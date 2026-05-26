import { Badge } from "@/components/ui/badge";
import {
  DataTable,
  EmptyState,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui/data-table";
import { PageHeader } from "@/components/ui/page-header";
import { fmtDate, fmtPct, pnlColor } from "@/lib/format";
import { supabaseVt } from "@/lib/supabase/server";

export const revalidate = 30;

interface Backtest {
  backtest_id: string;
  strategy_type: string;
  symbols: string[];
  start_date: string;
  end_date: string;
  initial_capital: string;
  final_value: string;
  total_return_pct: string | null;
  sharpe: string | null;
  max_drawdown_pct: string | null;
  trade_count: number;
  win_rate_pct: string | null;
  results: { params?: Record<string, unknown> };
  created_at: string;
}

function sharpeBadge(s: number | null) {
  if (s === null) return null;
  if (s >= 1.5) return <Badge variant="filled">★ {s.toFixed(2)}</Badge>;
  if (s >= 1.0) return <Badge variant="info">{s.toFixed(2)}</Badge>;
  if (s >= 0.5) return <Badge variant="warn">{s.toFixed(2)}</Badge>;
  return <Badge variant="muted">{s.toFixed(2)}</Badge>;
}

function paramsLabel(strategy: string, p: Record<string, unknown> | undefined): string {
  if (!p) return "-";
  if (strategy === "rsi") {
    return `RSI(${p.period}, ${p.oversold}/${p.overbought})`;
  }
  if (strategy === "ma_cross") {
    return `MA(${p.fast}/${p.slow})`;
  }
  return JSON.stringify(p);
}

export default async function BacktestsPage() {
  // 최신 200건 — sharpe 정렬
  const { data, error } = await supabaseVt
    .from("backtests")
    .select("*")
    .order("sharpe", { ascending: false, nullsFirst: false })
    .limit(200);

  const backtests = (data || []) as Backtest[];

  // 종목별 best (가장 높은 sharpe)
  const bestPerSymbol = new Map<string, Backtest>();
  for (const b of backtests) {
    if (b.symbols.length !== 1) continue;
    const sym = b.symbols[0];
    const prev = bestPerSymbol.get(sym);
    const cur = b.sharpe ? Number(b.sharpe) : -Infinity;
    const prevS = prev?.sharpe ? Number(prev.sharpe) : -Infinity;
    if (cur > prevS) bestPerSymbol.set(sym, b);
  }
  const bestList = Array.from(bestPerSymbol.values()).sort(
    (a, b) => Number(b.sharpe ?? -999) - Number(a.sharpe ?? -999),
  );

  return (
    <>
      <PageHeader
        title="Backtests"
        description={`총 ${backtests.length}건 (단일 종목 best ${bestList.length}건) — sharpe 내림차순`}
      />

      {error ? (
        <EmptyState message={`error: ${error.message}`} />
      ) : backtests.length === 0 ? (
        <EmptyState message="백테스트 결과 없음 — python -m velotrade_trading backtest ... 로 실행 후 보입니다." />
      ) : (
        <>
          <h2 className="text-sm font-medium text-muted-foreground mb-3">
            종목별 Best (Sharpe 기준)
          </h2>
          <div className="mb-8">
            <DataTable>
              <THead>
                <tr>
                  <TH>Symbol</TH>
                  <TH>Strategy</TH>
                  <TH>Params</TH>
                  <TH align="right">Sharpe</TH>
                  <TH align="right">Return</TH>
                  <TH align="right">Max DD</TH>
                  <TH align="right">Trades</TH>
                  <TH align="right">Win</TH>
                  <TH>Period</TH>
                </tr>
              </THead>
              <tbody>
                {bestList.map((b) => {
                  const ret = b.total_return_pct ? Number(b.total_return_pct) : null;
                  const dd = b.max_drawdown_pct ? Number(b.max_drawdown_pct) : null;
                  const sh = b.sharpe ? Number(b.sharpe) : null;
                  return (
                    <TR key={b.backtest_id}>
                      <TD className="font-medium">{b.symbols[0]}</TD>
                      <TD className="text-xs">{b.strategy_type}</TD>
                      <TD className="font-mono text-xs text-muted-foreground">
                        {paramsLabel(b.strategy_type, b.results?.params)}
                      </TD>
                      <TD align="right">{sharpeBadge(sh)}</TD>
                      <TD align="right" mono className={pnlColor(ret)}>
                        {ret !== null ? fmtPct(ret) : "-"}
                      </TD>
                      <TD align="right" mono>
                        {dd !== null ? `${dd.toFixed(2)}%` : "-"}
                      </TD>
                      <TD align="right" mono>{b.trade_count}</TD>
                      <TD align="right" mono className="text-xs text-muted-foreground">
                        {b.win_rate_pct ? `${Number(b.win_rate_pct).toFixed(1)}%` : "-"}
                      </TD>
                      <TD className="text-xs text-muted-foreground whitespace-nowrap">
                        {fmtDate(b.start_date)} → {fmtDate(b.end_date)}
                      </TD>
                    </TR>
                  );
                })}
              </tbody>
            </DataTable>
          </div>

          <h2 className="text-sm font-medium text-muted-foreground mb-3">
            전체 (상위 200건, sharpe 정렬)
          </h2>
          <DataTable>
            <THead>
              <tr>
                <TH>Symbols</TH>
                <TH>Params</TH>
                <TH align="right">Sharpe</TH>
                <TH align="right">Return</TH>
                <TH align="right">DD</TH>
                <TH align="right">Trades</TH>
              </tr>
            </THead>
            <tbody>
              {backtests.map((b) => {
                const ret = b.total_return_pct ? Number(b.total_return_pct) : null;
                const dd = b.max_drawdown_pct ? Number(b.max_drawdown_pct) : null;
                const sh = b.sharpe ? Number(b.sharpe) : null;
                return (
                  <TR key={b.backtest_id}>
                    <TD className="text-xs">{b.symbols.join(", ")}</TD>
                    <TD className="font-mono text-xs text-muted-foreground">
                      {paramsLabel(b.strategy_type, b.results?.params)}
                    </TD>
                    <TD align="right">{sharpeBadge(sh)}</TD>
                    <TD align="right" mono className={pnlColor(ret)}>
                      {ret !== null ? fmtPct(ret) : "-"}
                    </TD>
                    <TD align="right" mono>
                      {dd !== null ? `${dd.toFixed(2)}%` : "-"}
                    </TD>
                    <TD align="right" mono>{b.trade_count}</TD>
                  </TR>
                );
              })}
            </tbody>
          </DataTable>
        </>
      )}
    </>
  );
}
