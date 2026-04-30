"""Java tree-sitter walker — Pass 1 extraction.

Emits:
  - Nodes: module (per file) / class / method (includes constructors)
  - EXTRACTED edges: CONTAINS, CALLS (same-file bare method names)
  - AmbiguousRef: imports, extends/implements, cross-file / qualified calls
"""

from __future__ import annotations

from tree_sitter_language_pack import get_parser

from ..models import AmbiguousRef, Edge, Node

# Java import prefixes that are always external — never project nodes.
# Dropped in Pass 1 so Pass 2 never wastes tokens on them.
_JAVA_STDLIB_PREFIXES: tuple[str, ...] = (
    # JDK / stdlib
    "java.", "javax.", "sun.", "com.sun.", "jdk.",
    # Spring ecosystem
    "org.springframework.", "io.spring.",
    # Jakarta EE (successor to javax.*)
    "jakarta.",
    # Persistence / ORM
    "org.hibernate.", "javax.persistence.", "com.querydsl.",
    # Testing
    "org.junit.", "org.testng.", "org.mockito.", "org.assertj.",
    "org.hamcrest.", "com.github.tomakehurst.",
    # Logging
    "org.slf4j.", "ch.qos.logback.", "org.apache.logging.",
    "org.apache.log4j.", "org.jboss.logging.",
    # Apache Commons / utilities
    "org.apache.commons.", "org.apache.http.", "org.apache.tomcat.",
    "org.apache.kafka.", "org.apache.avro.", "org.apache.curator.",
    # Google libraries
    "com.google.common.", "com.google.gson.", "com.google.protobuf.",
    "com.google.cloud.", "com.google.api.",
    # JSON / serialization
    "com.fasterxml.jackson.", "org.json.",
    # Resilience / observability
    "io.micrometer.", "io.github.resilience4j.", "io.opentelemetry.",
    "io.prometheus.",
    # Cloud SDKs
    "com.amazonaws.", "software.amazon.", "com.azure.", "com.microsoft.",
    # Health / FHIR
    "org.hl7.", "ca.uhn.fhir.", "com.philips.",
    # MapStruct / Lombok (annotation processors)
    "org.mapstruct.", "lombok.",
    # Reactor / RxJava
    "reactor.", "io.reactivex.",
    # Netty / gRPC
    "io.netty.", "io.grpc.",
    # Swagger / OpenAPI
    "io.swagger.", "org.springdoc.",
    # Flyway / Liquibase
    "org.flywaydb.", "org.liquibase.",
)

# Known external receiver types whose method calls are never project-level graph
# edges. When the first identifier in a qualified call matches one of these, the
# call is dropped instead of deferred to Pass 2.
_JAVA_STDLIB_TYPES: frozenset[str] = frozenset({
    # java.lang (always in scope, no import needed)
    "System", "Math", "String", "StringBuilder", "StringBuffer",
    "Object", "Class", "Enum", "Thread", "Runtime", "Process",
    "Integer", "Long", "Double", "Float", "Short", "Byte",
    "Boolean", "Character", "Number", "Void",
    "Exception", "RuntimeException", "Error", "Throwable",
    "IllegalArgumentException", "IllegalStateException",
    "NullPointerException", "IndexOutOfBoundsException",
    "UnsupportedOperationException", "StackOverflowError",
    # java.util (common, almost always imported)
    "Objects", "Arrays", "Collections", "Optional",
    "List", "ArrayList", "LinkedList",
    "Map", "HashMap", "LinkedHashMap", "TreeMap",
    "Set", "HashSet", "LinkedHashSet", "TreeSet",
    "Queue", "Deque", "ArrayDeque", "PriorityQueue",
    "Iterator", "Stream", "Collectors",
    "UUID", "Random", "Scanner",
    # Logging (ubiquitous in Java projects)
    "Logger", "LoggerFactory", "LogManager",
    "log", "logger", "LOG", "LOGGER",
    # Spring framework common receiver types
    "ResponseEntity", "HttpStatus", "HttpHeaders", "MediaType",
    "RequestMapping", "RestTemplate", "WebClient",
    "BeanDefinitionRegistry", "ApplicationContext", "Environment",
    "Assert", "StringUtils", "CollectionUtils", "ObjectUtils",
    # Lombok-generated common names
    "builder", "Builder",
    # Jackson / serialization
    "ObjectMapper", "JsonNode", "ObjectNode", "ArrayNode",
    # Testing frameworks
    "Mockito", "MockMvcResultMatchers", "MockMvcRequestBuilders",
    "Assertions", "Matchers",
    # Reactor / reactive
    "Mono", "Flux", "Scheduler", "Schedulers",
    # Apache Commons
    "StringUtils", "IOUtils", "FileUtils", "DateUtils",
})

_parser = None


def _get_parser():
    global _parser
    if _parser is None:
        _parser = get_parser("java")
    return _parser


def parse_java(
    rel_path: str, source: bytes, repo_root: object = None
) -> tuple[list[Node], list[Edge], list[AmbiguousRef]]:
    tree = _get_parser().parse(source)
    walker = _JavaWalker(rel_path, source)
    walker.visit_program(tree.root_node)
    return walker.nodes, walker.edges, walker.ambiguous


class _JavaWalker:
    def __init__(self, rel_path: str, source: bytes) -> None:
        self.file = rel_path
        self.src = source
        self.module_id = rel_path
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.ambiguous: list[AmbiguousRef] = []
        # Same-file method name → node id for CALLS resolution.
        self.local_defs: dict[str, str] = {}

    def _text(self, n) -> str:
        return self.src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")

    def visit_program(self, root) -> None:
        # First pass: collect top-level class names for resolution.
        for child in root.named_children:
            if child.type in ("class_declaration", "interface_declaration", "enum_declaration"):
                name_n = child.child_by_field_name("name")
                if name_n:
                    name = self._text(name_n)
                    self.local_defs[name] = f"{self.module_id}::{name}"

        # Derive a meaningful module name from the package declaration if present.
        pkg_name = None
        for child in root.named_children:
            if child.type == "package_declaration":
                for c in child.named_children:
                    if c.type in ("scoped_identifier", "identifier"):
                        pkg_name = self._text(c)
                        break
                break

        self.nodes.append(
            Node(
                id=self.module_id,
                type="module",
                name=pkg_name or self.module_id,
                file=self.file,
                line_start=root.start_point[0] + 1,
                line_end=root.end_point[0] + 1,
                language="java",
            )
        )

        for child in root.named_children:
            t = child.type
            if t in ("class_declaration", "interface_declaration", "enum_declaration"):
                self._visit_class(child)
            elif t == "import_declaration":
                raw = self._text(child).strip()
                # Drop stdlib / JDK imports — Pass 2 has nothing to resolve.
                # Extract the dotted name (skip "import" keyword and trailing ";")
                dotted = raw.removeprefix("import").replace(";", "").strip()
                if dotted.startswith(_JAVA_STDLIB_PREFIXES):
                    continue
                self.ambiguous.append(
                    AmbiguousRef(
                        source=self.module_id,
                        raw=raw,
                        kind="import",
                        file=self.file,
                        line=child.start_point[0] + 1,
                    )
                )

    def _visit_class(self, n) -> None:
        name_n = n.child_by_field_name("name")
        if name_n is None:
            return
        name = self._text(name_n)
        cls_id = f"{self.module_id}::{name}"

        self.nodes.append(
            Node(
                id=cls_id,
                type="class",
                name=name,
                file=self.file,
                line_start=n.start_point[0] + 1,
                line_end=n.end_point[0] + 1,
                language="java",
            )
        )
        self.edges.append(Edge(self.module_id, cls_id, "CONTAINS"))

        # extends
        superclass = n.child_by_field_name("superclass")
        if superclass is not None:
            for c in superclass.named_children:
                if c.type in ("type_identifier", "identifier"):
                    raw = self._text(c)
                    if raw in self.local_defs:
                        self.edges.append(Edge(cls_id, self.local_defs[raw], "INHERITS"))
                    else:
                        self.ambiguous.append(
                            AmbiguousRef(cls_id, raw, "inherits", self.file, c.start_point[0] + 1)
                        )

        # implements
        interfaces = n.child_by_field_name("interfaces")
        if interfaces is not None:
            for c in self._find_all(interfaces, {"type_identifier", "identifier"}):
                raw = self._text(c)
                if raw in self.local_defs:
                    self.edges.append(Edge(cls_id, self.local_defs[raw], "INHERITS"))
                else:
                    self.ambiguous.append(
                        AmbiguousRef(cls_id, raw, "inherits", self.file, c.start_point[0] + 1)
                    )

        body = n.child_by_field_name("body")
        if body is None:
            return

        # Collect method names within this class for same-class CALLS resolution.
        class_local: dict[str, str] = {}
        for c in body.named_children:
            if c.type in ("method_declaration", "constructor_declaration"):
                mn = c.child_by_field_name("name")
                if mn:
                    mname = self._text(mn)
                    mid = f"{cls_id}.{mname}"
                    class_local[mname] = mid

        for c in body.named_children:
            if c.type in ("method_declaration", "constructor_declaration"):
                self._visit_method(c, parent=cls_id, class_name=name, class_local=class_local)
            elif c.type in ("class_declaration", "interface_declaration"):
                self._visit_class(c)

    def _visit_method(
        self, n, parent: str, class_name: str, class_local: dict[str, str]
    ) -> None:
        name_n = n.child_by_field_name("name")
        if name_n is None:
            return
        name = self._text(name_n)
        mid = f"{parent}.{name}"

        params_n = n.child_by_field_name("parameters")
        params = self._params(params_n) if params_n is not None else []

        self.nodes.append(
            Node(
                id=mid,
                type="method",
                name=name,
                file=self.file,
                line_start=n.start_point[0] + 1,
                line_end=n.end_point[0] + 1,
                language="java",
                params=params,
            )
        )
        self.edges.append(Edge(parent, mid, "CONTAINS"))

        body = n.child_by_field_name("body")
        if body is not None:
            self._collect_calls(body, source_id=mid, class_local=class_local)

    def _collect_calls(self, n, source_id: str, class_local: dict[str, str]) -> None:
        for child in n.named_children:
            if child.type in ("method_declaration", "constructor_declaration", "class_declaration"):
                continue
            if child.type == "method_invocation":
                self._handle_call(child, source_id, class_local)
            self._collect_calls(child, source_id, class_local)

    def _handle_call(self, n, source_id: str, class_local: dict[str, str]) -> None:
        children = n.named_children
        # method_invocation: [object?, name, arguments]
        # bare call: just [name, arguments] where name is an identifier
        name_nodes = [c for c in children if c.type == "identifier"]
        obj_like = [c for c in children if c.type not in ("identifier", "argument_list", "type_arguments")]

        if not obj_like and len(name_nodes) == 1:
            # Bare method name — may resolve to same class.
            raw = self._text(name_nodes[0])
            if raw in class_local:
                self.edges.append(Edge(source_id, class_local[raw], "CALLS"))
            elif raw in self.local_defs:
                self.edges.append(Edge(source_id, self.local_defs[raw], "CALLS"))
            else:
                self.ambiguous.append(
                    AmbiguousRef(source_id, raw, "call", self.file, name_nodes[0].start_point[0] + 1)
                )
        elif (
            len(obj_like) == 1
            and obj_like[0].type == "this"
            and len(name_nodes) == 1
        ):
            # this.method() — try same-class resolution before deferring.
            raw = self._text(name_nodes[0])
            if raw in class_local:
                self.edges.append(Edge(source_id, class_local[raw], "CALLS"))
            else:
                self.ambiguous.append(
                    AmbiguousRef(source_id, raw, "call", self.file, name_nodes[0].start_point[0] + 1)
                )
        else:
            # Qualified call — drop if the root receiver is a known stdlib type.
            # Two shapes: obj_like=[receiver_node] name_nodes=[method]
            #             obj_like=[]              name_nodes=[ReceiverType, method]
            if obj_like:
                receiver_text = self._leftmost_id(obj_like[0])
            elif len(name_nodes) > 1:
                receiver_text = self._text(name_nodes[0])
            else:
                receiver_text = None
            if receiver_text in _JAVA_STDLIB_TYPES:
                return
            raw = self._text(n)
            self.ambiguous.append(
                AmbiguousRef(source_id, raw.split("(")[0].strip(), "call", self.file, n.start_point[0] + 1)
            )

    def _params(self, params_n) -> list[str]:
        out: list[str] = []
        for p in params_n.named_children:
            if p.type == "formal_parameter":
                name_n = p.child_by_field_name("name")
                if name_n:
                    out.append(self._text(name_n))
            elif p.type == "spread_parameter":
                name_n = p.child_by_field_name("name")
                if name_n:
                    out.append(f"...{self._text(name_n)}")
        return out

    def _leftmost_id(self, n) -> str | None:
        """Return the text of the leftmost identifier in a node tree.
        Handles chained field access like System.out.println → 'System'.
        """
        if n.type in ("identifier", "type_identifier"):
            return self._text(n)
        obj = n.child_by_field_name("object")
        if obj is not None:
            return self._leftmost_id(obj)
        if n.named_children:
            return self._leftmost_id(n.named_children[0])
        return None

    def _find_all(self, n, types: set[str]) -> list:
        results = []
        for child in n.named_children:
            if child.type in types:
                results.append(child)
            results.extend(self._find_all(child, types))
        return results
