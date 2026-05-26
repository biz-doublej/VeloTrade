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
import { fmtCurrency, fmtDateTime, fmtNumber } from "@/lib/format";
import { supabaseVt } from "@/lib/supabase/server";

export const revalidate = 10;

interface Order {
  order_id: string;
  account_id: string;
  exchange_order_id: string | null;
  symbol: string;
  side: "buy" | "sell";
  order_type: "market" | "limit";
  qty: string;
  filled_qty: string;
  filled_avg_price: string | null;
  status: string;
  created_at: string;
}

interface Account {
  account_id: string;
  exchange: string;
  account_type: string;
  base_currency: string;
}

function statusVariant(s: string) {
  switch (s) {
    case "filled":
      return "filled" as const;
    case "submitted":
    case "pending":
      return "submitted" as const;
    case "partially_filled":
      return "warn" as const;
    case "cancelled":
      return "cancelled" as const;
    case "rejected":
      return "rejected" as const;
    default:
      return "default" as const;
  }
}

export default async function OrdersPage() {
  const { data: accounts } = await supabaseVt
    .from("exchange_accounts")
    .select("account_id, exchange, account_type, base_currency");
  const accountMap = new Map<string, Account>(
    ((accounts || []) as Account[]).map((a) => [a.account_id, a]),
  );

  const { data, error } = await supabaseVt
    .from("orders")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(50);

  const orders = (data || []) as Order[];

  return (
    <>
      <PageHeader
        title="Orders"
        description={`최근 ${orders.length}건 — 시간 역순, 50건 limit`}
      />

      {error ? (
        <EmptyState message={`error: ${error.message}`} />
      ) : orders.length === 0 ? (
        <EmptyState message="주문 없음 — 봇이 paper/live 주문 시 자동 기록됩니다." />
      ) : (
        <DataTable>
          <THead>
            <tr>
              <TH>Time</TH>
              <TH>Exchange</TH>
              <TH>Symbol</TH>
              <TH>Side</TH>
              <TH align="right">Qty</TH>
              <TH align="right">Fill Price</TH>
              <TH>Status</TH>
              <TH>Type</TH>
            </tr>
          </THead>
          <tbody>
            {orders.map((o) => {
              const acc = accountMap.get(o.account_id);
              const ccy = acc?.base_currency || "USD";
              return (
                <TR key={o.order_id}>
                  <TD className="text-xs text-muted-foreground whitespace-nowrap">
                    {fmtDateTime(o.created_at)}
                  </TD>
                  <TD>
                    <Badge variant="muted">{acc?.exchange ?? "?"}</Badge>
                  </TD>
                  <TD className="font-medium">{o.symbol}</TD>
                  <TD>
                    <Badge variant={o.side === "buy" ? "buy" : "sell"}>
                      {o.side.toUpperCase()}
                    </Badge>
                  </TD>
                  <TD align="right" mono>
                    {fmtNumber(o.filled_qty, 6)} / {fmtNumber(o.qty, 6)}
                  </TD>
                  <TD align="right" mono>
                    {o.filled_avg_price ? fmtCurrency(o.filled_avg_price, ccy) : "-"}
                  </TD>
                  <TD>
                    <Badge variant={statusVariant(o.status)}>{o.status}</Badge>
                  </TD>
                  <TD className="text-xs text-muted-foreground">{o.order_type}</TD>
                </TR>
              );
            })}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
