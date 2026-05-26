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
import { fmtCurrency, fmtNumber, pnlColor } from "@/lib/format";
import { supabaseVt } from "@/lib/supabase/server";

export const revalidate = 10;  // 10 초마다 SSR 캐시

interface Position {
  position_id: string;
  account_id: string;
  symbol: string;
  qty: string;
  avg_entry_price: string;
  current_price: string | null;
  unrealized_pnl: string | null;
  updated_at: string;
}

interface Account {
  account_id: string;
  exchange: string;
  account_type: string;
  label: string;
  base_currency: string;
}

export default async function PositionsPage() {
  // 1. 모든 계좌 조회
  const { data: accounts } = await supabaseVt
    .from("exchange_accounts")
    .select("account_id, exchange, account_type, label, base_currency");
  const accountMap = new Map<string, Account>(
    ((accounts || []) as Account[]).map((a) => [a.account_id, a]),
  );

  // 2. 포지션 (qty != 0)
  const { data, error } = await supabaseVt
    .from("positions")
    .select("*")
    .neq("qty", 0)
    .order("updated_at", { ascending: false });

  const positions = (data || []) as Position[];

  return (
    <>
      <PageHeader
        title="Positions"
        description={`현재 보유 포지션 — 총 ${positions.length}건 (각 봇이 거래 시 자동 동기화)`}
      />

      {error ? (
        <EmptyState message={`error: ${error.message}`} />
      ) : positions.length === 0 ? (
        <EmptyState message="보유 포지션 없음 — 봇이 매수 후 자동으로 채워집니다." />
      ) : (
        <DataTable>
          <THead>
            <tr>
              <TH>Exchange</TH>
              <TH>Symbol</TH>
              <TH align="right">Qty</TH>
              <TH align="right">Avg Entry</TH>
              <TH align="right">Current</TH>
              <TH align="right">Unrealized PnL</TH>
              <TH align="right">Updated</TH>
            </tr>
          </THead>
          <tbody>
            {positions.map((p) => {
              const acc = accountMap.get(p.account_id);
              const ccy = acc?.base_currency || "USD";
              const pnl = p.unrealized_pnl ? Number(p.unrealized_pnl) : null;
              return (
                <TR key={p.position_id}>
                  <TD>
                    <Badge variant="muted">{acc?.exchange ?? "?"}</Badge>
                    <span className="ml-2 text-xs text-muted-foreground">
                      {acc?.account_type}
                    </span>
                  </TD>
                  <TD className="font-medium">{p.symbol}</TD>
                  <TD align="right" mono>
                    {fmtNumber(p.qty, 6)}
                  </TD>
                  <TD align="right" mono>
                    {fmtCurrency(p.avg_entry_price, ccy)}
                  </TD>
                  <TD align="right" mono>
                    {fmtCurrency(p.current_price, ccy)}
                  </TD>
                  <TD align="right" mono className={pnlColor(pnl)}>
                    {pnl !== null ? fmtCurrency(pnl, ccy) : "-"}
                  </TD>
                  <TD align="right" className="text-xs text-muted-foreground">
                    {new Date(p.updated_at).toLocaleTimeString("ko-KR")}
                  </TD>
                </TR>
              );
            })}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
