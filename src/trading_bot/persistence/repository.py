"""PostgreSQL OHLCV candlestick repository implementation.

Provides idempotent single/batch persistence, transaction-safe atomic batch writes,
conflict rejection, deterministic ordering, and gap detection conforming to CandleRepository.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
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
    BatchHomogeneityError,
    CandleRepositoryError,
    ConflictingCandleError,
)
from trading_bot.persistence.models import CandleModel


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _candle_to_dict(candle: Candle) -> dict[str, Any]:
    """Convert domain candle to dictionary for exact persistence insertion."""
    return {
        "exchange": candle.exchange,
        "symbol": candle.symbol,
        "market_type": candle.market_type.value,
        "timeframe": candle.timeframe.value,
        "open_time": _ensure_utc(candle.open_time),
        "close_time": _ensure_utc(candle.close_time),
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "is_closed": candle.is_closed,
        "ingested_at": _ensure_utc(candle.ingested_at),
    }


UNIQUE_CANDLE_KEYS = ["exchange", "symbol", "market_type", "timeframe", "open_time"]


def _build_upsert_stmt(dialect_name: str, values: dict[str, Any] | list[dict[str, Any]]) -> Any:
    """Construct dialect-specific atomic INSERT ... ON CONFLICT DO NOTHING statement."""
    if dialect_name == "postgresql":
        pg_stmt = pg_insert(CandleModel).values(values)
        return pg_stmt.on_conflict_do_nothing(index_elements=UNIQUE_CANDLE_KEYS)
    elif dialect_name == "sqlite":
        sq_stmt = sqlite_insert(CandleModel).values(values)
        return sq_stmt.on_conflict_do_nothing(index_elements=UNIQUE_CANDLE_KEYS)
    else:
        from sqlalchemy import insert

        return insert(CandleModel).values(values)


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
        Handles PostgreSQL unique-constraint race conditions safely using native ON CONFLICT.
        """

        async def _save(s: AsyncSession) -> None:
            norm_open_time = _ensure_utc(candle.open_time)
            # 1. Optimistic insert using dialect ON CONFLICT DO NOTHING
            dialect_name = s.bind.dialect.name if s.bind else "postgresql"
            val = _candle_to_dict(candle)
            stmt = _build_upsert_stmt(dialect_name, val)
            res = await s.execute(stmt)

            cursor_res = cast(CursorResult[Any], res)
            if cursor_res.rowcount is not None and cursor_res.rowcount > 0:
                return

            # 2. Row already exists or concurrent transaction inserted it.
            # Query existing row to check if identical or conflicting.
            q_stmt = select(CandleModel).where(
                CandleModel.exchange == candle.exchange,
                CandleModel.symbol == candle.symbol,
                CandleModel.market_type == candle.market_type.value,
                CandleModel.timeframe == candle.timeframe.value,
                CandleModel.open_time == norm_open_time,
            )
            existing_res = await s.execute(q_stmt)
            existing = existing_res.scalars().first()

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
        Enforces batch homogeneity: all candles must share (exchange, symbol, market_type, timeframe).
        Skips identical duplicates idempotently.
        If any candle in the batch conflicts with existing records or within the batch itself,
        the entire transaction is rolled back and ConflictingCandleError is raised.
        """
        candles = batch.candles if isinstance(batch, CandleBatch) else tuple(batch)
        if not candles:
            return 0

        # 1. Enforce batch homogeneity across all candles
        first = candles[0]
        first_series = (first.exchange, first.symbol, first.market_type, first.timeframe)
        for idx, c in enumerate(candles[1:], start=1):
            c_series = (c.exchange, c.symbol, c.market_type, c.timeframe)
            if c_series != first_series:
                raise BatchHomogeneityError(
                    f"Batch homogeneity violation: all candles in a batch must belong to the same series. "
                    f"Expected {first_series}, but candle at index {idx} has {c_series}."
                )

        # 2. Validate internal batch uniqueness and consistency
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
                # Identical intra-batch duplicate: keep first occurrence deterministically
                continue
            seen_keys[key] = c
            deduped_candles.append(c)

        async def _save_batch(s: AsyncSession) -> int:
            exchange = deduped_candles[0].exchange
            symbol = deduped_candles[0].symbol
            market_type = deduped_candles[0].market_type.value
            timeframe = deduped_candles[0].timeframe.value

            # First, check for historical conflicts against existing records
            timestamps = [_ensure_utc(c.open_time) for c in deduped_candles]
            stmt_query = select(CandleModel).where(
                CandleModel.exchange == exchange,
                CandleModel.symbol == symbol,
                CandleModel.market_type == market_type,
                CandleModel.timeframe == timeframe,
                CandleModel.open_time.in_(timestamps),
            )
            result = await s.execute(stmt_query)
            existing_map = {_ensure_utc(m.open_time): m for m in result.scalars().all()}

            candles_to_insert: list[Candle] = []
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
                    # Identical duplicate: skip
                    continue
                candles_to_insert.append(candle)

            if not candles_to_insert:
                return 0

            # Insert new candles using dialect ON CONFLICT DO NOTHING
            dialect_name = s.bind.dialect.name if s.bind else "postgresql"
            vals = [_candle_to_dict(c) for c in candles_to_insert]
            insert_stmt = _build_upsert_stmt(dialect_name, vals)
            res = await s.execute(insert_stmt)
            cursor_res = cast(CursorResult[Any], res)
            rowcount = cursor_res.rowcount
            inserted_count = (
                rowcount if rowcount is not None and rowcount >= 0 else len(candles_to_insert)
            )

            # If fewer rows were inserted than attempted, verify concurrent duplicate vs conflict
            if inserted_count < len(candles_to_insert):
                post_res = await s.execute(stmt_query)
                current_map = {_ensure_utc(m.open_time): m for m in post_res.scalars().all()}
                for candle in candles_to_insert:
                    norm_open = _ensure_utc(candle.open_time)
                    if norm_open in current_map:
                        cur = current_map[norm_open]
                        if not cur.is_identical(candle):
                            raise ConflictingCandleError(
                                f"Conflicting candle in batch for {candle.exchange} {candle.symbol} "
                                f"{candle.market_type} {candle.timeframe} at {candle.open_time}: "
                                f"existing (open={cur.open}, high={cur.high}, "
                                f"low={cur.low}, close={cur.close}, volume={cur.volume}) "
                                f"vs incoming (open={candle.open}, high={candle.high}, "
                                f"low={candle.low}, close={candle.close}, volume={candle.volume})"
                            )

            return inserted_count

        try:
            return await self._execute_in_session(session, _save_batch)
        except (ConflictingCandleError, BatchHomogeneityError):
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
