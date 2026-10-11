"""Static gates for nominal product contracts."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "formbridge"


def _protocol_violations(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_aliases: set[str] = set()
    typing_modules: set[str] = set()
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            "typing",
            "typing_extensions",
        }:
            for alias in node.names:
                if alias.name == "Protocol":
                    imported_aliases.add(alias.asname or alias.name)
                    violations.append(f"line {node.lineno}: imports Protocol")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"typing", "typing_extensions"}:
                    typing_modules.add(alias.asname or alias.name)

    for node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in imported_aliases:
                violations.append(f"line {node.lineno}: {node.name} inherits Protocol")
            if (
                isinstance(base, ast.Attribute)
                and base.attr == "Protocol"
                and isinstance(base.value, ast.Name)
                and base.value.id in typing_modules
            ):
                violations.append(f"line {node.lineno}: {node.name} inherits Protocol")
    return tuple(violations)


def test_product_code_uses_nominal_abcs_instead_of_typing_protocols() -> None:
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): declarations
        for path in PACKAGE_ROOT.rglob("*.py")
        if (declarations := _protocol_violations(path))
    }

    assert violations == {}
