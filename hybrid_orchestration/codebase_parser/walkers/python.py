"""Python tree-sitter walker — Pass 1 extraction.

Emits:
  - Nodes: module / class / function / method
  - EXTRACTED edges:
      CONTAINS,
      INHERITS  (same-file),
      CALLS     (same-file bare names + self.X / cls.X to same-class methods
                 + bare calls to imported names like `ReviewOrchestrator()`),
      DECORATES (same-file decorators only),
      IMPORTS   (first-party imports — relative or absolute — resolved to a
                 module file on disk)
  - AmbiguousRef: imports of first-party modules whose file we couldn't find,
                  cross-file inheritance/decorators, attribute / unresolved calls

Dropped entirely (not emitted as edges OR ambiguous refs):
  - Calls to common Python builtins (`len`, `str`, `print`, ...).
  - Imports of third-party packages whose top-level name isn't in this repo.
  - Decorators that don't resolve locally (framework-y `@router.post(...)`).
  - Attribute calls whose method name is a known builtin/stdlib method
    (`.format`, `.append`, `.get`, ...) or a dunder (`__init__`, `__call__`).
    These add no first-party graph signal and would only waste Pass 2 tokens.

Anything that requires cross-file knowledge beyond simple import binding is
left for Pass 2 (C6, the surgical agent) — this pass deliberately does NOT
guess at attribute calls or dynamic dispatch.
"""

from __future__ import annotations

import builtins
from pathlib import Path

from tree_sitter_language_pack import get_parser

from ..models import AmbiguousRef, Edge, Node

_parser = None


def _collect_builtin_names() -> frozenset[str]:
    """Every public name in `builtins` — functions, types, exceptions."""
    return frozenset(n for n in dir(builtins) if not n.startswith("_"))


def _collect_builtin_methods() -> frozenset[str]:
    """Every method name on any builtin type.

    Covers `.format`, `.append`, `.get`, `.keys`, etc. — anything an attribute
    call could resolve to on a builtin receiver. We can't know the receiver's
    type from tree-sitter alone, so this is a best-effort denylist that
    eliminates the bulk of noise without hand-curating.
    """
    methods: set[str] = set()
    for name in dir(builtins):
        obj = getattr(builtins, name, None)
        if isinstance(obj, type):
            for member in dir(obj):
                methods.add(member)
    return frozenset(methods)


_PYTHON_BUILTINS: frozenset[str] = _collect_builtin_names()
_PYTHON_BUILTIN_METHODS: frozenset[str] = _collect_builtin_methods()


def _is_builtin_method(name: str) -> bool:
    return name in _PYTHON_BUILTIN_METHODS or (
        name.startswith("__") and name.endswith("__")
    )


def _get_parser():
    global _parser
    if _parser is None:
        _parser = get_parser("python")
    return _parser


def parse_python(
    rel_path: str, source: bytes, repo_root: Path
) -> tuple[list[Node], list[Edge], list[AmbiguousRef]]:
    tree = _get_parser().parse(source)
    walker = _PythonWalker(rel_path, source, repo_root)
    walker.visit_module(tree.root_node)
    return walker.nodes, walker.edges, walker.ambiguous


class _PythonWalker:
    def __init__(self, rel_path: str, source: bytes, repo_root: Path) -> None:
        self.file = rel_path
        self.src = source
        self.repo_root = repo_root
        self.module_id = rel_path
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.ambiguous: list[AmbiguousRef] = []
        # Top-level name → node id, for same-file CALLS / INHERITS resolution.
        self.local_defs: dict[str, str] = {}
        # Imported name → constructed node id `<file>::<name>` (or `<file>` for
        # `from . import module`). Used to resolve bare-name calls that refer
        # to symbols pulled in via `from X import Y`.
        self.imported_names: dict[str, str] = {}

    def _text(self, n) -> str:
        return self.src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")

    def visit_module(self, root) -> None:
        self._collect_top_defs(root)
        self.nodes.append(
            Node(
                id=self.module_id,
                type="module",
                name=Path(self.file).stem,
                file=self.file,
                line_start=root.start_point[0] + 1,
                line_end=root.end_point[0] + 1,
                language="python",
                docstring=self._docstring_of_block(root),
            )
        )
        for child in root.named_children:
            self._visit_top(child)

    def _collect_top_defs(self, root) -> None:
        for child in root.named_children:
            target = child
            if target.type == "decorated_definition":
                target = target.child_by_field_name("definition") or (
                    target.named_children[-1] if target.named_children else target
                )
            if target.type in ("function_definition", "class_definition"):
                name_node = target.child_by_field_name("name")
                if name_node:
                    name = self._text(name_node)
                    self.local_defs[name] = f"{self.module_id}::{name}"

    def _visit_top(self, n) -> None:
        t = n.type
        if t == "decorated_definition":
            decorators = [c for c in n.named_children if c.type == "decorator"]
            inner = n.child_by_field_name("definition") or (
                n.named_children[-1] if n.named_children else None
            )
            if inner is not None:
                self._visit_def(inner, decorators, parent=self.module_id, class_name=None)
        elif t in ("function_definition", "class_definition"):
            self._visit_def(n, [], parent=self.module_id, class_name=None)
        elif t == "import_from_statement":
            self._handle_from_import(n)
        elif t == "import_statement":
            self._handle_plain_import(n)

    def _visit_def(self, n, decorators, parent: str, class_name: str | None) -> None:
        if n.type == "class_definition":
            self._visit_class(n, decorators)
        elif n.type == "function_definition":
            self._visit_function(
                n,
                decorators,
                parent=parent,
                is_method=class_name is not None,
                class_name=class_name,
                class_local={},
            )

    def _visit_class(self, n, decorators) -> None:
        name_node = n.child_by_field_name("name")
        if name_node is None:
            return
        name = self._text(name_node)
        cls_id = f"{self.module_id}::{name}"
        self.nodes.append(
            Node(
                id=cls_id,
                type="class",
                name=name,
                file=self.file,
                line_start=n.start_point[0] + 1,
                line_end=n.end_point[0] + 1,
                language="python",
                docstring=self._docstring_of_block(n),
            )
        )
        self.edges.append(Edge(self.module_id, cls_id, "CONTAINS"))

        supers = n.child_by_field_name("superclasses")
        if supers is not None:
            for c in supers.named_children:
                raw = self._text(c)
                if c.type == "identifier" and raw in self.local_defs:
                    self.edges.append(Edge(cls_id, self.local_defs[raw], "INHERITS"))
                else:
                    self.ambiguous.append(
                        AmbiguousRef(
                            source=cls_id,
                            raw=raw,
                            kind="inherits",
                            file=self.file,
                            line=c.start_point[0] + 1,
                        )
                    )

        self._emit_decorators(decorators, target_id=cls_id)

        body = n.child_by_field_name("body")
        if body is None:
            return

        # Pre-collect method names for same-class self.X / cls.X resolution.
        class_local: dict[str, str] = {}
        for c in body.named_children:
            inner = c
            if c.type == "decorated_definition":
                inner = c.child_by_field_name("definition") or (
                    c.named_children[-1] if c.named_children else c
                )
            if inner.type == "function_definition":
                mn = inner.child_by_field_name("name")
                if mn is not None:
                    mname = self._text(mn)
                    class_local[mname] = f"{cls_id}.{mname}"

        for c in body.named_children:
            if c.type == "decorated_definition":
                inner_decs = [x for x in c.named_children if x.type == "decorator"]
                inner = c.child_by_field_name("definition") or (
                    c.named_children[-1] if c.named_children else None
                )
                if inner is not None and inner.type == "function_definition":
                    self._visit_function(
                        inner, inner_decs, parent=cls_id, is_method=True,
                        class_name=name, class_local=class_local,
                    )
            elif c.type == "function_definition":
                self._visit_function(
                    c, [], parent=cls_id, is_method=True,
                    class_name=name, class_local=class_local,
                )

    def _visit_function(
        self,
        n,
        decorators,
        parent: str,
        is_method: bool,
        class_name: str | None,
        class_local: dict[str, str],
    ) -> None:
        name_node = n.child_by_field_name("name")
        if name_node is None:
            return
        name = self._text(name_node)
        fid = (
            f"{self.module_id}::{class_name}.{name}"
            if is_method and class_name is not None
            else f"{self.module_id}::{name}"
        )
        params_node = n.child_by_field_name("parameters")
        params = self._params(params_node) if params_node is not None else []
        self.nodes.append(
            Node(
                id=fid,
                type="method" if is_method else "function",
                name=name,
                file=self.file,
                line_start=n.start_point[0] + 1,
                line_end=n.end_point[0] + 1,
                language="python",
                params=params,
                docstring=self._docstring_of_block(n),
            )
        )
        self.edges.append(Edge(parent, fid, "CONTAINS"))

        self._emit_decorators(decorators, target_id=fid)

        body = n.child_by_field_name("body")
        if body is not None:
            self._collect_calls(body, source_id=fid, class_local=class_local)

    def _handle_from_import(self, n) -> None:
        """`from <module> import <names>` — emit IMPORTS edge + record bindings.

        - First-party module resolved to a file: emit IMPORTS, bind each
          imported name to `<target_file>::<name>` so bare-name calls later in
          this file can resolve to a concrete node.
        - First-party module that should exist but file missing: AmbiguousRef.
        - Third-party (top-level package not present in repo): drop entirely.
        """
        raw = self._text(n).strip()
        line = n.start_point[0] + 1

        module_n = n.child_by_field_name("module_name")
        if module_n is None:
            self.ambiguous.append(
                AmbiguousRef(self.module_id, raw, "import", self.file, line)
            )
            return

        if module_n.type == "dotted_name":
            parts = [
                self._text(p) for p in module_n.named_children if p.type == "identifier"
            ]
            if not parts:
                self.ambiguous.append(
                    AmbiguousRef(self.module_id, raw, "import", self.file, line)
                )
                return
            target = self._resolve_module_file(Path(*parts))
            if target is not None:
                self._emit_import_with_bindings(target, n, module_n)
                return
            if not self._is_first_party(parts[0]):
                # Third-party package — skip, Pass 2 has nothing useful to do.
                return
            self.ambiguous.append(
                AmbiguousRef(self.module_id, raw, "import", self.file, line)
            )
            return

        if module_n.type != "relative_import":
            self.ambiguous.append(
                AmbiguousRef(self.module_id, raw, "import", self.file, line)
            )
            return

        # `relative_import` = leading dots (import_prefix) + optional dotted_name.
        levels = 0
        sub_parts: list[str] = []
        for c in module_n.children:
            if c.type == "import_prefix":
                levels = c.end_byte - c.start_byte  # number of dots
            elif c.type == "dotted_name":
                sub_parts = [
                    self._text(p) for p in c.named_children if p.type == "identifier"
                ]

        if levels == 0:
            self.ambiguous.append(
                AmbiguousRef(self.module_id, raw, "import", self.file, line)
            )
            return

        # 1 dot = same package (no up). N dots = go up (N-1).
        base = Path(self.file).parent
        for _ in range(levels - 1):
            if str(base) in (".", ""):
                base = Path("")
                break
            base = base.parent
        for part in sub_parts:
            base = base / part

        if sub_parts:
            target = self._resolve_module_file(base)
            if target is not None:
                self._emit_import_with_bindings(target, n, module_n)
                return
        else:
            # `from . import foo, bar` — each imported name IS its own module.
            emitted = False
            for name_n, alias_n in self._iter_import_names(n, exclude=module_n):
                original = self._text(name_n)
                target = self._resolve_module_file(base / original)
                if target is not None:
                    self.edges.append(Edge(self.module_id, target, "IMPORTS"))
                    bind = self._text(alias_n) if alias_n is not None else original
                    # Calling the bound name calls the module itself — point at the module node.
                    self.imported_names[bind] = target
                    emitted = True
            if emitted:
                return

        self.ambiguous.append(
            AmbiguousRef(self.module_id, raw, "import", self.file, line)
        )

    def _handle_plain_import(self, n) -> None:
        """`import a.b.c` / `import x as y` / `import a, b`.

        Emits IMPORTS edges for first-party modules. Drops third-party.
        Plain `import x` doesn't create useful bare-name call bindings (calls
        are typically `x.func()` — attribute access, ambiguous), so we don't
        populate `imported_names` from these.
        """
        raw = self._text(n).strip()
        line = n.start_point[0] + 1
        handled = False

        for c in n.named_children:
            module_node = self._unwrap_aliased(c)[0]
            if module_node is None or module_node.type != "dotted_name":
                continue
            parts = [
                self._text(p) for p in module_node.named_children if p.type == "identifier"
            ]
            if not parts:
                continue
            target = self._resolve_module_file(Path(*parts))
            if target is not None:
                self.edges.append(Edge(self.module_id, target, "IMPORTS"))
                handled = True
            elif not self._is_first_party(parts[0]):
                # Third-party — drop.
                handled = True

        if not handled:
            self.ambiguous.append(
                AmbiguousRef(self.module_id, raw, "import", self.file, line)
            )

    def _emit_import_with_bindings(self, target_file: str, import_n, module_n) -> None:
        """Emit IMPORTS edge to `target_file` and bind each imported name."""
        self.edges.append(Edge(self.module_id, target_file, "IMPORTS"))
        for name_n, alias_n in self._iter_import_names(import_n, exclude=module_n):
            original = self._text(name_n)
            bind = self._text(alias_n) if alias_n is not None else original
            self.imported_names[bind] = f"{target_file}::{original}"

    def _resolve_module_file(self, base: Path) -> str | None:
        """Return rel_path of a real .py file matching `base`, or None."""
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            full = self.repo_root / candidate
            try:
                if full.is_file():
                    return candidate.as_posix()
            except OSError:
                continue
        return None

    def _is_first_party(self, top_level: str) -> bool:
        """True if `top_level` is a real top-level package/module in this repo."""
        for cand in (
            Path(top_level + ".py"),
            Path(top_level) / "__init__.py",
            Path(top_level),  # bare directory (namespace package or just a dir)
        ):
            full = self.repo_root / cand
            try:
                if full.exists():
                    return True
            except OSError:
                continue
        return False

    def _iter_import_names(self, n, exclude):
        """Yield (name_identifier, alias_identifier_or_None) pairs from an
        import_from_statement, skipping the module_name child.
        """
        for c in n.named_children:
            if c is exclude:
                continue
            if c.type == "dotted_name":
                first = c.named_children[0] if c.named_children else None
                if first is not None and first.type == "identifier":
                    yield (first, None)
            elif c.type == "aliased_import":
                inner = c.child_by_field_name("name") or (
                    c.named_children[0] if c.named_children else None
                )
                alias = c.child_by_field_name("alias")
                if inner is None:
                    continue
                if inner.type == "dotted_name" and inner.named_children:
                    inner = inner.named_children[0]
                if inner.type == "identifier":
                    yield (inner, alias)

    def _unwrap_aliased(self, c):
        """For an `import_statement` child, return (module_dotted_name, alias_or_None)."""
        if c.type == "dotted_name":
            return (c, None)
        if c.type == "aliased_import":
            name_n = c.child_by_field_name("name") or (
                c.named_children[0] if c.named_children else None
            )
            alias_n = c.child_by_field_name("alias")
            return (name_n, alias_n)
        return (None, None)

    def _emit_decorators(self, decorators, target_id: str) -> None:
        # Only emit DECORATES when we can resolve the decorator locally.
        # Unresolvable decorators (`@router.post(...)`, `@app.middleware`, etc.)
        # are framework bindings — dropped, not handed to Pass 2.
        for d in decorators:
            head = self._decorator_head(d)
            if head is not None and head in self.local_defs:
                self.edges.append(Edge(target_id, self.local_defs[head], "DECORATES"))

    def _decorator_head(self, d) -> str | None:
        """Return the bare identifier head of a decorator, if simple, else None."""
        if not d.named_children:
            return None
        expr = d.named_children[0]
        if expr.type == "identifier":
            return self._text(expr)
        if expr.type == "call":
            callee = expr.child_by_field_name("function")
            if callee is not None and callee.type == "identifier":
                return self._text(callee)
        return None

    def _collect_calls(self, n, source_id: str, class_local: dict[str, str]) -> None:
        for child in n.named_children:
            # Don't descend into nested defs — their calls belong to that owner.
            if child.type in (
                "function_definition",
                "class_definition",
                "decorated_definition",
                "lambda",
            ):
                continue
            if child.type == "call":
                self._handle_call(child, source_id, class_local)
            self._collect_calls(child, source_id, class_local)

    def _handle_call(self, n, source_id: str, class_local: dict[str, str]) -> None:
        fn = n.child_by_field_name("function")
        if fn is None:
            return
        if fn.type == "identifier":
            name = self._text(fn)
            target = self.local_defs.get(name) or self.imported_names.get(name)
            if target is not None:
                self.edges.append(Edge(source_id, target, "CALLS"))
            elif name in _PYTHON_BUILTINS:
                # Drop noise — builtins are not graph edges.
                return
            else:
                self.ambiguous.append(
                    AmbiguousRef(
                        source=source_id,
                        raw=name,
                        kind="call",
                        file=self.file,
                        line=fn.start_point[0] + 1,
                    )
                )
            return
        if fn.type == "attribute":
            obj_n = fn.child_by_field_name("object")
            attr_n = fn.child_by_field_name("attribute")
            if obj_n is not None and attr_n is not None:
                obj_text = self._text(obj_n)
                attr_text = self._text(attr_n)
                if obj_text in ("self", "cls") and attr_text in class_local:
                    self.edges.append(Edge(source_id, class_local[attr_text], "CALLS"))
                    return
                # Builtin/dunder method on an unknown receiver — never a project
                # node. Drop instead of paying Pass 2 to discover that.
                if _is_builtin_method(attr_text):
                    return
        self.ambiguous.append(
            AmbiguousRef(
                source=source_id,
                raw=self._text(fn),
                kind="call",
                file=self.file,
                line=fn.start_point[0] + 1,
            )
        )

    def _params(self, params_node) -> list[str]:
        out: list[str] = []
        for p in params_node.named_children:
            t = p.type
            if t == "identifier":
                out.append(self._text(p))
            elif t in ("default_parameter", "typed_parameter", "typed_default_parameter"):
                name_n = p.child_by_field_name("name")
                out.append(self._text(name_n) if name_n is not None else self._text(p))
            elif t in ("list_splat_pattern", "dictionary_splat_pattern"):
                out.append(self._text(p))
            elif t in ("positional_separator", "keyword_separator"):
                continue
            else:
                out.append(self._text(p))
        return out

    def _docstring_of_block(self, n) -> str | None:
        body = n if n.type == "module" else n.child_by_field_name("body")
        if body is None or not body.named_children:
            return None
        first = body.named_children[0]
        if first.type != "expression_statement" or not first.named_children:
            return None
        inner = first.named_children[0]
        if inner.type != "string":
            return None
        text = self._text(inner).strip()
        for q in ('"""', "'''", '"', "'"):
            if text.startswith(q) and text.endswith(q) and len(text) >= 2 * len(q):
                return text[len(q) : -len(q)].strip()
        return text
