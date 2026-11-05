"""What each distribution may import (scene-verify-0001).

- The engine imports nothing from RoboEval's ``app`` package: the code it needed was copied in.
- The contract imports only the standard library, so a consumer pins it without the engine's
  dependencies.
- No engine module imports Isaac Sim (``isaacsim``, ``omni``, ``carb``) at module level, so
  importing the engine outside Isaac Sim's Python boots nothing; the runner imports them
  inside its functions.

Each check reads the source with ``ast``, so it sees function-local imports too.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE_SRC = ROOT / "packages" / "engine" / "src" / "scene_verify"
CONTRACT_SRC = ROOT / "packages" / "contract" / "src" / "scene_verify_contract"
ISAAC_TOP_LEVEL = {"isaacsim", "omni", "carb"}


def _python_files(package_dir: Path) -> list[Path]:
    files = sorted(package_dir.rglob("*.py"))
    assert files, f"no Python files under {package_dir}"
    return files


def _imports(path: Path, *, module_level_only: bool = False) -> list[tuple[int, str]]:
    """``(line, imported module)`` for each import in ``path``; relative imports are skipped."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = tree.body if module_level_only else list(ast.walk(tree))
    found: list[tuple[int, str]] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def _top(module: str) -> str:
    return module.split(".", 1)[0]


@pytest.mark.parametrize("path", _python_files(ENGINE_SRC), ids=lambda p: p.name)
def test_engine_imports_nothing_from_roboeval_app(path: Path):
    offending = [(line, mod) for line, mod in _imports(path) if _top(mod) == "app"]
    assert offending == [], f"{path.relative_to(ROOT)} imports RoboEval's app: {offending}"


@pytest.mark.parametrize("path", _python_files(CONTRACT_SRC), ids=lambda p: p.name)
def test_contract_imports_only_the_standard_library(path: Path):
    allowed = set(sys.stdlib_module_names) | {"__future__", "scene_verify_contract"}
    offending = [(line, mod) for line, mod in _imports(path) if _top(mod) not in allowed]
    assert offending == [], f"{path.relative_to(ROOT)} imports outside the stdlib: {offending}"


@pytest.mark.parametrize("path", _python_files(ENGINE_SRC), ids=lambda p: p.name)
def test_engine_imports_isaac_sim_only_inside_functions(path: Path):
    offending = [
        (line, mod)
        for line, mod in _imports(path, module_level_only=True)
        if _top(mod) in ISAAC_TOP_LEVEL
    ]
    assert offending == [], f"{path.relative_to(ROOT)} imports Isaac Sim at module level"


def test_the_scan_finds_a_function_local_app_import(tmp_path: Path):
    # Guard on the guard: an import buried in a function is still found.
    probe = tmp_path / "probe.py"
    probe.write_text("def f():\n    from app.scene import object_physics\n", encoding="utf-8")
    assert _imports(probe) == [(2, "app.scene")]
    assert _imports(probe, module_level_only=True) == []
