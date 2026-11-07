"""Verification tests for directory structure, scaffolding, and ADR completeness."""

from pathlib import Path


def test_required_source_directories_exist() -> None:
    """Ensure all modular monolith subpackages exist with __init__.py files."""
    required_packages = [
        "domain",
        "application",
        "market_data",
        "indicators",
        "regime",
        "strategies",
        "risk",
        "portfolio",
        "execution",
        "exchanges",
        "backtesting",
        "persistence",
        "monitoring",
        "reporting",
    ]
    base_src = Path("src/trading_bot")
    assert base_src.exists()
    assert (base_src / "__init__.py").exists()
    assert (base_src / "main.py").exists()

    for pkg in required_packages:
        pkg_dir = base_src / pkg
        assert pkg_dir.exists(), f"Missing subpackage directory: {pkg_dir}"
        assert (pkg_dir / "__init__.py").exists(), f"Missing __init__.py in: {pkg_dir}"


def test_required_test_directories_exist() -> None:
    """Ensure all test suite categories are properly partitioned."""
    required_test_dirs = [
        "tests/unit",
        "tests/unit/domain",
        "tests/unit/config",
        "tests/integration",
        "tests/contract",
        "tests/scenarios",
    ]
    for test_dir_str in required_test_dirs:
        test_dir = Path(test_dir_str)
        assert test_dir.exists(), f"Missing test directory: {test_dir}"
        assert (test_dir / "__init__.py").exists(), f"Missing __init__.py in: {test_dir}"


def test_documentation_and_adrs_complete() -> None:
    """Ensure canonical documentation and all 7 ADRs are present and properly structured."""
    docs_dir = Path("docs")
    assert (docs_dir / "ARCHITECTURE.md").exists()
    assert (docs_dir / "STRATEGIES.md").exists()
    assert (docs_dir / "RISK_POLICY.md").exists()
    assert (docs_dir / "EXECUTION.md").exists()
    assert (docs_dir / "BACKTESTING.md").exists()
    assert (docs_dir / "RUNBOOK.md").exists()

    adr_dir = docs_dir / "adr"
    assert adr_dir.exists()

    expected_adrs = [
        "ADR-001-modular-monolith.md",
        "ADR-002-ccxt-adapter.md",
        "ADR-003-postgresql.md",
        "ADR-004-decimal-financial-values.md",
        "ADR-005-shared-strategy-core.md",
        "ADR-006-fail-closed-risk-policy.md",
        "ADR-007-paper-before-live.md",
    ]

    required_sections = [
        "## Status",
        "## Date",
        "## Context",
        "## Decision",
        "## Alternatives Considered",
        "## Rationale",
        "## Consequences",
    ]

    for adr_name in expected_adrs:
        adr_file = adr_dir / adr_name
        assert adr_file.exists(), f"Missing ADR: {adr_name}"
        content = adr_file.read_text(encoding="utf-8")
        assert "Accepted" in content
        for sec in required_sections:
            assert sec in content, f"Missing section '{sec}' in {adr_name}"


def test_scripts_and_deployment_files_exist() -> None:
    """Ensure CLI script stubs and container manifests are present."""
    assert Path("Dockerfile").exists()
    assert Path("docker-compose.yml").exists()
    assert Path("scripts/backtest.py").exists()
    assert Path("scripts/paper_trade.py").exists()
    assert Path("scripts/reconcile.py").exists()
