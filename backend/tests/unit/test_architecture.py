"""Import-boundary test (plan §3.1, §3.2).

``domain/`` and ``ranking/`` may not import from ``sources/``, ``ai/``,
``persistence/``, ``api/``, or any third-party framework. Walked via AST so
the check is enforced on source, not on whatever happens to be installed.
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "tripfinder"
PROTECTED_PACKAGES = ("domain", "ranking")

FORBIDDEN_INTERNAL_PACKAGES = ("sources", "ai", "persistence", "api")
FORBIDDEN_FRAMEWORKS = {
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "httpx",
    "openai",
    "requests",
}


def _imported_top_level_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    top_level = module.split(".")[0]
    if top_level == "tripfinder":
        parts = module.split(".")
        return len(parts) > 1 and parts[1] in FORBIDDEN_INTERNAL_PACKAGES
    return top_level in FORBIDDEN_FRAMEWORKS


def _violations_in(package_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        modules = _imported_top_level_modules(path.read_text())
        for module in sorted(modules):
            if _is_forbidden(module):
                violations.append(f"{path.relative_to(SRC_ROOT.parent.parent)}: imports {module!r}")
    return violations


def test_predicate_flags_known_bad_imports() -> None:
    assert _is_forbidden("fastapi")
    assert _is_forbidden("sqlalchemy.orm")
    assert _is_forbidden("tripfinder.sources.arctic_shift")
    assert _is_forbidden("tripfinder.persistence.repositories")
    assert _is_forbidden("tripfinder.api.routers")


def test_predicate_allows_known_good_imports() -> None:
    assert not _is_forbidden("pydantic")
    assert not _is_forbidden("typing")
    assert not _is_forbidden("tripfinder.domain.models")
    assert not _is_forbidden("tripfinder.ranking.aggregation")


def test_domain_and_ranking_do_not_import_forbidden_modules() -> None:
    all_violations: list[str] = []
    for package_name in PROTECTED_PACKAGES:
        package_dir = SRC_ROOT / package_name
        if package_dir.is_dir():
            all_violations.extend(_violations_in(package_dir))

    assert all_violations == []


def test_domain_package_exists_and_was_actually_checked() -> None:
    domain_dir = SRC_ROOT / "domain"

    assert domain_dir.is_dir()
    assert list(domain_dir.rglob("*.py"))
