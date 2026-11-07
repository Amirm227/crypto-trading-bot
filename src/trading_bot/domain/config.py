"""Configuration schemas, custom YAML Decimal loader, and fail-closed validation models.

Guarantees type safety, exact Decimal precision, and strict enforcement of all risk,
safety, and architectural mandates across system configuration files.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    TimeFrame,
)


class SafeDecimalLoader(yaml.SafeLoader):
    """YAML loader that constructs Python Decimal directly from float tokens without binary float drift."""


SafeDecimalLoader.add_constructor(
    "tag:yaml.org,2002:float",
    lambda loader, node: Decimal(loader.construct_scalar(node)),  # type: ignore[arg-type]
)


def load_yaml_with_decimals(file_path: Path | str) -> dict[str, Any]:
    """Load a YAML file parsing floating-point numbers directly as Python Decimal."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Configuration file does not exist: {p}")
    content = p.read_text(encoding="utf-8")
    loaded = yaml.load(content, Loader=SafeDecimalLoader)
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration file {p} did not parse into a top-level dictionary")
    return loaded


class ExchangeConfig(DomainModel):
    """Exchange connectivity parameters."""

    exchange_id: str = "binance"
    sandbox: bool = True
    timeout_ms: int = Field(default=10000, gt=0)
    rate_limit_enabled: bool = True

    @model_validator(mode="after")
    def validate_exchange(self) -> Self:
        if not self.exchange_id.strip():
            raise ValueError("exchange_id must not be empty")
        return self


class DatabaseConfig(DomainModel):
    """Database connectivity parameters."""

    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    name: str = "trading_bot"
    user: str = "postgres"
    password: str = "placeholder_db_password"
    ssl_mode: str = "prefer"

    @model_validator(mode="after")
    def validate_db(self) -> Self:
        if not self.name.strip():
            raise ValueError("database name must not be empty")
        if not self.user.strip():
            raise ValueError("database user must not be empty")
        return self

    def get_url(self, password: str | None = None) -> str:
        """Construct PostgreSQL asyncpg connection URL."""
        pwd = password if password is not None else self.password
        return f"postgresql+asyncpg://{self.user}:{pwd}@{self.host}:{self.port}/{self.name}"


class MonitoringConfig(DomainModel):
    """Monitoring, health check, and metrics parameters."""

    heartbeat_interval_seconds: int = Field(default=30, gt=0)
    metrics_enabled: bool = True
    metrics_port: int = Field(default=8000, ge=1024, le=65535)


class SafetyConfig(DomainModel):
    """Non-negotiable system safety boundaries."""

    enable_live_trading: bool = False
    allow_withdrawals: bool = False
    fail_closed_on_error: bool = True

    @model_validator(mode="after")
    def enforce_safety_invariants(self) -> Self:
        if self.enable_live_trading:
            raise ValueError(
                "Live trading (enable_live_trading=True) is strictly prohibited in Phase 0. "
                "Only 'paper' or 'backtest' environments are permitted."
            )
        if self.allow_withdrawals:
            raise ValueError(
                "Withdrawals (allow_withdrawals=True) are permanently prohibited. "
                "The bot must never have withdrawal permissions."
            )
        if not self.fail_closed_on_error:
            raise ValueError("fail_closed_on_error must be True. Fail-open operation is prohibited.")
        return self


class RiskLimitsConfig(DomainModel):
    """Mandatory trade-level and portfolio-level risk caps."""

    per_trade_pct: FinancialDecimal = Decimal("0.25")
    max_open_risk_pct: FinancialDecimal = Decimal("0.50")
    daily_loss_limit_pct: FinancialDecimal = Decimal("0.75")
    weekly_loss_limit_pct: FinancialDecimal = Decimal("2.00")
    max_drawdown_pct: FinancialDecimal = Decimal("8.00")
    min_risk_reward: FinancialDecimal = Decimal("2.0")
    max_new_trades_per_day: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def validate_risk_limits(self) -> Self:
        zero = Decimal("0")
        if self.per_trade_pct <= zero or self.per_trade_pct > Decimal("0.25"):
            raise ValueError(f"per_trade_pct must be in (0, 0.25], got {self.per_trade_pct}")

        if self.max_open_risk_pct <= zero or self.max_open_risk_pct > Decimal("0.50"):
            raise ValueError(f"max_open_risk_pct must be in (0, 0.50], got {self.max_open_risk_pct}")

        if self.daily_loss_limit_pct <= zero or self.daily_loss_limit_pct > Decimal("0.75"):
            raise ValueError(f"daily_loss_limit_pct must be in (0, 0.75], got {self.daily_loss_limit_pct}")

        if self.weekly_loss_limit_pct <= zero or self.weekly_loss_limit_pct > Decimal("2.00"):
            raise ValueError(f"weekly_loss_limit_pct must be in (0, 2.00], got {self.weekly_loss_limit_pct}")

        if self.max_drawdown_pct <= zero or self.max_drawdown_pct > Decimal("8.00"):
            raise ValueError(f"max_drawdown_pct must be in (0, 8.00], got {self.max_drawdown_pct}")

        if self.min_risk_reward < Decimal("2.0"):
            raise ValueError(f"min_risk_reward must be >= 2.0, got {self.min_risk_reward}")

        if self.per_trade_pct > self.max_open_risk_pct:
            raise ValueError(
                f"per_trade_pct ({self.per_trade_pct}) cannot exceed max_open_risk_pct ({self.max_open_risk_pct})"
            )

        if not (self.daily_loss_limit_pct <= self.weekly_loss_limit_pct <= self.max_drawdown_pct):
            raise ValueError(
                f"Risk hierarchy violated: requires daily ({self.daily_loss_limit_pct}) <= "
                f"weekly ({self.weekly_loss_limit_pct}) <= drawdown ({self.max_drawdown_pct})"
            )

        return self


class FuturesConfig(DomainModel):
    """Futures trading constraints."""

    enabled_in_paper: bool = True
    enabled_live: bool = False
    leverage: int = 1
    margin_mode: str = "isolated"
    allow_cross_margin: bool = False

    @model_validator(mode="after")
    def validate_futures(self) -> Self:
        if self.enabled_live:
            raise ValueError("Futures live trading (enabled_live=True) is strictly prohibited.")
        if self.leverage != 1:
            raise ValueError(f"Futures leverage must be exactly 1x, got {self.leverage}x.")
        if self.margin_mode.lower() != "isolated":
            raise ValueError(f"Margin mode must be 'isolated', got {self.margin_mode!r}.")
        if self.allow_cross_margin:
            raise ValueError("allow_cross_margin must be False. Cross margin is strictly prohibited.")
        return self


class ExecutionSafetyConfig(DomainModel):
    """Execution state machine and order safety settings."""

    require_protective_stop: bool = True
    entry_halt_on_unknown_order: bool = True
    forced_trading: bool = False
    martingale: bool = False

    @model_validator(mode="after")
    def validate_execution_safety(self) -> Self:
        if not self.require_protective_stop:
            raise ValueError("require_protective_stop must be True.")
        if not self.entry_halt_on_unknown_order:
            raise ValueError("entry_halt_on_unknown_order must be True.")
        if self.forced_trading:
            raise ValueError("forced_trading must be False. Forced trading is strictly prohibited.")
        if self.martingale:
            raise ValueError("martingale must be False. Martingale sizing is strictly prohibited.")
        return self


class RiskConfigFile(DomainModel):
    """Schema for configs/risk.yaml."""

    profile: str
    risk: RiskLimitsConfig
    futures: FuturesConfig
    execution: ExecutionSafetyConfig
    safety: SafetyConfig


class SymbolConfig(DomainModel):
    """Symbol-specific trading constraints."""

    id: str
    exchange_symbol: str
    enabled: bool = True
    min_notional: FinancialDecimal
    price_precision: int = Field(ge=0, le=8)
    quantity_precision: int = Field(ge=0, le=8)
    step_size: FinancialDecimal

    @model_validator(mode="after")
    def validate_symbol(self) -> Self:
        if self.id.upper() not in {"BTC", "ETH", "SOL"}:
            raise ValueError(f"Symbol id must be one of BTC, ETH, SOL; got {self.id!r}")
        if not self.exchange_symbol.strip():
            raise ValueError("exchange_symbol must not be empty")
        zero = Decimal("0")
        if self.min_notional < zero:
            raise ValueError("min_notional cannot be negative")
        if self.step_size <= zero:
            raise ValueError("step_size must be strictly positive")
        return self


class TimeframesConfig(DomainModel):
    """System timeframe parameters."""

    regime: TimeFrame = TimeFrame.H4
    entry: TimeFrame = TimeFrame.H1

    @model_validator(mode="after")
    def validate_timeframes(self) -> Self:
        if self.regime != TimeFrame.H4:
            raise ValueError(f"Regime timeframe must be 4h, got {self.regime}")
        if self.entry != TimeFrame.H1:
            raise ValueError(f"Entry timeframe must be 1h, got {self.entry}")
        return self


class MarketsConfig(DomainModel):
    """Enabled market types."""

    spot: bool = True
    futures_paper: bool = True
    futures_live: bool = False

    @model_validator(mode="after")
    def validate_markets(self) -> Self:
        if self.futures_live:
            raise ValueError("futures_live must be False.")
        return self


class SymbolsConfigFile(DomainModel):
    """Schema for configs/symbols.yaml."""

    symbols: list[SymbolConfig]
    timeframes: TimeframesConfig
    markets: MarketsConfig

    @model_validator(mode="after")
    def validate_symbols_file(self) -> Self:
        if not self.symbols:
            raise ValueError("At least one symbol must be configured")
        enabled_count = sum(1 for s in self.symbols if s.enabled)
        if enabled_count == 0:
            raise ValueError("At least one symbol must be enabled")
        # Check uniqueness
        ids = [s.id.upper() for s in self.symbols]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate symbol ids detected: {ids}")
        return self


class TrendFollowingConfig(DomainModel):
    """Strategy parameters for Trend Following."""

    enabled: bool = True
    strategy_id: str = "trend_following"
    version: str = "1.0.0"
    adx_period: int = Field(default=14, ge=5)
    adx_min: FinancialDecimal = Decimal("25.0")
    ema_fast: int = Field(default=20, ge=5)
    ema_slow: int = Field(default=50, ge=10)
    ema_regime: int = Field(default=200, ge=50)
    rsi_period: int = Field(default=14, ge=2)
    long_rsi_min: FinancialDecimal = Decimal("45.0")
    long_rsi_max: FinancialDecimal = Decimal("65.0")
    short_rsi_min: FinancialDecimal = Decimal("35.0")
    short_rsi_max: FinancialDecimal = Decimal("55.0")
    atr_period: int = Field(default=14, ge=2)
    atr_stop_buffer: FinancialDecimal = Decimal("0.2")
    min_risk_reward: FinancialDecimal = Decimal("2.0")

    @model_validator(mode="after")
    def validate_trend(self) -> Self:
        if not (self.ema_fast < self.ema_slow < self.ema_regime):
            raise ValueError(
                f"EMA hierarchy violated: requires ema_fast ({self.ema_fast}) < "
                f"ema_slow ({self.ema_slow}) < ema_regime ({self.ema_regime})"
            )
        if not (self.long_rsi_min < self.long_rsi_max):
            raise ValueError("long_rsi_min must be less than long_rsi_max")
        if not (self.short_rsi_min < self.short_rsi_max):
            raise ValueError("short_rsi_min must be less than short_rsi_max")
        if self.min_risk_reward < Decimal("2.0"):
            raise ValueError("min_risk_reward must be >= 2.0")
        return self


class MeanReversionConfig(DomainModel):
    """Strategy parameters for Mean Reversion."""

    enabled: bool = True
    strategy_id: str = "mean_reversion"
    version: str = "1.0.0"
    adx_max: FinancialDecimal = Decimal("20.0")
    bb_period: int = Field(default=20, ge=5)
    bb_stddev: FinancialDecimal = Decimal("2.0")
    rsi_period: int = Field(default=14, ge=2)
    long_rsi_max: FinancialDecimal = Decimal("30.0")
    short_rsi_min: FinancialDecimal = Decimal("70.0")
    exit_target: str = "middle_band"
    min_risk_reward: FinancialDecimal = Decimal("2.0")

    @model_validator(mode="after")
    def validate_mean_rev(self) -> Self:
        if self.long_rsi_max >= self.short_rsi_min:
            raise ValueError("long_rsi_max must be strictly less than short_rsi_min")
        if self.bb_stddev < Decimal("1.0"):
            raise ValueError("bb_stddev must be >= 1.0")
        if self.min_risk_reward < Decimal("2.0"):
            raise ValueError("min_risk_reward must be >= 2.0")
        return self


class BreakoutConfig(DomainModel):
    """Strategy parameters for Breakout."""

    enabled: bool = True
    strategy_id: str = "breakout"
    version: str = "1.0.0"
    donchian_period: int = Field(default=20, ge=5)
    volume_sma_period: int = Field(default=20, ge=5)
    volume_multiplier: FinancialDecimal = Decimal("1.5")
    entry_mode: str = "breakout"
    min_risk_reward: FinancialDecimal = Decimal("2.0")

    @model_validator(mode="after")
    def validate_breakout(self) -> Self:
        if self.volume_multiplier < Decimal("1.0"):
            raise ValueError("volume_multiplier must be >= 1.0")
        if self.min_risk_reward < Decimal("2.0"):
            raise ValueError("min_risk_reward must be >= 2.0")
        return self


class BaseConfigFile(DomainModel):
    """Schema for configs/base.yaml."""

    app_name: str = "crypto-trading-bot"
    version: str = "0.1.0"
    environment: str = "paper"
    log_level: str = "INFO"
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)

    @model_validator(mode="after")
    def validate_base(self) -> Self:
        if self.environment.lower() not in {"paper", "backtest"}:
            raise ValueError(f"environment must be 'paper' or 'backtest', got {self.environment!r}")
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid log_level: {self.log_level!r}")
        return self


class EnvSettings(BaseSettings):
    """Environment variable overrides using pydantic-settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "paper"
    log_level: str = "INFO"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "trading_bot"
    db_user: str = "postgres"
    db_password: str = "placeholder_db_password"
    database_url: str | None = None
    exchange_id: str = "binance"
    exchange_sandbox: bool = True
    enable_live_trading: bool = False
    allow_withdrawals: bool = False
    futures_leverage: int = 1
    margin_mode: str = "isolated"
    allow_cross_margin: bool = False

    @model_validator(mode="after")
    def validate_env_settings(self) -> Self:
        if self.app_env.lower() not in {"paper", "backtest"}:
            raise ValueError(
                f"APP_ENV must be 'paper' or 'backtest', got {self.app_env!r}. "
                "Live environment is strictly prohibited."
            )
        if self.enable_live_trading:
            raise ValueError("ENABLE_LIVE_TRADING=true is strictly prohibited in Phase 0.")
        if self.allow_withdrawals:
            raise ValueError("ALLOW_WITHDRAWALS=true is strictly prohibited.")
        if self.futures_leverage != 1:
            raise ValueError("FUTURES_LEVERAGE must be 1.")
        if self.margin_mode.lower() != "isolated":
            raise ValueError("MARGIN_MODE must be 'isolated'.")
        if self.allow_cross_margin:
            raise ValueError("ALLOW_CROSS_MARGIN must be false.")
        return self


class AppConfig(DomainModel):
    """Unified application configuration aggregating base, risk, symbols, strategies, and environment settings."""

    base: BaseConfigFile
    risk: RiskConfigFile
    symbols: SymbolsConfigFile
    trend_following: TrendFollowingConfig
    mean_reversion: MeanReversionConfig
    breakout: BreakoutConfig
    env_settings: EnvSettings


def load_app_config(
    config_dir: Path | str = "configs",
    env_file: Path | str | None = None,
) -> AppConfig:
    """Load and validate all application configuration files and environment overrides."""
    base_dir = Path(config_dir)

    base_raw = load_yaml_with_decimals(base_dir / "base.yaml")
    risk_raw = load_yaml_with_decimals(base_dir / "risk.yaml")
    symbols_raw = load_yaml_with_decimals(base_dir / "symbols.yaml")
    tf_raw = load_yaml_with_decimals(base_dir / "strategies" / "trend_following.yaml")
    mr_raw = load_yaml_with_decimals(base_dir / "strategies" / "mean_reversion.yaml")
    bo_raw = load_yaml_with_decimals(base_dir / "strategies" / "breakout.yaml")

    env_kwargs: dict[str, Any] = {}
    if env_file is not None:
        env_kwargs["_env_file"] = str(env_file)
    env_settings = EnvSettings(**env_kwargs)

    base_cfg = BaseConfigFile.model_validate(base_raw)
    risk_cfg = RiskConfigFile.model_validate(risk_raw)
    symbols_cfg = SymbolsConfigFile.model_validate(symbols_raw)
    tf_cfg = TrendFollowingConfig.model_validate(tf_raw)
    mr_cfg = MeanReversionConfig.model_validate(mr_raw)
    bo_cfg = BreakoutConfig.model_validate(bo_raw)

    return AppConfig(
        base=base_cfg,
        risk=risk_cfg,
        symbols=symbols_cfg,
        trend_following=tf_cfg,
        mean_reversion=mr_cfg,
        breakout=bo_cfg,
        env_settings=env_settings,
    )
