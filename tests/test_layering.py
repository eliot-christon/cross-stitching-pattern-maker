"""Enforce the layering invariant: the core never imports the HTTP layer.

The core packages (`colour`, `threads`, `pattern`, `export` under `cross_stitch`) are pure
Python. None of their modules may import `cross_stitch.api` (absolutely or relatively),
a web framework, or an HTTP client or server library. Only `api/` speaks HTTP.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import cross_stitch

CORE_PACKAGES = ("colour", "threads", "pattern", "export")

# Module prefixes the core must never import. A prefix matches the module itself and
# anything below it (`fastapi` matches `fastapi.responses`).
FORBIDDEN_PREFIXES = (
    "cross_stitch.api",
    "fastapi",
    "starlette",
    "uvicorn",
    "httpx",
    "requests",
    "urllib3",
    "aiohttp",
    "http",
    "urllib.request",
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    module: str


def _is_forbidden(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def _imported_modules(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    """Absolute names an import statement may bind, relative imports resolved."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        parts = package.split(".")
        base = ".".join(parts[: len(parts) - node.level + 1])
        source = f"{base}.{node.module}" if node.module else base
    else:
        source = node.module or ""
    # `from pkg import name` may import the submodule `pkg.name`.
    return [source, *(f"{source}.{alias.name}" for alias in node.names)]


def find_violations(package_root: Path) -> list[Violation]:
    """Forbidden imports in the core packages under `package_root` (a `cross_stitch` dir)."""
    violations = []
    for core in CORE_PACKAGES:
        for path in sorted((package_root / core).rglob("*.py")):
            relative = path.relative_to(package_root.parent).with_suffix("")
            parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
            module = ".".join(parts)
            package = module if relative.name == "__init__" else module.rpartition(".")[0]
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Import | ast.ImportFrom):
                    continue
                hits = [m for m in _imported_modules(node, package) if _is_forbidden(m)]
                if hits:
                    violations.append(Violation(path, node.lineno, hits[0]))
    return violations


def _plant(tmp_path: Path, relative: str, source: str) -> Path:
    root = tmp_path / "cross_stitch"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return root


def test_real_tree_has_no_violations() -> None:
    package_root = Path(cross_stitch.__file__).parent
    assert not find_violations(package_root)


def test_core_importing_fastapi_is_one_violation_naming_file_and_import(
    tmp_path: Path,
) -> None:
    root = _plant(tmp_path, "pattern/convert.py", "import fastapi\n")
    assert find_violations(root) == [Violation(root / "pattern/convert.py", 1, "fastapi")]


def test_core_importing_api_absolutely_is_a_violation(tmp_path: Path) -> None:
    root = _plant(tmp_path, "colour/__init__.py", "from cross_stitch.api import app\n")
    assert [v.module for v in find_violations(root)] == ["cross_stitch.api"]


def test_core_importing_api_relatively_is_a_violation(tmp_path: Path) -> None:
    root = _plant(tmp_path, "threads/lookup.py", "from ..api import x\n")
    assert [v.module for v in find_violations(root)] == ["cross_stitch.api"]


def test_core_importing_api_package_by_name_is_a_violation(tmp_path: Path) -> None:
    root = _plant(tmp_path, "export/pdf.py", "from .. import api\n")
    assert [v.module for v in find_violations(root)] == ["cross_stitch.api"]


def test_core_importing_starlette_is_a_violation(tmp_path: Path) -> None:
    root = _plant(tmp_path, "pattern/model.py", "from starlette.requests import Request\n")
    assert [v.module for v in find_violations(root)] == ["starlette.requests"]


def test_api_importing_fastapi_is_allowed(tmp_path: Path) -> None:
    root = _plant(tmp_path, "api/app.py", "import fastapi\n")
    assert not find_violations(root)


def test_core_importing_numpy_is_allowed(tmp_path: Path) -> None:
    root = _plant(tmp_path, "colour/__init__.py", "import numpy as np\nfrom . import lab\n")
    assert not find_violations(root)
