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
import { fmtDateTime } from "@/lib/format";
import { supabaseVt } from "@/lib/supabase/server";

export const revalidate = 10;

interface Signal {
  signal_id: string;
  symbol: string;
  side: "buy" | "sell" | "hold";
  size_pct: string;
  confidence: string;
  reasoning: string | null;
  meta: Record<string, unknown>;
  rejected_by_risk: boolean;
  reject_reason: string | null;
  created_at: string;
}

export default async function SignalsPage() {
  const { data, error } = await supabaseVt
    .from("signals")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(100);

  const signals = (data || []) as Signal[];
  const rejectedCount = signals.filter((s) => s.rejected_by_risk).length;
  const passedCount = signals.length - rejectedCount;

  return (
    <>
      <PageHeader
        title="Signals"
        description={
          signals.length > 0
            ? `최근 ${signals.length}건 (통과 ${passedCount} · risk 거부 ${rejectedCount})`
            : "전략이 생성한 매매 시그널 로그"
        }
      />

      {error ? (
        <EmptyState message={`error: ${error.message}`} />
      ) : signals.length === 0 ? (
        <EmptyState message="시그널 없음 — 봇 실행 시 RSI/MA cross/LLM 시그널이 기록됩니다." />
      ) : (
        <DataTable>
          <THead>
            <tr>
              <TH>Time</TH>
              <TH>Symbol</TH>
              <TH>Side</TH>
              <TH>Strategy</TH>
              <TH align="right">Size %</TH>
              <TH align="right">Conf</TH>
              <TH>Status</TH>
              <TH>Reasoning</TH>
            </tr>
          </THead>
          <tbody>
            {signals.map((s) => {
              const strategy = String(s.meta?.strategy ?? "?");
              return (
                <TR key={s.signal_id}>
                  <TD className="text-xs text-muted-foreground whitespace-nowrap">
                    {fmtDateTime(s.created_at)}
                  </TD>
                  <TD className="font-medium">{s.symbol}</TD>
                  <TD>
                    <Badge
                      variant={
                        s.side === "buy"
                          ? "buy"
                          : s.side === "sell"
                            ? "sell"
                            : "muted"
                      }
                    >
                      {s.side.toUpperCase()}
                    </Badge>
                  </TD>
                  <TD className="text-xs">{strategy}</TD>
                  <TD align="right" mono>
                    {(Number(s.size_pct) * 100).toFixed(2)}%
                  </TD>
                  <TD align="right" mono>
                    {Number(s.confidence).toFixed(2)}
                  </TD>
                  <TD>
                    {s.rejected_by_risk ? (
                      <Badge variant="rejected">risk reject</Badge>
                    ) : (
                      <Badge variant="info">passed</Badge>
                    )}
                  </TD>
                  <TD
                    className="text-xs text-muted-foreground max-w-md truncate"
                    title={s.rejected_by_risk ? (s.reject_reason ?? undefined) : (s.reasoning ?? undefined)}
                  >
                    {s.rejected_by_risk
                      ? `❌ ${s.reject_reason ?? "rejected"}`
                      : (s.reasoning ?? "-")}
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
