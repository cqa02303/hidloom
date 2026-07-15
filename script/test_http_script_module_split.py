#!/usr/bin/env python3
"""Guard the HTTP script editor module split."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_API = ROOT / "daemon" / "http" / "scripts_api.py"
SCRIPT_RUNNER = ROOT / "daemon" / "http" / "script_runner.py"
SCRIPT_STORE = ROOT / "daemon" / "http" / "script_store.py"


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _imported_from_names(tree: ast.Module, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                names.add(alias.name)
    return names


def _function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _attribute_names(tree: ast.Module) -> set[str]:
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }


def _call_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_scripts_api_does_not_own_process_or_tempfile_details() -> None:
    tree = _module(SCRIPTS_API)
    imports = _imported_names(tree)
    calls = _call_names(tree)
    attrs = _attribute_names(tree)
    runner_imports = _imported_from_names(tree, "script_runner")

    assert "asyncio" not in imports, "scripts_api.py must not own subprocess execution"
    assert "tempfile" not in imports, "scripts_api.py must not own check-run temp file lifecycle"
    assert "os" not in imports, "scripts_api.py must not own chmod/PATH environment setup"
    assert "create_subprocess_exec" not in attrs
    assert "TemporaryDirectory" not in calls
    assert "chmod" not in attrs
    assert "run_script_content" in calls
    assert "run_script_path" in calls
    # httpd.py still imports these names from scripts_api.py for compatibility;
    # the implementation remains in script_runner.py and is only re-exported here.
    assert {"script_check_env", "trim_script_output"}.issubset(runner_imports)


def test_script_runner_owns_execution_details() -> None:
    tree = _module(SCRIPT_RUNNER)
    imports = _imported_names(tree)
    funcs = _function_names(tree)
    calls = _call_names(tree)
    attrs = _attribute_names(tree)

    assert "asyncio" in imports
    assert "tempfile" in imports
    assert "os" in imports
    assert {"script_check_env", "trim_script_output", "run_script_path", "run_script_content"}.issubset(funcs)
    assert "create_subprocess_exec" in attrs
    assert "TemporaryDirectory" in calls
    assert "chmod" in attrs


def test_script_store_owns_path_configuration() -> None:
    tree = _module(SCRIPT_STORE)
    funcs = _function_names(tree)
    assert "configure_paths" in funcs

    scripts_tree = _module(SCRIPTS_API)
    calls = _call_names(scripts_tree)
    assert "configure_paths" in calls


if __name__ == "__main__":
    test_scripts_api_does_not_own_process_or_tempfile_details()
    test_script_runner_owns_execution_details()
    test_script_store_owns_path_configuration()
    print("ok")
