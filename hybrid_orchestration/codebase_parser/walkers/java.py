"""Java tree-sitter walker — Pass 1 extraction.

Emits:
  - Nodes: module (per file) / class / method (includes constructors)
  - EXTRACTED edges: CONTAINS, CALLS (same-file bare method names)
  - AmbiguousRef: imports, extends/implements, cross-file / qualified calls
"""

from __future__ import annotations

from tree_sitter_language_pack import get_parser

from ..models import AmbiguousRef, Edge, Node

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
                self.ambiguous.append(
                    AmbiguousRef(
                        source=self.module_id,
                        raw=self._text(child).strip(),
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
        else:
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

    def _find_all(self, n, types: set[str]) -> list:
        results = []
        for child in n.named_children:
            if child.type in types:
                results.append(child)
            results.extend(self._find_all(child, types))
        return results
