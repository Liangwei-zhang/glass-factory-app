from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read_non_empty_lines(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _repo_files(root: Path) -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_legacy_backend_allowlist_matches_repo() -> None:
    allowlist_path = ROOT / "ops" / "policy" / "legacy_backend_allowlist.txt"
    allowlist = _read_non_empty_lines(allowlist_path)
    backend_files = _repo_files(ROOT / "backend")

    unexpected = sorted(backend_files - allowlist)
    stale = sorted(allowlist - backend_files)

    assert not unexpected, (
        "backend/ is frozen for new feature delivery. Unexpected legacy files found: "
        f"{unexpected}. If this is a justified migration shim, update the allowlist "
        "in the same change and document the reason."
    )
    assert not stale, f"Remove stale paths from the legacy backend allowlist: {stale}"


def test_development_guide_points_to_guardrail_docs() -> None:
    guide = (ROOT / "docs" / "DEVELOPMENT_GUIDE.md").read_text(encoding="utf-8")

    assert "docs/ARCHITECTURE_GUARDRAILS.md" in guide
    assert "docs/CACHE_STRATEGY_MATRIX.md" in guide
    assert "make test-guardrails" in guide


def test_guardrail_docs_capture_event_and_cache_requirements() -> None:
    architecture = (ROOT / "docs" / "ARCHITECTURE_GUARDRAILS.md").read_text(
        encoding="utf-8"
    )
    cache_matrix = (ROOT / "docs" / "CACHE_STRATEGY_MATRIX.md").read_text(
        encoding="utf-8"
    )

    assert "topics.py" in architecture
    assert "Outbox" in architecture
    assert "subscriber" in architecture
    assert "backend/" in architecture

    assert "cache:order:{order_id}" in cache_matrix
    assert "cache:customer:{customer_id}" in cache_matrix
    assert "cache:inventory:{product_id}" in cache_matrix
    assert "Every new read path must add a row before merge." in cache_matrix