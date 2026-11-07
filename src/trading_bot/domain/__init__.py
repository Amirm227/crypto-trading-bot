"""Domain models, value objects, and configuration schemas.

Pure business definitions with zero external I/O dependencies.
All financial quantities use Python Decimal; all timestamps use timezone-aware UTC.
"""

from trading_bot.domain.candle import Candle
from trading_bot.domain.config import (
    AppConfig,
    BaseConfigFile,
    BreakoutConfig,
    DatabaseConfig,
    EnvSettings,
    ExchangeConfig,
    ExecutionSafetyConfig,
    FuturesConfig,
    MarketsConfig,
    MeanReversionConfig,
    MonitoringConfig,
    RiskConfigFile,
    RiskLimitsConfig,
    SafeDecimalLoader,
    SafetyConfig,
    SymbolConfig,
    SymbolsConfigFile,
    TimeframesConfig,
    TrendFollowingConfig,
    load_app_config,
    load_yaml_with_decimals,
)
from trading_bot.domain.events import BotEvent, RiskEvent
from trading_bot.domain.fill import Fill
from trading_bot.domain.order import Order
from trading_bot.domain.portfolio import PortfolioSnapshot
from trading_bot.domain.position import Position
from trading_bot.domain.regime import MarketRegime
from trading_bot.domain.risk import RiskDecision
from trading_bot.domain.signal import Signal
from trading_bot.domain.trade import Trade
from trading_bot.domain.types import (
    DomainModel,
    EventSeverity,
    FinancialDecimal,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    RegimeType,
    SignalStatus,
    TimeFrame,
    UTCDateTime,
)

__all__ = [
    "AppConfig",
    "BaseConfigFile",
    "BotEvent",
    "BreakoutConfig",
    "Candle",
    "DatabaseConfig",
    "DomainModel",
    "EnvSettings",
    "EventSeverity",
    "ExchangeConfig",
    "ExecutionSafetyConfig",
    "Fill",
    "FinancialDecimal",
    "FuturesConfig",
    "MarketRegime",
    "MarketType",
    "MarketsConfig",
    "MeanReversionConfig",
    "MonitoringConfig",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PortfolioSnapshot",
    "Position",
    "PositionSide",
    "RegimeType",
    "RiskConfigFile",
    "RiskDecision",
    "RiskEvent",
    "RiskLimitsConfig",
    "SafeDecimalLoader",
    "SafetyConfig",
    "Signal",
    "SignalStatus",
    "SymbolConfig",
    "SymbolsConfigFile",
    "TimeFrame",
    "TimeframesConfig",
    "Trade",
    "TrendFollowingConfig",
    "UTCDateTime",
    "load_app_config",
    "load_yaml_with_decimals",
]
