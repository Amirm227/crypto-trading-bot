"""Unit tests for configuration schemas, YAML Decimal parsing, and fail-closed safety validation."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_bot.domain.config import (
    AppConfig,
    BreakoutConfig,
    EnvSettings,
    ExecutionSafetyConfig,
    FuturesConfig,
    MarketsConfig,
    MeanReversionConfig,
    RiskLimitsConfig,
    SafetyConfig,
    SymbolConfig,
    SymbolsConfigFile,
    TimeframesConfig,
    TrendFollowingConfig,
    load_app_config,
    load_yaml_with_decimals,
)
from trading_bot.domain.types import TimeFrame


def test_load_default_configs_cleanly() -> None:
    """Ensure baseline YAML configuration files parse cleanly and construct valid AppConfig."""
    cfg = load_app_config(config_dir="configs")
    assert isinstance(cfg, AppConfig)
    assert cfg.base.app_name == "crypto-trading-bot"
    assert cfg.base.environment == "paper"
    assert cfg.base.safety.enable_live_trading is False
    assert cfg.base.safety.allow_withdrawals is False

    # Risk limits exact Decimals
    assert cfg.risk.risk.per_trade_pct == Decimal("0.25")
    assert cfg.risk.risk.max_open_risk_pct == Decimal("0.50")
    assert cfg.risk.risk.daily_loss_limit_pct == Decimal("0.75")
    assert cfg.risk.risk.weekly_loss_limit_pct == Decimal("2.00")
    assert cfg.risk.risk.max_drawdown_pct == Decimal("8.00")
    assert cfg.risk.risk.min_risk_reward == Decimal("2.0")
    assert cfg.risk.risk.max_new_trades_per_day == 3

    # Futures constraints
    assert cfg.risk.futures.leverage == 1
    assert cfg.risk.futures.margin_mode == "isolated"
    assert cfg.risk.futures.allow_cross_margin is False
    assert cfg.risk.futures.enabled_live is False

    # Symbols
    symbols = {s.id: s for s in cfg.symbols.symbols}
    assert "BTC" in symbols and symbols["BTC"].enabled is True
    assert "ETH" in symbols and symbols["ETH"].enabled is True
    assert "SOL" in symbols and symbols["SOL"].enabled is True
    assert cfg.symbols.timeframes.regime == TimeFrame.H4
    assert cfg.symbols.timeframes.entry == TimeFrame.H1

    # Strategies
    assert cfg.trend_following.enabled is True
    assert cfg.trend_following.adx_min == Decimal("25.0")
    assert cfg.mean_reversion.enabled is True
    assert cfg.mean_reversion.adx_max == Decimal("20.0")
    assert cfg.breakout.enabled is True
    assert cfg.breakout.volume_multiplier == Decimal("1.5")


def test_safe_decimal_loader_preserves_exact_representation() -> None:
    """Ensure SafeDecimalLoader produces exact Decimals without IEEE 754 float drift."""
    parsed = load_yaml_with_decimals("configs/risk.yaml")
    risk_sec = parsed["risk"]
    assert isinstance(risk_sec["per_trade_pct"], Decimal)
    assert risk_sec["per_trade_pct"] == Decimal("0.25")
    assert isinstance(risk_sec["daily_loss_limit_pct"], Decimal)
    assert risk_sec["daily_loss_limit_pct"] == Decimal("0.75")


def test_safety_config_strictly_blocks_live_trading_and_withdrawals() -> None:
    """Ensure enable_live_trading=True and allow_withdrawals=True fail closed."""
    # Live trading forbidden
    with pytest.raises(ValidationError) as exc1:
        SafetyConfig(enable_live_trading=True, allow_withdrawals=False, fail_closed_on_error=True)
    assert "Live trading (enable_live_trading=True) is strictly prohibited" in str(exc1.value)

    # Withdrawals permanently forbidden
    with pytest.raises(ValidationError) as exc2:
        SafetyConfig(enable_live_trading=False, allow_withdrawals=True, fail_closed_on_error=True)
    assert "Withdrawals (allow_withdrawals=True) are permanently prohibited" in str(exc2.value)

    # Fail open forbidden
    with pytest.raises(ValidationError) as exc3:
        SafetyConfig(enable_live_trading=False, allow_withdrawals=False, fail_closed_on_error=False)
    assert "fail_closed_on_error must be True" in str(exc3.value)


def test_risk_limits_rejections() -> None:
    """Ensure risk parameters exceeding architecture caps are rejected."""
    base_kwargs = {
        "per_trade_pct": Decimal("0.25"),
        "max_open_risk_pct": Decimal("0.50"),
        "daily_loss_limit_pct": Decimal("0.75"),
        "weekly_loss_limit_pct": Decimal("2.00"),
        "max_drawdown_pct": Decimal("8.00"),
        "min_risk_reward": Decimal("2.0"),
        "max_new_trades_per_day": 3,
    }

    # per_trade_pct > 0.25%
    with pytest.raises(ValidationError):
        RiskLimitsConfig.model_validate({**base_kwargs, "per_trade_pct": Decimal("0.30")})

    # max_open_risk_pct > 0.50%
    with pytest.raises(ValidationError):
        RiskLimitsConfig.model_validate({**base_kwargs, "max_open_risk_pct": Decimal("0.55")})

    # daily_loss_limit_pct > 0.75%
    with pytest.raises(ValidationError):
        RiskLimitsConfig.model_validate({**base_kwargs, "daily_loss_limit_pct": Decimal("0.80")})

    # max_drawdown_pct > 8.00%
    with pytest.raises(ValidationError):
        RiskLimitsConfig.model_validate({**base_kwargs, "max_drawdown_pct": Decimal("10.00")})

    # min_risk_reward < 2.0
    with pytest.raises(ValidationError):
        RiskLimitsConfig.model_validate({**base_kwargs, "min_risk_reward": Decimal("1.8")})

    # Inverted risk hierarchy (daily loss > weekly loss)
    with pytest.raises(ValidationError):
        RiskLimitsConfig.model_validate(
            {
                **base_kwargs,
                "daily_loss_limit_pct": Decimal("0.75"),
                "weekly_loss_limit_pct": Decimal("0.50"),
            }
        )


def test_futures_safety_rejections() -> None:
    """Ensure leverage > 1x, cross-margin, or live futures are rejected."""
    base_kwargs: dict[str, object] = {
        "enabled_in_paper": True,
        "enabled_live": False,
        "leverage": 1,
        "margin_mode": "isolated",
        "allow_cross_margin": False,
    }

    # Leverage > 1x
    with pytest.raises(ValidationError):
        FuturesConfig.model_validate({**base_kwargs, "leverage": 2})

    # Cross margin mode
    with pytest.raises(ValidationError):
        FuturesConfig.model_validate({**base_kwargs, "margin_mode": "cross"})

    # allow_cross_margin True
    with pytest.raises(ValidationError):
        FuturesConfig.model_validate({**base_kwargs, "allow_cross_margin": True})

    # enabled_live True
    with pytest.raises(ValidationError):
        FuturesConfig.model_validate({**base_kwargs, "enabled_live": True})


def test_execution_safety_rejections() -> None:
    """Ensure Martingale and forced trading are strictly rejected."""
    # Martingale prohibited
    with pytest.raises(ValidationError):
        ExecutionSafetyConfig(
            require_protective_stop=True,
            entry_halt_on_unknown_order=True,
            forced_trading=False,
            martingale=True,
        )

    # Forced trading prohibited
    with pytest.raises(ValidationError):
        ExecutionSafetyConfig(
            require_protective_stop=True,
            entry_halt_on_unknown_order=True,
            forced_trading=True,
            martingale=False,
        )

    # Protective stop disabled prohibited
    with pytest.raises(ValidationError):
        ExecutionSafetyConfig(
            require_protective_stop=False,
            entry_halt_on_unknown_order=True,
            forced_trading=False,
            martingale=False,
        )


def test_symbols_configuration_validations() -> None:
    """Ensure symbol restrictions and timeframes are strictly validated."""
    # Unsupported asset
    with pytest.raises(ValidationError):
        SymbolConfig(
            id="DOGE",  # Only BTC, ETH, SOL allowed
            exchange_symbol="DOGE/USDT",
            enabled=True,
            min_notional=Decimal("5"),
            price_precision=2,
            quantity_precision=2,
            step_size=Decimal("0.1"),
        )

    # Regime timeframe must be 4h
    with pytest.raises(ValidationError):
        TimeframesConfig(regime=TimeFrame.H1, entry=TimeFrame.H1)

    # Entry timeframe must be 1h
    with pytest.raises(ValidationError):
        TimeframesConfig(regime=TimeFrame.H4, entry=TimeFrame.M15)

    # Duplicate symbol IDs
    s_btc = SymbolConfig(
        id="BTC",
        exchange_symbol="BTC/USDT",
        enabled=True,
        min_notional=Decimal("5"),
        price_precision=2,
        quantity_precision=5,
        step_size=Decimal("0.00001"),
    )
    with pytest.raises(ValidationError):
        SymbolsConfigFile(
            symbols=[s_btc, s_btc],
            timeframes=TimeframesConfig(regime=TimeFrame.H4, entry=TimeFrame.H1),
            markets=MarketsConfig(),
        )


def test_strategy_parameter_validations() -> None:
    """Ensure strategy parameter boundaries enforce domain constraints."""
    # Trend following: fast EMA >= slow EMA
    with pytest.raises(ValidationError):
        TrendFollowingConfig(ema_fast=50, ema_slow=20, ema_regime=200)

    # Mean reversion: long RSI threshold >= short RSI threshold
    with pytest.raises(ValidationError):
        MeanReversionConfig(long_rsi_max=Decimal("70"), short_rsi_min=Decimal("30"))

    # Breakout: volume multiplier < 1.0
    with pytest.raises(ValidationError):
        BreakoutConfig(volume_multiplier=Decimal("0.8"))


def test_env_settings_fails_closed_on_unsafe_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure environment variables cannot override safety boundaries."""
    # Attempting to enable live trading via environment
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
    with pytest.raises(ValidationError) as exc1:
        EnvSettings()
    assert "ENABLE_LIVE_TRADING=true is strictly prohibited" in str(exc1.value)

    monkeypatch.undo()

    # Attempting to enable withdrawals via environment
    monkeypatch.setenv("ALLOW_WITHDRAWALS", "true")
    with pytest.raises(ValidationError) as exc2:
        EnvSettings()
    assert "ALLOW_WITHDRAWALS=true is strictly prohibited" in str(exc2.value)

    monkeypatch.undo()

    # Attempting leverage > 1
    monkeypatch.setenv("FUTURES_LEVERAGE", "5")
    with pytest.raises(ValidationError) as exc3:
        EnvSettings()
    assert "FUTURES_LEVERAGE must be 1" in str(exc3.value)


def test_load_yaml_with_decimals_error_cases(tmp_path: Path) -> None:
    """Ensure missing files and non-dict YAML raise explicit exceptions."""
    # Missing file
    with pytest.raises(FileNotFoundError):
        load_yaml_with_decimals(tmp_path / "nonexistent.yaml")

    # Non-dictionary YAML (e.g. list or scalar)
    bad_yaml = tmp_path / "scalar.yaml"
    bad_yaml.write_text("just_a_string", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_yaml_with_decimals(bad_yaml)
    assert "did not parse into a top-level dictionary" in str(exc.value)


def test_symbols_all_disabled_rejected() -> None:
    """Ensure configuring symbols with 0 enabled symbols fails validation."""
    s_btc = SymbolConfig(
        id="BTC",
        exchange_symbol="BTC/USDT",
        enabled=False,
        min_notional=Decimal("5"),
        price_precision=2,
        quantity_precision=5,
        step_size=Decimal("0.00001"),
    )
    with pytest.raises(ValidationError) as exc:
        SymbolsConfigFile(
            symbols=[s_btc],
            timeframes=TimeframesConfig(regime=TimeFrame.H4, entry=TimeFrame.H1),
            markets=MarketsConfig(),
        )
    assert "At least one symbol must be enabled" in str(exc.value)


def test_main_entrypoint_stub() -> None:
    """Ensure main entrypoint executes cleanly without exceptions."""
    from trading_bot.main import main

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
