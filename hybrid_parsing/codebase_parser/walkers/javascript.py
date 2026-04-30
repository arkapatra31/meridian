"""JavaScript / TypeScript / TSX tree-sitter walker — Pass 1 extraction.

Emits:
  - Nodes: module / class / function / method
  - EXTRACTED edges: CONTAINS, INHERITS (same-file), CALLS (same-file bare names)
  - AmbiguousRef: imports, cross-file extends, qualified / unresolved calls

One shared walker, three thin entry points covering:
  javascript (.js, .jsx, .mjs, .cjs)
  typescript (.ts)
  tsx        (.tsx)
"""

from __future__ import annotations

from pathlib import Path

from tree_sitter_language_pack import get_parser

from ..models import AmbiguousRef, Edge, Node

_parsers: dict[str, object] = {}

# Bare identifiers and member-expression receivers that are never project nodes.
# Calls to these are dropped rather than handed to Pass 2.
_JS_GLOBAL_OBJECTS: frozenset[str] = frozenset({
    # Language built-ins
    "Object", "Array", "String", "Number", "Boolean", "BigInt", "Symbol",
    "Function", "Promise", "Proxy", "Reflect",
    "Map", "Set", "WeakMap", "WeakSet", "WeakRef",
    "ArrayBuffer", "DataView", "SharedArrayBuffer",
    "Int8Array", "Uint8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array",
    "Int32Array", "Uint32Array", "Float32Array", "Float64Array",
    "BigInt64Array", "BigUint64Array",
    "Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError",
    "URIError", "EvalError",
    "RegExp", "Date", "JSON", "Math", "Intl", "Atomics",
    "URL", "URLSearchParams",
    # Browser globals
    "window", "document", "navigator", "location", "history",
    "localStorage", "sessionStorage", "performance", "screen",
    "console", "fetch", "XMLHttpRequest", "WebSocket", "EventSource",
    # Node.js globals
    "process", "global", "Buffer",
    # Global functions (bare calls)
    "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "setImmediate", "clearImmediate", "queueMicrotask",
    "parseInt", "parseFloat", "isNaN", "isFinite",
    "encodeURIComponent", "decodeURIComponent",
    "encodeURI", "decodeURI", "escape", "unescape",
    "require",
})


def _get_parser(lang: str):
    if lang not in _parsers:
        _parsers[lang] = get_parser(lang)
    return _parsers[lang]


def parse_javascript(rel_path: str, source: bytes, repo_root: Path | None = None):
    return _parse(rel_path, source, "javascript", repo_root)


def parse_typescript(rel_path: str, source: bytes, repo_root: Path | None = None):
    return _parse(rel_path, source, "typescript", repo_root)


def parse_tsx(rel_path: str, source: bytes, repo_root: Path | None = None):
    return _parse(rel_path, source, "tsx", repo_root)


def _parse(
    rel_path: str, source: bytes, lang: str, repo_root: Path | None = None
) -> tuple[list[Node], list[Edge], list[AmbiguousRef]]:
    tree = _get_parser(lang).parse(source)
    walker = _JsWalker(rel_path, source, lang, repo_root)
    walker.visit_program(tree.root_node)
    return walker.nodes, walker.edges, walker.ambiguous


class _JsWalker:
    def __init__(self, rel_path: str, source: bytes, lang: str, repo_root: Path | None = None) -> None:
        self.file = rel_path
        self.src = source
        self.lang = lang
        self.repo_root = repo_root
        self.module_id = rel_path
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.ambiguous: list[AmbiguousRef] = []
        # Top-level name → node id for same-file resolution.
        self.local_defs: dict[str, str] = {}

    def _text(self, n) -> str:
        return self.src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")

    def visit_program(self, root) -> None:
        self._collect_top_defs(root)

        self.nodes.append(
            Node(
                id=self.module_id,
                type="module",
                name=self.module_id.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                file=self.file,
                line_start=root.start_point[0] + 1,
                line_end=root.end_point[0] + 1,
                language=self.lang,
            )
        )

        for child in root.named_children:
            self._visit_top(child)

    def _collect_top_defs(self, root) -> None:
        for child in root.named_children:
            node = self._unwrap_export(child)
            if node is None:
                node = child
            t = node.type
            if t in ("class_declaration", "interface_declaration"):
                name_n = node.named_children[0] if node.named_children else None
                if name_n and name_n.type in ("identifier", "type_identifier"):
                    name = self._text(name_n)
                    self.local_defs[name] = f"{self.module_id}::{name}"
            elif t == "function_declaration":
                name_n = node.child_by_field_name("name")
                if name_n:
                    name = self._text(name_n)
                    self.local_defs[name] = f"{self.module_id}::{name}"
            elif t in ("lexical_declaration", "variable_declaration"):
                for decl in node.named_children:
                    if decl.type == "variable_declarator":
                        id_n = decl.child_by_field_name("name")
                        val_n = decl.child_by_field_name("value")
                        if id_n and val_n and val_n.type in (
                            "arrow_function", "function", "function_expression"
                        ):
                            name = self._text(id_n)
                            self.local_defs[name] = f"{self.module_id}::{name}"

    def _unwrap_export(self, n):
        if n.type == "export_statement":
            for c in n.named_children:
                if c.type not in ("default", "identifier", "string"):
                    return c
        return None

    def _visit_top(self, n) -> None:
        node = self._unwrap_export(n)
        if node is None:
            node = n
        t = node.type
        if t == "class_declaration":
            self._visit_class(node)
        elif t == "interface_declaration":
            self._visit_interface(node)
        elif t == "function_declaration":
            self._visit_function(node)
        elif t in ("lexical_declaration", "variable_declaration"):
            self._visit_var_decl(node)
        elif t == "import_statement":
            source_n = next(
                (c for c in node.named_children if c.type == "string"), None
            )
            if source_n is not None:
                raw_source = self._text(source_n).strip("\"'`")
                if self._is_npm_package(raw_source):
                    return  # npm/third-party — never a project node
                resolved = self._resolve_js_import(raw_source)
                if resolved is not None:
                    self.edges.append(Edge(self.module_id, resolved, "IMPORTS"))
                    return
            self.ambiguous.append(
                AmbiguousRef(
                    source=self.module_id,
                    raw=self._text(node).strip(),
                    kind="import",
                    file=self.file,
                    line=node.start_point[0] + 1,
                )
            )

    def _visit_class(self, n) -> None:
        name_n = n.named_children[0] if n.named_children else None
        if name_n is None or name_n.type not in ("identifier", "type_identifier"):
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
                language=self.lang,
            )
        )
        self.edges.append(Edge(self.module_id, cls_id, "CONTAINS"))

        # extends clause
        for c in n.named_children:
            if c.type == "class_heritage":
                for cc in c.named_children:
                    if cc.type in ("identifier", "type_identifier"):
                        raw = self._text(cc)
                        if raw in self.local_defs:
                            self.edges.append(Edge(cls_id, self.local_defs[raw], "INHERITS"))
                        else:
                            self.ambiguous.append(
                                AmbiguousRef(cls_id, raw, "inherits", self.file, cc.start_point[0] + 1)
                            )

        # collect method names for same-class CALLS
        class_local: dict[str, str] = {}
        body = n.named_children[-1] if n.named_children else None
        if body and body.type == "class_body":
            for c in body.named_children:
                if c.type == "method_definition":
                    mn = c.child_by_field_name("name")
                    if mn:
                        mname = self._text(mn)
                        class_local[mname] = f"{cls_id}.{mname}"

            for c in body.named_children:
                if c.type == "method_definition":
                    self._visit_method(c, parent=cls_id, class_name=name, class_local=class_local)

    def _visit_interface(self, n) -> None:
        # TypeScript interfaces — treat as class nodes (no callable body, no call walking)
        name_n = n.named_children[0] if n.named_children else None
        if name_n is None or name_n.type not in ("identifier", "type_identifier"):
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
                language=self.lang,
            )
        )
        self.edges.append(Edge(self.module_id, cls_id, "CONTAINS"))

        for c in n.named_children:
            if c.type in ("extends_type_clause", "extends_clause"):
                for cc in self._find_all(c, {"identifier", "type_identifier"}):
                    raw = self._text(cc)
                    if raw in self.local_defs:
                        self.edges.append(Edge(cls_id, self.local_defs[raw], "INHERITS"))
                    else:
                        self.ambiguous.append(
                            AmbiguousRef(cls_id, raw, "inherits", self.file, cc.start_point[0] + 1)
                        )

    def _visit_function(self, n) -> None:
        name_n = n.child_by_field_name("name")
        if name_n is None:
            return
        name = self._text(name_n)
        fid = f"{self.module_id}::{name}"
        params_n = n.child_by_field_name("parameters") or n.child_by_field_name("parameter")
        params = self._params(params_n) if params_n else []

        self.nodes.append(
            Node(
                id=fid,
                type="function",
                name=name,
                file=self.file,
                line_start=n.start_point[0] + 1,
                line_end=n.end_point[0] + 1,
                language=self.lang,
                params=params,
            )
        )
        self.edges.append(Edge(self.module_id, fid, "CONTAINS"))

        body = n.child_by_field_name("body")
        if body:
            self._collect_calls(body, fid, class_local={})

    def _visit_var_decl(self, n) -> None:
        for decl in n.named_children:
            if decl.type != "variable_declarator":
                continue
            id_n = decl.child_by_field_name("name")
            val_n = decl.child_by_field_name("value")
            if id_n is None or val_n is None:
                continue
            if val_n.type not in ("arrow_function", "function", "function_expression"):
                continue
            name = self._text(id_n)
            fid = f"{self.module_id}::{name}"
            params_n = val_n.child_by_field_name("parameters") or val_n.child_by_field_name("parameter")
            params = self._params(params_n) if params_n else []

            self.nodes.append(
                Node(
                    id=fid,
                    type="function",
                    name=name,
                    file=self.file,
                    line_start=val_n.start_point[0] + 1,
                    line_end=val_n.end_point[0] + 1,
                    language=self.lang,
                    params=params,
                )
            )
            self.edges.append(Edge(self.module_id, fid, "CONTAINS"))
            body = val_n.child_by_field_name("body")
            if body:
                self._collect_calls(body, fid, class_local={})

    def _visit_method(self, n, parent: str, class_name: str, class_local: dict[str, str]) -> None:
        name_n = n.child_by_field_name("name")
        if name_n is None:
            return
        name = self._text(name_n)
        mid = f"{parent}.{name}"
        params_n = n.child_by_field_name("parameters")
        params = self._params(params_n) if params_n else []

        self.nodes.append(
            Node(
                id=mid,
                type="method",
                name=name,
                file=self.file,
                line_start=n.start_point[0] + 1,
                line_end=n.end_point[0] + 1,
                language=self.lang,
                params=params,
            )
        )
        self.edges.append(Edge(parent, mid, "CONTAINS"))

        body = n.child_by_field_name("body")
        if body:
            self._collect_calls(body, mid, class_local)

    def _collect_calls(self, n, source_id: str, class_local: dict[str, str]) -> None:
        for child in n.named_children:
            if child.type in (
                "function_declaration", "function", "function_expression",
                "arrow_function", "class_declaration", "class",
            ):
                continue
            if child.type == "call_expression":
                self._handle_call(child, source_id, class_local)
            self._collect_calls(child, source_id, class_local)

    def _handle_call(self, n, source_id: str, class_local: dict[str, str]) -> None:
        fn = n.child_by_field_name("function")
        if fn is None:
            return
        if fn.type == "identifier":
            raw = self._text(fn)
            if raw in class_local:
                self.edges.append(Edge(source_id, class_local[raw], "CALLS"))
            elif raw in self.local_defs:
                self.edges.append(Edge(source_id, self.local_defs[raw], "CALLS"))
            elif raw in _JS_GLOBAL_OBJECTS:
                return  # stdlib / runtime — never a project node
            else:
                self.ambiguous.append(
                    AmbiguousRef(source_id, raw, "call", self.file, fn.start_point[0] + 1)
                )
        elif fn.type == "member_expression":
            obj_n = fn.child_by_field_name("object")
            prop_n = fn.child_by_field_name("property")
            if obj_n is not None and prop_n is not None:
                obj_text = self._text(obj_n)
                prop_text = self._text(prop_n)
                if obj_text == "this" and prop_text in class_local:
                    self.edges.append(Edge(source_id, class_local[prop_text], "CALLS"))
                    return
                if obj_text in _JS_GLOBAL_OBJECTS:
                    return  # e.g. console.log, Math.floor, JSON.stringify
            self.ambiguous.append(
                AmbiguousRef(source_id, self._text(fn), "call", self.file, fn.start_point[0] + 1)
            )
        else:
            self.ambiguous.append(
                AmbiguousRef(source_id, self._text(fn), "call", self.file, fn.start_point[0] + 1)
            )

    @staticmethod
    def _is_npm_package(source_str: str) -> bool:
        """True for npm/node_modules imports that are never project nodes.

        Drops bare package names ('react', 'axios', 'lodash') and scoped packages
        ('@nestjs/core', '@angular/common'). Keeps path aliases that MAY resolve
        to project files: '@/' (Vite/CRA), '~/', '#' (TypeScript paths).
        """
        if source_str.startswith(("./", "../")):
            return False  # relative — handled by _resolve_js_import
        if source_str.startswith("@/") or source_str.startswith("~/") or source_str.startswith("#"):
            return False  # project-relative path aliases
        return True  # npm package or bare specifier

    def _resolve_js_import(self, source_str: str) -> str | None:
        """Resolve a relative import path to a repo-relative file path, or None."""
        if self.repo_root is None:
            return None
        if not (source_str.startswith("./") or source_str.startswith("../")):
            return None
        try:
            repo_root = self.repo_root.resolve()
            file_dir = (repo_root / self.file).parent
            base = (file_dir / source_str).resolve()
            # Already has a supported extension
            if base.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
                if base.is_file():
                    return base.relative_to(repo_root).as_posix()
            # Try appending extensions
            for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
                candidate = base.with_suffix(suffix)
                if candidate.is_file():
                    return candidate.relative_to(repo_root).as_posix()
            # Try index files (directory import)
            for index in ("index.ts", "index.tsx", "index.js"):
                candidate = base / index
                if candidate.is_file():
                    return candidate.relative_to(repo_root).as_posix()
        except (OSError, ValueError):
            pass
        return None

    def _params(self, params_n) -> list[str]:
        out: list[str] = []
        for p in params_n.named_children:
            t = p.type
            if t == "identifier":
                out.append(self._text(p))
            elif t in ("assignment_pattern", "rest_pattern"):
                left = p.named_children[0] if p.named_children else None
                if left:
                    out.append(self._text(left))
            elif t == "object_pattern":
                out.append(self._text(p))
            elif t in ("required_parameter", "optional_parameter"):
                pn = p.child_by_field_name("pattern") or (p.named_children[0] if p.named_children else None)
                if pn:
                    out.append(self._text(pn).split(":")[0].strip())
        return out

    def _find_all(self, n, types: set[str]) -> list:
        results = []
        for child in n.named_children:
            if child.type in types:
                results.append(child)
            results.extend(self._find_all(child, types))
        return results
