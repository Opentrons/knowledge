"""Extract public Protocol API symbols via Python AST."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from opentrons_knowledge.models.enums import DerivationMethod, SymbolType
from opentrons_knowledge.models.records import (
    CodeSymbol,
    Relationship,
    SourceFileRecord,
    SymbolParameter,
)
from opentrons_knowledge.normalization.ids import (
    content_hash,
    github_blob_url,
    relationship_id,
    source_file_id,
    symbol_id,
)

PRIVATE_PREFIX = "_"
SKIP_DIR_NAMES = {"__pycache__", "tests", "python_tests"}


@dataclass
class SymbolBundle:
    symbols: list[CodeSymbol] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    source_files: list[SourceFileRecord] = field(default_factory=list)


def ingest_protocol_api(
    materialize_root: Path,
    *,
    repository: str,
    commit: str,
    configured_paths: list[str],
    release: str,
    source_key: str = "protocol_api",
) -> SymbolBundle:
    """Parse configured Protocol API paths into symbols."""
    bundle = SymbolBundle()
    for configured in configured_paths:
        root = materialize_root / configured
        if not root.exists():
            continue
        paths = sorted(p for p in root.rglob("*.py") if not _should_skip(p.relative_to(root).parts))
        for path in paths:
            rel = path.relative_to(materialize_root).as_posix()
            module_path = _module_path_from_file(rel)
            text = path.read_text(encoding="utf-8")
            bundle.source_files.append(
                SourceFileRecord(
                    source_file_id=source_file_id(source_key, rel),
                    source_key=source_key,
                    repository=repository,
                    commit=commit,
                    path=rel,
                    status="included",
                    content_hash=content_hash(text),
                    byte_size=len(text.encode("utf-8")),
                )
            )
            try:
                tree = ast.parse(text, filename=rel)
            except SyntaxError:
                continue
            file_bundle = _extract_from_module(
                tree,
                module_path=module_path,
                source_path=rel,
                repository=repository,
                commit=commit,
                release=release,
            )
            bundle.symbols.extend(file_bundle.symbols)
            bundle.relationships.extend(file_bundle.relationships)
    return bundle


def _should_skip(parts: tuple[str, ...]) -> bool:
    return any(part in SKIP_DIR_NAMES or part.startswith(".") for part in parts)


def _module_path_from_file(source_path: str) -> str:
    # api/src/opentrons/protocol_api/foo.py -> opentrons.protocol_api.foo
    marker = "opentrons/"
    rel = source_path.split(marker, 1)[1] if marker in source_path else source_path
    if rel.endswith(".py"):
        rel = rel[:-3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return "opentrons." + rel.replace("/", ".")


def _extract_from_module(
    tree: ast.Module,
    *,
    module_path: str,
    source_path: str,
    repository: str,
    commit: str,
    release: str,
) -> SymbolBundle:
    bundle = SymbolBundle()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith(PRIVATE_PREFIX):
            class_qname = f"{module_path}.{node.name}"
            class_symbol = _class_symbol(
                node,
                qualified_name=class_qname,
                module_path=module_path,
                source_path=source_path,
                repository=repository,
                commit=commit,
                release=release,
            )
            bundle.symbols.append(class_symbol)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith(PRIVATE_PREFIX) and item.name != "__init__":
                        continue
                    method_qname = f"{class_qname}.{item.name}"
                    method = _function_symbol(
                        item,
                        qualified_name=method_qname,
                        module_path=module_path,
                        source_path=source_path,
                        repository=repository,
                        commit=commit,
                        release=release,
                        symbol_type=SymbolType.METHOD,
                    )
                    bundle.symbols.append(method)
                    bundle.relationships.append(
                        Relationship(
                            relationship_id=relationship_id(
                                "class_contains_method",
                                class_symbol.symbol_id,
                                method.symbol_id,
                            ),
                            source_id=class_symbol.symbol_id,
                            target_id=method.symbol_id,
                            relationship_type="class_contains_method",
                            derivation_method=DerivationMethod.DIRECT,
                            source_reference=source_path,
                        )
                    )
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.target.id.startswith(PRIVATE_PREFIX):
                        continue
                    const_qname = f"{class_qname}.{item.target.id}"
                    bundle.symbols.append(
                        _constant_symbol(
                            item,
                            name=item.target.id,
                            qualified_name=const_qname,
                            module_path=module_path,
                            source_path=source_path,
                            repository=repository,
                            commit=commit,
                            release=release,
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith(PRIVATE_PREFIX):
                continue
            qname = f"{module_path}.{node.name}"
            bundle.symbols.append(
                _function_symbol(
                    node,
                    qualified_name=qname,
                    module_path=module_path,
                    source_path=source_path,
                    repository=repository,
                    commit=commit,
                    release=release,
                    symbol_type=SymbolType.FUNCTION,
                )
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = _assignment_names(node)
            for name in names:
                if name.startswith(PRIVATE_PREFIX) or not name.isupper():
                    continue
                qname = f"{module_path}.{name}"
                bundle.symbols.append(
                    _constant_symbol(
                        node,
                        name=name,
                        qualified_name=qname,
                        module_path=module_path,
                        source_path=source_path,
                        repository=repository,
                        commit=commit,
                        release=release,
                    )
                )
        elif isinstance(node, ast.ClassDef) and _is_enum_class(node):
            # Handled above as class; mark type enum by rewriting if bases include Enum
            pass

    # Retype Enum subclasses
    for symbol in bundle.symbols:
        bases = symbol.metadata.get("bases") or []
        if symbol.symbol_type == SymbolType.CLASS and "Enum" in bases:
            symbol.symbol_type = SymbolType.ENUM
    return bundle


def _class_symbol(
    node: ast.ClassDef,
    *,
    qualified_name: str,
    module_path: str,
    source_path: str,
    repository: str,
    commit: str,
    release: str,
) -> CodeSymbol:
    line_start = getattr(node, "lineno", None)
    line_end = getattr(node, "end_lineno", line_start)
    docstring = ast.get_docstring(node)
    bases = [_expr_to_str(base) for base in node.bases]
    deprecated, dep_msg = _deprecation(node.decorator_list)
    min_ver, max_ver = _version_gates(node.decorator_list)
    signature = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
    payload = f"{signature}\n{docstring or ''}"
    return CodeSymbol(
        symbol_id=symbol_id(qualified_name, release),
        qualified_name=qualified_name,
        symbol_type=SymbolType.ENUM if any("Enum" in b for b in bases) else SymbolType.CLASS,
        module_path=module_path,
        source_path=source_path,
        source_url=github_blob_url(
            repository, commit, source_path, line_start=line_start, line_end=line_end
        ),
        signature=signature,
        docstring=docstring,
        minimum_api_version=min_ver,
        maximum_api_version=max_ver,
        deprecated=deprecated,
        deprecation_message=dep_msg,
        line_start=line_start,
        line_end=line_end,
        content_hash=content_hash(payload),
        metadata={"bases": bases, "decorators": [_expr_to_str(d) for d in node.decorator_list]},
    )


def _function_symbol(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    qualified_name: str,
    module_path: str,
    source_path: str,
    repository: str,
    commit: str,
    release: str,
    symbol_type: SymbolType,
) -> CodeSymbol:
    line_start = getattr(node, "lineno", None)
    line_end = getattr(node, "end_lineno", line_start)
    docstring = ast.get_docstring(node)
    params = _parameters(node.args)
    return_type = _expr_to_str(node.returns) if node.returns else None
    deprecated, dep_msg = _deprecation(node.decorator_list)
    min_ver, max_ver = _version_gates(node.decorator_list)
    async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    param_sig = ", ".join(
        f"{p.name}: {p.annotation}" if p.annotation else p.name for p in params if p.name != "self"
    )
    signature = f"{async_prefix}def {node.name}({param_sig})"
    if return_type:
        signature += f" -> {return_type}"
    payload = f"{signature}\n{docstring or ''}"
    return CodeSymbol(
        symbol_id=symbol_id(qualified_name, release),
        qualified_name=qualified_name,
        symbol_type=symbol_type,
        module_path=module_path,
        source_path=source_path,
        source_url=github_blob_url(
            repository, commit, source_path, line_start=line_start, line_end=line_end
        ),
        signature=signature,
        parameters=params,
        return_type=return_type,
        docstring=docstring,
        minimum_api_version=min_ver,
        maximum_api_version=max_ver,
        deprecated=deprecated,
        deprecation_message=dep_msg,
        line_start=line_start,
        line_end=line_end,
        content_hash=content_hash(payload),
        metadata={"decorators": [_expr_to_str(d) for d in node.decorator_list]},
    )


def _constant_symbol(
    node: ast.AST,
    *,
    name: str,
    qualified_name: str,
    module_path: str,
    source_path: str,
    repository: str,
    commit: str,
    release: str,
) -> CodeSymbol:
    line_start = getattr(node, "lineno", None)
    line_end = getattr(node, "end_lineno", line_start)
    annotation = None
    if isinstance(node, ast.AnnAssign) and node.annotation is not None:
        annotation = _expr_to_str(node.annotation)
    signature = f"{name}: {annotation}" if annotation else name
    return CodeSymbol(
        symbol_id=symbol_id(qualified_name, release),
        qualified_name=qualified_name,
        symbol_type=SymbolType.CONSTANT,
        module_path=module_path,
        source_path=source_path,
        source_url=github_blob_url(
            repository, commit, source_path, line_start=line_start, line_end=line_end
        ),
        signature=signature,
        return_type=annotation,
        line_start=line_start,
        line_end=line_end,
        content_hash=content_hash(signature),
    )


def _parameters(args: ast.arguments) -> list[SymbolParameter]:
    params: list[SymbolParameter] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(positional, defaults, strict=True):
        params.append(
            SymbolParameter(
                name=arg.arg,
                annotation=_expr_to_str(arg.annotation) if arg.annotation else None,
                default=_expr_to_str(default) if default is not None else None,
                kind="positional_only" if arg in args.posonlyargs else "positional_or_keyword",
            )
        )
    if args.vararg:
        params.append(
            SymbolParameter(
                name=args.vararg.arg,
                annotation=_expr_to_str(args.vararg.annotation) if args.vararg.annotation else None,
                kind="var_positional",
            )
        )
    kw_defaults = list(args.kw_defaults)
    for arg, default in zip(args.kwonlyargs, kw_defaults, strict=True):
        params.append(
            SymbolParameter(
                name=arg.arg,
                annotation=_expr_to_str(arg.annotation) if arg.annotation else None,
                default=_expr_to_str(default) if default is not None else None,
                kind="keyword_only",
            )
        )
    if args.kwarg:
        params.append(
            SymbolParameter(
                name=args.kwarg.arg,
                annotation=_expr_to_str(args.kwarg.annotation) if args.kwarg.annotation else None,
                kind="var_keyword",
            )
        )
    return params


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    names: list[str] = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    return names


def _is_enum_class(node: ast.ClassDef) -> bool:
    return any("Enum" in _expr_to_str(base) for base in node.bases)


def _deprecation(decorators: list[ast.expr]) -> tuple[bool, str | None]:
    for decorator in decorators:
        text = _expr_to_str(decorator)
        if "deprecated" in text.lower():
            return True, text
    return False, None


def _version_gates(decorators: list[ast.expr]) -> tuple[str | None, str | None]:
    min_ver = None
    max_ver = None
    for decorator in decorators:
        text = _expr_to_str(decorator)
        lower = text.lower()
        if "requires_version" in lower or "requiresapi" in lower.replace("_", ""):
            # requires_version(2, 15) or similar
            match = re_version_tuple(text)
            if match:
                min_ver = match
        if "maximum" in lower and "version" in lower:
            match = re_version_tuple(text)
            if match:
                max_ver = match
    return min_ver, max_ver


def re_version_tuple(text: str) -> str | None:
    import re

    match = re.search(r"(\d+)\s*,\s*(\d+)", text)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    match = re.search(r"[\"'](\d+\.\d+)[\"']", text)
    if match:
        return match.group(1)
    return None


def _expr_to_str(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__
