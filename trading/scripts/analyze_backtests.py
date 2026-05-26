"""DB 의 backtest 결과로 종목별 best 파라미터 + 패턴 분석.

출력:
- 종목별 best by sharpe / return / lowest drawdown
- 파라미터 분포 (어떤 RSI period/oversold/overbought 가 자주 best 인가)
- 종목군별 (Mag7/ETF/섹터) 평균 성과
"""

import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

import httpx
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


GROUPS = {
    "Mag7": {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"},
    "Index ETF": {"SPY", "QQQ", "IWM", "DIA"},
    "Sector ETF": {"XLF", "XLE", "XLK", "XLV"},
    "Other Stock": {"JPM", "JNJ", "XOM"},
    "Crypto (Binance)": {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"},
    "Crypto (Upbit)": {"KRW-BTC", "KRW-ETH"},
}


def group_of(symbol: str) -> str:
    for name, syms in GROUPS.items():
        if symbol in syms:
            return name
    return "Other"


async def main():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise SystemExit("SUPABASE keys missing")

    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": "vt"}

    async with httpx.AsyncClient(base_url=f"{url}/rest/v1", headers=headers, timeout=20.0) as c:
        # 모든 backtest 가져오기 (큰 결과면 페이지네이션 필요하지만 우리는 적음)
        r = await c.get(
            "/backtests",
            params={
                "select": "symbols,strategy_type,total_return_pct,sharpe,max_drawdown_pct,"
                          "trade_count,win_rate_pct,results",
                "order": "sharpe.desc.nullslast",
            },
        )
        r.raise_for_status()
        rows = r.json()
        print(f"loaded {len(rows)} backtests from vt.backtests\n")

    # 종목별로 분류 (단일 종목 백테스트만 — symbols 가 [sym] 인 경우)
    by_symbol: dict[str, list[dict]] = {}
    for row in rows:
        symbols = row.get("symbols") or []
        if len(symbols) != 1:
            continue
        sym = symbols[0]
        by_symbol.setdefault(sym, []).append(row)

    # === 종목별 best by Sharpe ===
    print("=" * 96)
    print(f"{'symbol':<10} {'group':<18} {'best sharpe':>12} {'return':>9} {'dd':>8} "
          f"{'trades':>7} {'win':>6} {'params':<35}")
    print("=" * 96)

    period_counter = Counter()
    oversold_counter = Counter()
    overbought_counter = Counter()
    group_stats: dict[str, list[dict]] = {}

    sorted_symbols = sorted(by_symbol.keys(), key=lambda s: (group_of(s), s))
    for sym in sorted_symbols:
        results = by_symbol[sym]
        best = max(results, key=lambda r: r["sharpe"] or -999)
        params = best.get("results", {}).get("params", {})
        period = params.get("period", "?")
        os_ = params.get("oversold", "?")
        ob = params.get("overbought", "?")
        if best["sharpe"] is not None and best["sharpe"] > 0:
            period_counter[period] += 1
            oversold_counter[os_] += 1
            overbought_counter[ob] += 1

        g = group_of(sym)
        group_stats.setdefault(g, []).append(best)

        print(
            f"{sym:<10} {g:<18} {best['sharpe']:>+12.2f} "
            f"{best['total_return_pct']:>+8.2f}% {best['max_drawdown_pct']:>7.2f}% "
            f"{best['trade_count']:>7d} {best['win_rate_pct']:>5.1f}% "
            f"RSI({period}, {os_}/{ob})"
        )

    # === 종목군별 평균 ===
    print("\n=== 종목군별 평균 (best by sharpe) ===")
    print(f"{'group':<20} {'count':>6} {'avg sharpe':>12} {'avg return':>12} {'avg dd':>10}")
    for g, items in group_stats.items():
        n = len(items)
        avg_sharpe = sum(i["sharpe"] or 0 for i in items) / n
        avg_ret = sum(i["total_return_pct"] or 0 for i in items) / n
        avg_dd = sum(i["max_drawdown_pct"] or 0 for i in items) / n
        print(f"{g:<20} {n:>6d} {avg_sharpe:>+12.2f} {avg_ret:>+11.2f}% {avg_dd:>9.2f}%")

    # === 파라미터 분포 ===
    print("\n=== 어떤 RSI 파라미터가 자주 'best' 인가 ===")
    print(f"period       : {dict(period_counter.most_common())}")
    print(f"oversold     : {dict(oversold_counter.most_common())}")
    print(f"overbought   : {dict(overbought_counter.most_common())}")


if __name__ == "__main__":
    asyncio.run(main())
