"""PostgreSQL OHLCV candlestick repository implementation.

Provides idempotent single/batch persistence, transaction-safe atomic batch writes,
conflict rejection, deterministic ordering, and gap detection conforming to CandleRepository.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import MarketType, TimeFrame
from trading_bot.market_data.contracts import (
    SUPPORTED_FUTURES_SYMBOLS,
    TIMEFRAME_DURATIONS,
    CandleBatch,
    CandleRepository,
    OHLCVRequest,
)
from trading_bot.persistence.database import DatabaseManager
from trading_bot.persistence.exceptions import (
    CandleRepositoryError,
    ConflictingCandleError,
)
from trading_bot.persistence.models import CandleModel


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


T = TypeVar("T")


class PostgresCandleRepository(CandleRepository):
    """PostgreSQL implementation of the CandleRepository domain protocol."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | DatabaseManager,
    ) -> None:
        if isinstance(session_factory, DatabaseManager):
            self._session_factory = session_factory.session_factory
        else:
            self._session_factory = session_factory

    async def _execute_in_session(
        self,
        session: AsyncSession | None,
        coro_fn: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        """Execute a coroutine within an explicit session or a newly managed transaction."""
        if session is not None:
            return await coro_fn(session)
        async with self._session_factory() as s, s.begin():
            return await coro_fn(s)

    async def save_candle(
        self,
        candle: Candle,
        session: AsyncSession | None = None,
    ) -> None:
        """Persist a single candle idempotently.

        If a candle with identical unique keys and values exists, does nothing.
        If a candle with identical unique keys but conflicting values exists,
        raises ConflictingCandleError and rejects modification.
        """

        async def _save(s: AsyncSession) -> None:
            norm_open_time = _ensure_utc(candle.open_time)
            stmt = select(CandleModel).where(
                CandleModel.exchange == candle.exchange,
                CandleModel.symbol == candle.symbol,
                CandleModel.market_type == candle.market_type.value,
                CandleModel.timeframe == candle.timeframe.value,
                CandleModel.open_time == norm_open_time,
            )
            result = await s.execute(stmt)
            existing = result.scalars().first()

            if existing is not None:
                if existing.is_identical(candle):
                    return  # Idempotent identical duplicate
                raise ConflictingCandleError(
                    f"Conflicting candle data for {candle.exchange} {candle.symbol} "
                    f"{candle.market_type} {candle.timeframe} at {candle.open_time}: "
                    f"existing (open={existing.open}, high={existing.high}, low={existing.low}, "
                    f"close={existing.close}, volume={existing.volume}) vs incoming "
                    f"(open={candle.open}, high={candle.high}, low={candle.low}, "
                    f"close={candle.close}, volume={candle.volume})"
                )

            model = CandleModel.from_domain(candle)
            s.add(model)
            await s.flush()

        try:
            await self._execute_in_session(session, _save)
        except ConflictingCandleError:
            raise
        except Exception as e:
            raise CandleRepositoryError(f"Failed to persist candle: {e}") from e

    async def save_batch(
        self,
        batch: CandleBatch | Sequence[Candle],
        session: AsyncSession | None = None,
    ) -> int:
        """Persist a collection of candles atomically.

        Returns the number of newly inserted records.
        Skips identical duplicates idempotently.
        If any candle in the batch conflicts with existing records, the entire transaction
        is rolled back and ConflictingCandleError is raised.
        """
        candles = batch.candles if isinstance(batch, CandleBatch) else tuple(batch)
        if not candles:
            return 0

        # Validate internal batch uniqueness and consistency
        seen_keys: dict[tuple[str, str, str, str, datetime], Candle] = {}
        deduped_candles: list[Candle] = []

        for c in candles:
            norm_open = _ensure_utc(c.open_time)
            key = (c.exchange, c.symbol, c.market_type.value, c.timeframe.value, norm_open)
            if key in seen_keys:
                prev = seen_keys[key]
                if (
                    prev.close_time != c.close_time
                    or prev.open != c.open
                    or prev.high != c.high
                    or prev.low != c.low
                    or prev.close != c.close
                    or prev.volume != c.volume
                    or prev.is_closed != c.is_closed
                ):
                    raise ConflictingCandleError(
                        f"Conflicting duplicate candles found within input batch for key {key}"
                    )
                # Identical intra-batch duplicate: keep first occurrence
                continue
            seen_keys[key] = c
            deduped_candles.append(c)

        async def _save_batch(s: AsyncSession) -> int:
            exchange = deduped_candles[0].exchange
            symbol = deduped_candles[0].symbol
            market_type = deduped_candles[0].market_type.value
            timeframe = deduped_candles[0].timeframe.value

            # Query existing records for all timestamps in the batch
            timestamps = [_ensure_utc(c.open_time) for c in deduped_candles]
            stmt = select(CandleModel).where(
                CandleModel.exchange == exchange,
                CandleModel.symbol == symbol,
                CandleModel.market_type == market_type,
                CandleModel.timeframe == timeframe,
                CandleModel.open_time.in_(timestamps),
            )
            result = await s.execute(stmt)
            existing_map = {_ensure_utc(m.open_time): m for m in result.scalars().all()}

            models_to_insert: list[CandleModel] = []
            for candle in deduped_candles:
                norm_open = _ensure_utc(candle.open_time)
                if norm_open in existing_map:
                    existing = existing_map[norm_open]
                    if not existing.is_identical(candle):
                        raise ConflictingCandleError(
                            f"Conflicting candle in batch for {candle.exchange} {candle.symbol} "
                            f"{candle.market_type} {candle.timeframe} at {candle.open_time}: "
                            f"existing (open={existing.open}, high={existing.high}, "
                            f"low={existing.low}, close={existing.close}, volume={existing.volume}) "
                            f"vs incoming (open={candle.open}, high={candle.high}, "
                            f"low={candle.low}, close={candle.close}, volume={candle.volume})"
                        )
                    # Identical duplicate: skip insertion
                    continue

                models_to_insert.append(CandleModel.from_domain(candle))

            if models_to_insert:
                s.add_all(models_to_insert)
                await s.flush()

            return len(models_to_insert)

        try:
            return await self._execute_in_session(session, _save_batch)
        except ConflictingCandleError:
            raise
        except Exception as e:
            raise CandleRepositoryError(f"Failed to persist candle batch: {e}") from e

    async def get_latest_candle(
        self,
        symbol: str,
        timeframe: TimeFrame,
        closed_only: bool = True,
        exchange: str = "binance",
        market_type: MarketType = MarketType.SPOT,
        session: AsyncSession | None = None,
    ) -> Candle | None:
        """Retrieve the most recent candle for symbol and timeframe with deterministic ordering."""

        async def _query(s: AsyncSession) -> Candle | None:
            stmt = (
                select(CandleModel)
                .where(
                    CandleModel.exchange == exchange,
                    CandleModel.symbol == symbol,
                    CandleModel.market_type == market_type.value,
                    CandleModel.timeframe == timeframe.value,
                )
                .order_by(CandleModel.open_time.desc(), CandleModel.id.desc())
                .limit(1)
            )
            if closed_only:
                stmt = stmt.where(CandleModel.is_closed.is_(True))

            result = await s.execute(stmt)
            model = result.scalars().first()
            return model.to_domain() if model is not None else None

        try:
            return await self._execute_in_session(session, _query)
        except Exception as e:
            raise CandleRepositoryError(f"Failed to query latest candle: {e}") from e

    async def get_candles(
        self,
        request: OHLCVRequest,
        exchange: str = "binance",
        market_type: MarketType | None = None,
        session: AsyncSession | None = None,
    ) -> CandleBatch | None:
        """Query candles from storage matching OHLCVRequest criteria in deterministic ascending order."""
        m_type = market_type
        if m_type is None:
            m_type = (
                MarketType.FUTURES
                if (":" in request.symbol or request.symbol in SUPPORTED_FUTURES_SYMBOLS)
                else MarketType.SPOT
            )

        async def _query(s: AsyncSession) -> CandleBatch | None:
            stmt = (
                select(CandleModel)
                .where(
                    CandleModel.exchange == exchange,
                    CandleModel.symbol == request.symbol,
                    CandleModel.market_type == m_type.value,
                    CandleModel.timeframe == request.timeframe.value,
                )
                .order_by(CandleModel.open_time.asc(), CandleModel.id.asc())
                .limit(request.limit)
            )
            if request.since is not None:
                stmt = stmt.where(CandleModel.open_time >= _ensure_utc(request.since))
            if request.until is not None:
                stmt = stmt.where(CandleModel.open_time <= _ensure_utc(request.until))

            result = await s.execute(stmt)
            models = result.scalars().all()
            if not models:
                return None

            domain_candles = tuple(m.to_domain() for m in models)
            return CandleBatch(
                symbol=request.symbol,
                timeframe=request.timeframe,
                candles=domain_candles,
            )

        try:
            return await self._execute_in_session(session, _query)
        except Exception as e:
            raise CandleRepositoryError(f"Failed to query candles for request: {e}") from e

    async def get_candles_by_range(
        self,
        symbol: str,
        timeframe: TimeFrame,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        exchange: str = "binance",
        market_type: MarketType = MarketType.SPOT,
        limit: int | None = None,
        session: AsyncSession | None = None,
    ) -> tuple[Candle, ...]:
        """Query candles over an explicit time interval sorted deterministically ascending."""

        async def _query(s: AsyncSession) -> tuple[Candle, ...]:
            stmt = (
                select(CandleModel)
                .where(
                    CandleModel.exchange == exchange,
                    CandleModel.symbol == symbol,
                    CandleModel.market_type == market_type.value,
                    CandleModel.timeframe == timeframe.value,
                )
                .order_by(CandleModel.open_time.asc(), CandleModel.id.asc())
            )
            if start_time is not None:
                stmt = stmt.where(CandleModel.open_time >= _ensure_utc(start_time))
            if end_time is not None:
                stmt = stmt.where(CandleModel.open_time <= _ensure_utc(end_time))
            if limit is not None:
                stmt = stmt.limit(limit)

            result = await s.execute(stmt)
            return tuple(m.to_domain() for m in result.scalars().all())

        try:
            return await self._execute_in_session(session, _query)
        except Exception as e:
            raise CandleRepositoryError(f"Failed to query candles by range: {e}") from e

    async def find_gaps(
        self,
        symbol: str,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime,
        exchange: str = "binance",
        market_type: MarketType = MarketType.SPOT,
        session: AsyncSession | None = None,
    ) -> tuple[tuple[datetime, datetime], ...]:
        """Detect missing timestamp intervals in stored historical candle sequences."""
        norm_start = _ensure_utc(start)
        norm_end = _ensure_utc(end)
        if norm_start >= norm_end:
            raise ValueError(f"start ({norm_start}) must be strictly earlier than end ({norm_end})")

        duration = TIMEFRAME_DURATIONS[timeframe]
        candles = await self.get_candles_by_range(
            symbol=symbol,
            timeframe=timeframe,
            start_time=norm_start,
            end_time=norm_end,
            exchange=exchange,
            market_type=market_type,
            session=session,
        )

        gaps: list[tuple[datetime, datetime]] = []
        if not candles:
            return ((norm_start, norm_end),)

        # Check gap between start and first candle
        if candles[0].open_time > norm_start:
            gaps.append((norm_start, candles[0].open_time))

        # Check gaps between consecutive candles
        for i in range(len(candles) - 1):
            expected_next = candles[i].open_time + duration
            actual_next = candles[i + 1].open_time
            if actual_next > expected_next:
                gaps.append((expected_next, actual_next))

        # Check gap between last candle close and end
        if candles[-1].close_time < norm_end:
            gaps.append((candles[-1].close_time, norm_end))

        return tuple(gaps)
