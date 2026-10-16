"""Form operations consume admitted values, not duplicate classifiers or type names."""

import ast
from pathlib import Path

import pytest


SOURCE = Path(__file__).parents[1] / "src" / "formbridge"
DELETED_CLASSIFIERS = {"is_container", "is_config_type", "is_dataclass"}
# MIME metadata is a protocol fact, not a Python class-name mirror.
DELETED_TYPE_FIELDS = (
    "source_type", "object_state_path_type", "raw_value_type",
    "resolved_value_type", "object_type", "help_target_type",
)


def test_operations_do_not_reclassify_values():
    violations = []
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
            else:
                continue
            if name in DELETED_CLASSIFIERS:
                violations.append(f"{path.relative_to(SOURCE)}:{node.lineno}: {name}")
    assert not violations, "\n" + "\n".join(sorted(violations))


@pytest.mark.parametrize("name", DELETED_TYPE_FIELDS)
def test_dto_does_not_copy_python_type_names(name):
    path = SOURCE / "bridge" / "dto.py"
    violations = [
        f"{path.name}:{node.lineno}: {name}"
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path)))
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == name
    ]
    assert not violations, "\n" + "\n".join(violations)
