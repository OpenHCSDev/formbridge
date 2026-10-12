"""formbridge is toolkit-neutral: importing any of its modules loads no GUI toolkit."""

from __future__ import annotations

import pkgutil
import subprocess
import sys
from pathlib import Path

import formbridge

TOOLKIT_PACKAGES = ("PyQt6", "PyQt5", "PySide6", "PySide2", "qtpy", "pyqt_reactive", "tkinter")


def _formbridge_modules() -> tuple[str, ...]:
    return tuple(
        sorted(
            module.name
            for module in pkgutil.walk_packages(formbridge.__path__, prefix="formbridge.")
        )
    )


def test_every_formbridge_module_imports_without_a_toolkit() -> None:
    modules = _formbridge_modules()
    assert len(modules) > 50
    script = f"""
import builtins
import importlib
import sys

toolkits = {TOOLKIT_PACKAGES!r}
original_import = builtins.__import__

def reject_toolkit(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name.split(".")[0] in toolkits:
        raise AssertionError(f"formbridge imported {{name}}")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = reject_toolkit
for module in {modules!r}:
    importlib.import_module(module)
loaded = sorted(name for name in sys.modules if name.split(".")[0] in toolkits)
assert not loaded, loaded
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr


def test_no_formbridge_source_names_a_toolkit() -> None:
    root = Path(formbridge.__file__).resolve().parent
    offenders = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith(("import ", "from "))
        and line.split()[1].split(".")[0] in TOOLKIT_PACKAGES
    )
    assert offenders == []
