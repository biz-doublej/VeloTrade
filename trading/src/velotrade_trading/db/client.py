"""Supabase DB 클라이언트 + 기록 헬퍼.

PostgREST + httpx 직접 호출 (supabase-py 의존성 회피 + 새 sb_secret_ 키 형식 지원).
- 모든 호출은 service_role 키 사용 (RLS 우회, 봇 전용)
- vt 스키마는 Data API exposure 필요 — Supabase 대시보드에서 `vt` 스키마를 노출 설정해야 함.
  (자동매매 봇은 service_role 사용해서 어떤 스키마든 접근 가능)
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from typing import Any

import httpx
import structlog

from velotrade_trading.core.types import OrderResult, Position, Signal

log = structlog.get_logger("db")


def _serialize(obj: Any) -> Any:
    """Decimal → str, datetime → ISO 문자열 직렬화."""
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """None 제외 + Decimal/datetime 직렬화."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        out[k] = _serialize(v)
    return out


class DBRecorder:
    """봇이 시그널·주문·알림·포지션을 Supabase 에 기록.

    모든 메서드는 best-effort: DB 호출 실패해도 봇 자체는 멈추지 않음.
    실패 시 logger.warning 으로만 알림.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        service_role_key: str | None = None,
        schema: str = "vt",
    ) -> None:
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.key = service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not self.url or not self.key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing — DB recording disabled"
            )
        self.schema = schema
        self._client = httpx.AsyncClient(
            base_url=f"{self.url}/rest/v1",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Profile": schema,    # write 시 schema 지정
                "Accept-Profile": schema,     # read 시 schema 지정
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            timeout=httpx.Timeout(10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # --- 저수준 헬퍼 --------------------------------------------------------

    async def _insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            r = await self._client.post(f"/{table}", json=_clean(payload))
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else None
        except Exception as e:
            log.warning("db.insert.failed", table=table, error=str(e)[:200])
            return None

    async def _update(
        self, table: str, match: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        try:
            params = {k: f"eq.{v}" for k, v in match.items()}
            r = await self._client.patch(f"/{table}", params=params, json=_clean(payload))
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else None
        except Exception as e:
            log.warning("db.update.failed", table=table, error=str(e)[:200])
            return None

    async def _upsert(
        self, table: str, payload: dict[str, Any], on_conflict: str
    ) -> dict[str, Any] | None:
        try:
            r = await self._client.post(
                f"/{table}",
                params={"on_conflict": on_conflict},
                headers={"Prefer": "return=representation,resolution=merge-duplicates"},
                json=_clean(payload),
            )
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else None
        except Exception as e:
            log.warning("db.upsert.failed", table=table, error=str(e)[:200])
            return None

    async def _select_one(
        self, table: str, match: dict[str, Any]
    ) -> dict[str, Any] | None:
        try:
            params = {k: f"eq.{v}" for k, v in match.items()}
            params["limit"] = "1"
            r = await self._client.get(f"/{table}", params=params)
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else None
        except Exception as e:
            log.warning("db.select.failed", table=table, error=str(e)[:200])
            return None

    # --- 도메인 메서드 ------------------------------------------------------

    async def record_signal(
        self,
        signal: Signal,
        *,
        instance_id: str | None = None,
        rejected_by_risk: bool = False,
        reject_reason: str | None = None,
    ) -> str | None:
        row = await self._insert(
            "signals",
            {
                "instance_id": instance_id,
                "symbol": signal.symbol,
                "side": signal.side,
                "size_pct": signal.size_pct,
                "confidence": signal.confidence,
                "reasoning": signal.reasoning,
                "meta": {**signal.meta, "strategy": signal.strategy},
                "rejected_by_risk": rejected_by_risk,
                "reject_reason": reject_reason,
            },
        )
        return row.get("signal_id") if row else None

    async def record_order(
        self,
        result: OrderResult,
        *,
        signal_id: str | None = None,
        account_id: str | None = None,
    ) -> str | None:
        row = await self._insert(
            "orders",
            {
                "signal_id": signal_id,
                "account_id": account_id,
                "client_order_id": result.client_order_id,
                "exchange_order_id": result.exchange_order_id,
                "symbol": result.symbol,
                "side": result.side,
                "order_type": result.type,
                "qty": result.qty,
                "status": result.status,
                "filled_qty": result.filled_qty,
                "filled_avg_price": result.filled_avg_price,
                "raw": result.raw,
            },
        )
        return row.get("order_id") if row else None

    async def upsert_position(
        self, *, account_id: str, position: Position
    ) -> str | None:
        row = await self._upsert(
            "positions",
            {
                "account_id": account_id,
                "symbol": position.symbol,
                "qty": position.qty,
                "avg_entry_price": position.avg_entry_price,
                "current_price": position.current_price,
                "unrealized_pnl": position.unrealized_pnl,
            },
            on_conflict="account_id,symbol",
        )
        return row.get("position_id") if row else None

    async def record_backtest(
        self,
        *,
        strategy_type: str,
        symbols: list[str],
        start_date: str,             # ISO YYYY-MM-DD
        end_date: str,
        initial_capital: Decimal,
        final_value: Decimal,
        total_return_pct: float,
        sharpe: float,
        max_drawdown_pct: float,
        trade_count: int,
        win_rate_pct: float,
        instance_id: str | None = None,
        params: dict[str, Any] | None = None,
        trades_summary: list[dict[str, Any]] | None = None,
    ) -> str | None:
        results_json = {
            "params": params or {},
            "trades_count": len(trades_summary or []),
            # 처음/마지막 50개만 저장 (큰 결과 방지)
            "trades_head": (trades_summary or [])[:50],
            "trades_tail": (trades_summary or [])[-50:] if trades_summary and len(trades_summary) > 50 else [],
        }
        row = await self._insert(
            "backtests",
            {
                "instance_id": instance_id,
                "strategy_type": strategy_type,
                "symbols": symbols,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": initial_capital,
                "final_value": final_value,
                "total_return_pct": total_return_pct,
                "sharpe": sharpe,
                "max_drawdown_pct": max_drawdown_pct,
                "trade_count": trade_count,
                "win_rate_pct": win_rate_pct,
                "results": results_json,
            },
        )
        return row.get("backtest_id") if row else None

    async def record_alert(
        self,
        *,
        level: str,
        alert_type: str,
        title: str,
        body: str = "",
        symbol: str | None = None,
        meta: dict[str, Any] | None = None,
        delivered_via: list[str] | None = None,
    ) -> str | None:
        row = await self._insert(
            "alerts",
            {
                "alert_type": alert_type,
                "level": level,
                "symbol": symbol,
                "title": title,
                "body": body,
                "meta": meta or {},
                "delivered_via": delivered_via,
            },
        )
        return row.get("alert_id") if row else None


# --- 정적 헬퍼 (모듈 함수) ---------------------------------------------------


async def get_or_create_account(
    db: DBRecorder,
    *,
    exchange: str,
    account_type: str,
    label: str,
    base_currency: str,
    starting_capital: Decimal | None = None,
) -> str | None:
    """label 기준으로 (없으면 생성)."""
    row = await db._select_one(
        "exchange_accounts",
        {"exchange": exchange, "account_type": account_type, "label": label},
    )
    if row:
        return row["account_id"]
    row = await db._insert(
        "exchange_accounts",
        {
            "exchange": exchange,
            "account_type": account_type,
            "label": label,
            "base_currency": base_currency,
            "starting_capital": starting_capital,
            "enabled": True,
        },
    )
    return row.get("account_id") if row else None


async def get_watchlist(db: DBRecorder, *, exchange: str) -> list[str]:
    """해당 거래소의 enabled=true 종목 목록."""
    try:
        r = await db._client.get(
            "/watchlist_items",
            params={"exchange": f"eq.{exchange}", "enabled": "eq.true", "select": "symbol"},
        )
        r.raise_for_status()
        return [row["symbol"] for row in r.json()]
    except Exception as e:
        log.warning("db.watchlist.failed", exchange=exchange, error=str(e)[:200])
        return []


# 동기 호출 어댑터 — 동기 코드(seed 스크립트 등)에서 사용
def run_sync(coro):
    """asyncio.run 의 단순 래퍼. event loop 안에서는 호출 금지."""
    return asyncio.run(coro)
