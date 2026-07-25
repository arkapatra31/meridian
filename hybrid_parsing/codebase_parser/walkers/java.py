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
    "org.hamcrest.", "com.github.tomakehurst.", "org.awaitility.",
    "com.tngtech.archunit.",
    # Logging
    "org.slf4j.", "ch.qos.logback.", "org.apache.logging.",
    "org.apache.log4j.", "org.jboss.logging.",
    # Apache (Commons, HTTP, Kafka, Avro, Curator, POI, PDFBox, Velocity, …)
    "org.apache.",
    # Google libraries (Guava, Gson, Protobuf, Cloud, Firebase, …)
    "com.google.",
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
    # JWT / auth
    "io.jsonwebtoken.", "com.auth0.", "com.nimbusds.", "org.keycloak.",
    "org.bouncycastle.", "org.passay.",
    # MongoDB
    "org.mongodb.", "com.mongodb.",
    # Redis clients
    "redis.clients.", "io.lettuce.", "org.redisson.",
    # Connection pooling
    "com.zaxxer.", "com.mchange.",
    # Elasticsearch / OpenSearch
    "org.elasticsearch.", "co.elastic.", "org.opensearch.",
    # Caching
    "com.github.benmanes.caffeine.", "net.sf.ehcache.", "org.ehcache.",
    # Scheduling
    "org.quartz.",
    # Template engines
    "org.thymeleaf.", "freemarker.", "com.github.jknack.",
    # HTTP clients
    "feign.", "okhttp3.", "retrofit2.",
    # Messaging
    "com.rabbitmq.", "io.confluent.", "io.nats.", "io.debezium.",
    # JDBC drivers (never project code)
    "org.postgresql.", "com.mysql.", "oracle.jdbc.", "org.mariadb.",
    "com.h2database.", "org.hsqldb.", "com.microsoft.sqlserver.",
    # NoSQL
    "com.datastax.", "org.neo4j.", "com.couchbase.", "io.minio.",
    # Document / reporting
    "org.jsoup.", "com.itextpdf.", "net.sf.jasperreports.",
    # CSV / data
    "com.opencsv.", "com.univocity.",
    # Observability / error tracking
    "io.sentry.", "com.bugsnag.",
    # Misc utilities
    "org.yaml.", "com.esotericsoftware.", "net.sf.", "org.osgi.",
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
    # java.util.concurrent
    "CompletableFuture", "Future", "FutureTask",
    "Executors", "CountDownLatch", "CyclicBarrier", "Semaphore",
    "AtomicInteger", "AtomicLong", "AtomicBoolean", "AtomicReference",
    "ConcurrentHashMap", "CopyOnWriteArrayList",
    # java.time (always external — project code never defines these)
    "LocalDate", "LocalDateTime", "LocalTime", "ZonedDateTime",
    "OffsetDateTime", "OffsetTime", "Instant", "Duration", "Period",
    "ZoneId", "ZoneOffset", "Clock", "DateTimeFormatter", "YearMonth",
    # Legacy date/time
    "Date", "Calendar", "GregorianCalendar", "TimeZone", "SimpleDateFormat",
    # java.math
    "BigDecimal", "BigInteger",
    # java.io / java.nio
    "File", "Path", "Files", "Paths",
    "InputStream", "OutputStream", "BufferedReader", "BufferedWriter",
    "PrintWriter", "PrintStream",
    "FileInputStream", "FileOutputStream",
    "ByteArrayInputStream", "ByteArrayOutputStream",
    "InputStreamReader", "OutputStreamWriter",
    # java.nio.charset / regex
    "Charset", "StandardCharsets", "Pattern", "Matcher",
    # java.security / crypto
    "MessageDigest", "Cipher", "SecretKey", "KeyFactory", "KeyPair",
    "SecureRandom",
    # java.util.Properties
    "Properties",
    # Logging (ubiquitous in Java projects)
    "Logger", "LoggerFactory", "LogManager",
    "log", "logger", "LOG", "LOGGER",
    # Spring framework receiver types
    "ResponseEntity", "HttpStatus", "HttpHeaders", "MediaType",
    "RestTemplate", "WebClient", "WebClientBuilder",
    "HttpEntity", "HttpMethod", "MultiValueMap", "LinkedMultiValueMap",
    "BeanDefinitionRegistry", "ApplicationContext", "ConfigurableApplicationContext",
    "Environment", "PropertySource",
    "Assert", "StringUtils", "CollectionUtils", "ObjectUtils",
    "BeanUtils", "ReflectionUtils", "ClassUtils", "AopUtils",
    "ConversionService", "MessageSource",
    "ResourceLoader", "Resource", "ClassPathResource",
    "TransactionTemplate", "TransactionStatus",
    "JdbcTemplate", "NamedParameterJdbcTemplate",
    # Spring MVC / Web
    "HttpServletRequest", "HttpServletResponse", "HttpSession",
    "BindingResult", "Errors", "Model", "ModelAndView",
    "RedirectAttributes", "MultipartFile",
    "Pageable", "PageRequest", "Sort", "Page",
    # Spring Security
    "Authentication", "SecurityContext", "SecurityContextHolder",
    "Principal",
    # Spring Data
    "ExampleMatcher",
    # Lombok-generated common names
    "builder", "Builder",
    # Jackson / serialization
    "ObjectMapper", "JsonNode", "ObjectNode", "ArrayNode",
    "ObjectWriter", "ObjectReader", "TypeReference",
    # JPA / Hibernate
    "EntityManager", "EntityManagerFactory",
    "TypedQuery", "CriteriaQuery", "CriteriaBuilder",
    "Session", "SessionFactory",
    # Testing frameworks
    "Mockito", "MockMvcResultMatchers", "MockMvcRequestBuilders",
    "Assertions", "Matchers", "MockMvc",
    # Reactor / reactive
    "Mono", "Flux", "Scheduler", "Schedulers",
    # Apache Commons utilities
    "IOUtils", "FileUtils", "DateUtils",
    # ModelMapper
    "ModelMapper",
    # java.lang exceptions not yet covered (extends these)
    "Exception", "IOException", "InterruptedException",
    "CloneNotSupportedException", "ReflectiveOperationException",
    "ClassNotFoundException", "NoSuchMethodException",
    "NoSuchFieldException",
    # java.util abstract collections (commonly extended)
    "AbstractList", "AbstractMap", "AbstractSet",
    "AbstractCollection", "AbstractQueue", "AbstractSequentialList",
    # Spring filter / security base classes (commonly extended)
    "OncePerRequestFilter", "GenericFilterBean",
    "UsernamePasswordAuthenticationFilter",
    "AbstractAuthenticationProcessingFilter",
    "AbstractSecurityInterceptor",
    "WebSecurityConfigurerAdapter",  # deprecated but still in many codebases
    "AbstractHealthIndicator",
    # Spring MVC base
    "AbstractController", "AbstractCommandController",
    "WebMvcConfigurerAdapter",  # deprecated but common
    # Spring Data base
    "SimpleJpaRepository",
})

# Interface names that are always from the stdlib or well-known frameworks —
# dropped in Pass 1 so the reducer never wastes index lookups on them.
_JAVA_STDLIB_INTERFACE_NAMES: frozenset[str] = frozenset({
    # java.lang
    "Comparable", "Cloneable", "Runnable", "Iterable", "CharSequence",
    "Appendable", "AutoCloseable", "Readable",
    # java.io
    "Serializable", "Closeable", "Flushable",
    # java.util (Collection hierarchy)
    "Collection", "List", "Set", "Map", "Queue", "Deque",
    "SortedSet", "SortedMap", "NavigableSet", "NavigableMap",
    "Iterator", "ListIterator", "Enumeration", "EventListener",
    "Comparator", "Observer",
    # java.util.function (functional interfaces — always lambda/method-ref targets)
    "Supplier", "Consumer", "Function", "Predicate",
    "BiFunction", "BiConsumer", "BiPredicate",
    "UnaryOperator", "BinaryOperator",
    "IntSupplier", "LongSupplier", "DoubleSupplier",
    "IntConsumer", "LongConsumer", "DoubleConsumer",
    "IntFunction", "LongFunction", "DoubleFunction",
    "ToIntFunction", "ToLongFunction", "ToDoubleFunction",
    # java.util.concurrent
    "Callable", "Executor", "ExecutorService", "ScheduledExecutorService",
    "Future", "CompletionStage", "CompletableFuture",
    "RejectedExecutionHandler", "ThreadFactory",
    # javax.servlet / jakarta.servlet
    "Filter", "Servlet", "GenericServlet",
    "ServletContextListener", "HttpSessionListener",
    "ServletRequestListener", "AsyncListener",
    # Spring framework
    "ApplicationContextAware", "BeanFactoryAware", "InitializingBean",
    "DisposableBean", "CommandLineRunner", "ApplicationRunner",
    "HandlerInterceptor", "WebMvcConfigurer",
    "UserDetails", "UserDetailsService", "AuthenticationProvider",
    "GrantedAuthority",
    "Ordered", "PriorityOrdered",
    "ApplicationListener", "ApplicationEventPublisher",
    "FactoryBean", "BeanPostProcessor",
    "BeanDefinitionRegistryPostProcessor",
    "MessageConverter", "HttpMessageConverter",
    "Converter", "GenericConverter",
    "Validator", "SmartValidator",
    "HandlerMethodArgumentResolver", "HandlerExceptionResolver",
    "ViewResolver", "LocaleResolver",
    "MessageSource", "ResourceLoader",
    "ImportSelector", "ImportBeanDefinitionRegistrar",
    "Condition", "Lifecycle", "SmartLifecycle",
    # Spring Data / JPA (project classes extend these, but the interfaces are external)
    "Repository", "CrudRepository", "JpaRepository",
    "PagingAndSortingRepository", "JpaSpecificationExecutor",
    "ReactiveCrudRepository", "ReactiveJpaRepository",
    "QueryByExampleExecutor",
    # javax.validation / jakarta.validation
    "ConstraintValidator",
    # Reactor
    "Publisher", "Subscriber", "Subscription", "Processor",
})

# Method names that are universally from java.lang.Object, logging frameworks,
# or builder APIs. For bare calls and this.X() calls these are dropped when not
# found in class_local (i.e. not defined in the same class) — they must be
# inherited framework/stdlib methods and can never be project-level graph nodes.
# Also dropped for qualified calls regardless of receiver.
_JAVA_COMMON_CALL_NAMES: frozenset[str] = frozenset({
    # java.lang.Object (every Java object inherits these)
    "toString", "hashCode", "equals", "compareTo", "clone", "finalize",
    "wait", "notify", "notifyAll", "getClass",
    # java.lang.Enum (every enum has these)
    "name", "ordinal", "values", "valueOf",
    # SLF4J / Log4j / JUL (always on external Logger objects)
    "debug", "info", "warn", "error", "trace", "fatal",
    "isDebugEnabled", "isInfoEnabled", "isWarnEnabled", "isErrorEnabled",
    "isTraceEnabled", "isFatalEnabled",
    "atDebug", "atInfo", "atWarn", "atError", "atTrace",  # SLF4J 2.x fluent API
    # Lombok/protobuf/Spring/Jackson builder terminal
    "build", "builder", "toBuilder", "newBuilder",
    # java.lang.Iterable / Collection universal operations
    "iterator", "forEach", "spliterator",
    # Optional (always on external Optional objects — project code uses orElseGet etc.)
    "orElse", "orElseGet", "orElseThrow", "orElseNull",
    "isPresent", "isEmpty", "ifPresent", "ifPresentOrElse",
    "filter", "map", "flatMap", "or", "stream",
    # Stream terminal ops (always on external Stream objects)
    "collect", "count", "findFirst", "findAny",
    "anyMatch", "allMatch", "noneMatch",
    "min", "max", "sum", "average",
    "toList", "toArray",
    # CompletableFuture
    "get", "join", "isDone", "isCancelled", "cancel",
    "thenApply", "thenAccept", "thenRun", "thenCompose",
    "exceptionally", "handle", "whenComplete",
    # java.lang.String (called on local String vars — receiver type unknown to static analysis)
    "charAt", "codePointAt", "codePoints", "chars", "lines",
    "indexOf", "lastIndexOf",
    "startsWith", "endsWith",
    "substring", "subSequence",
    "replace", "replaceAll", "replaceFirst",
    "split", "matches", "length",
    "toUpperCase", "toLowerCase", "toCharArray",
    "trim", "strip", "stripLeading", "stripTrailing",
    "isBlank", "formatted", "concat", "intern",
    # java.util.Collection / List operations
    "size", "contains", "containsAll",
    "addAll", "removeAll", "removeIf", "retainAll",
    "clear", "subList",
    "addFirst", "addLast", "getFirst", "getLast",
    "removeFirst", "removeLast",
    "copyOf",
    # java.util.Map operations
    "keySet", "entrySet",
    "containsKey", "containsValue",
    "putAll", "putIfAbsent", "getOrDefault",
    "computeIfAbsent", "computeIfPresent", "compute", "merge",
    # java.util.Iterator
    "hasNext", "next",
    # AutoCloseable / Closeable / Flushable
    "close", "flush",
    # java.util.Comparator
    "compare",
})

def _is_java_accessor(name: str) -> bool:
    """True if name follows Java getter/setter/builder accessor naming convention.

    Checks camelCase prefix (next char must be uppercase) to avoid false
    positives on words like 'issue', 'setup', 'settle', 'isset'.
    """
    for prefix in ("get", "set", "has", "with"):
        plen = len(prefix)
        if len(name) > plen and name.startswith(prefix) and name[plen].isupper():
            return True
    return len(name) > 2 and name.startswith("is") and name[2].isupper()


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

        # extends — handle both plain and generic superclass (e.g. BaseService<T>)
        superclass = n.child_by_field_name("superclass")
        if superclass is not None:
            for c in superclass.named_children:
                if c.type in ("type_identifier", "identifier"):
                    raw = self._text(c)
                    if raw in _JAVA_STDLIB_TYPES or raw in _JAVA_STDLIB_INTERFACE_NAMES:
                        continue  # stdlib base class — nothing to link
                    if raw in self.local_defs:
                        self.edges.append(Edge(cls_id, self.local_defs[raw], "INHERITS"))
                    else:
                        self.ambiguous.append(
                            AmbiguousRef(cls_id, raw, "inherits", self.file, c.start_point[0] + 1)
                        )
                elif c.type == "generic_type":
                    # "extends BaseService<T>" — take only the class name, not T
                    name_n = c.named_children[0] if c.named_children else None
                    if name_n and name_n.type in ("type_identifier", "identifier"):
                        raw = self._text(name_n)
                        if raw in _JAVA_STDLIB_TYPES or raw in _JAVA_STDLIB_INTERFACE_NAMES:
                            continue  # stdlib base class — nothing to link
                        if raw in self.local_defs:
                            self.edges.append(Edge(cls_id, self.local_defs[raw], "INHERITS"))
                        else:
                            self.ambiguous.append(
                                AmbiguousRef(cls_id, raw, "inherits", self.file, name_n.start_point[0] + 1)
                            )

        # implements — walk only top-level interface names; do NOT recurse into
        # generic type arguments (e.g. Repository<User, Long> must yield only
        # "Repository", not "User" or "Long").
        interfaces = n.child_by_field_name("interfaces")
        if interfaces is not None:
            for iface_node in self._iter_interface_names(interfaces):
                raw = self._text(iface_node)
                if raw in _JAVA_STDLIB_INTERFACE_NAMES:
                    continue  # always external — nothing to link
                if raw in self.local_defs:
                    self.edges.append(Edge(cls_id, self.local_defs[raw], "INHERITS"))
                else:
                    self.ambiguous.append(
                        AmbiguousRef(cls_id, raw, "inherits", self.file, iface_node.start_point[0] + 1)
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
        type_n = n.child_by_field_name("type")
        return_type = self._text(type_n).replace("\n", " ").strip() if type_n else None

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
                return_type=return_type,
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
            elif raw in _JAVA_COMMON_CALL_NAMES:
                pass  # universally external — nothing to link
            elif _is_java_accessor(raw):
                pass  # getter/setter/builder naming convention — inherited, never a cross-file node
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
            elif raw in _JAVA_COMMON_CALL_NAMES:
                pass  # universally external — nothing to link
            elif _is_java_accessor(raw):
                pass  # getter/setter/builder — inherited accessor, not a cross-file node
            else:
                self.ambiguous.append(
                    AmbiguousRef(source_id, raw, "call", self.file, name_nodes[0].start_point[0] + 1)
                )
        else:
            # Qualified call — drop if the root receiver is a known stdlib type,
            # if the method name is universally external, or if it follows the
            # Java getter/setter/builder accessor naming convention.
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
            method_name = self._text(name_nodes[-1]) if name_nodes else None
            if method_name in _JAVA_COMMON_CALL_NAMES:
                return  # universally external method, regardless of receiver
            if method_name and _is_java_accessor(method_name):
                return  # user.getName() / order.getTotal() / page.isLast() — never a project node
            raw = self._text(n)
            self.ambiguous.append(
                AmbiguousRef(source_id, raw.split("(")[0].strip(), "call", self.file, n.start_point[0] + 1)
            )

    def _params(self, params_n) -> list[str]:
        out: list[str] = []
        for p in params_n.named_children:
            if p.type == "formal_parameter":
                type_n = p.child_by_field_name("type")
                name_n = p.child_by_field_name("name")
                if name_n:
                    name = self._text(name_n)
                    type_str = self._text(type_n).replace("\n", " ").strip() if type_n else None
                    out.append(f"{name}: {type_str}" if type_str else name)
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

    def _iter_interface_names(self, interfaces_node):
        """Yield type_identifier nodes for each implemented interface name only.

        Walks the interfaces field without recursing into generic type arguments,
        so "implements Repository<User, Long>" yields only the "Repository" node,
        never "User" or "Long".
        """
        for child in interfaces_node.children:
            if not child.is_named:
                continue
            if child.type in ("type_list", "interface_type_list"):
                for t in child.named_children:
                    yield from self._extract_interface_type(t)
            else:
                yield from self._extract_interface_type(child)

    def _extract_interface_type(self, node):
        """Yield the name node from a type_identifier or generic_type node."""
        if node.type == "type_identifier":
            yield node
        elif node.type == "generic_type" and node.named_children:
            name_n = node.named_children[0]
            if name_n.type == "type_identifier":
                yield name_n

    def _find_all(self, n, types: set[str]) -> list:
        results = []
        for child in n.named_children:
            if child.type in types:
                results.append(child)
            results.extend(self._find_all(child, types))
        return results
