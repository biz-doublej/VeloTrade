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

interface Alert {
  alert_id: string;
  alert_type: string;
  level: "info" | "warn" | "error" | "trade";
  symbol: string | null;
  title: string;
  body: string | null;
  meta: Record<string, unknown>;
  delivered_via: string[] | null;
  created_at: string;
}

function levelVariant(level: Alert["level"]) {
  switch (level) {
    case "info":
      return "info" as const;
    case "warn":
      return "warn" as const;
    case "error":
      return "rejected" as const;
    case "trade":
      return "buy" as const;
  }
}

const LEVEL_EMOJI: Record<Alert["level"], string> = {
  info: "ℹ️",
  warn: "⚠️",
  error: "🛑",
  trade: "💱",
};

export default async function AlertsPage() {
  const { data, error } = await supabaseVt
    .from("alerts")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(100);

  const alerts = (data || []) as Alert[];

  // 레벨별 카운트
  const counts = alerts.reduce(
    (acc, a) => {
      acc[a.level] = (acc[a.level] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  return (
    <>
      <PageHeader
        title="Alerts"
        description={
          alerts.length === 0
            ? "봇 lifecycle / 주문 / risk reject / 이벤트 로그"
            : `최근 ${alerts.length}건 — info ${counts.info ?? 0} · warn ${counts.warn ?? 0} · error ${counts.error ?? 0} · trade ${counts.trade ?? 0}`
        }
      />

      <div className="mb-6 rounded-lg border border-border bg-card/30 p-4 text-sm">
        <h3 className="font-medium mb-2">📡 Webhook 채널 설정</h3>
        <p className="text-muted-foreground text-xs leading-relaxed">
          봇의 외부 알림은 <code className="font-mono px-1 bg-muted rounded">trading/.env</code>{" "}
          의 <code className="font-mono px-1 bg-muted rounded">DISCORD_WEBHOOK_URL</code> /{" "}
          <code className="font-mono px-1 bg-muted rounded">SLACK_WEBHOOK_URL</code> 로 제어합니다.
          <br />
          - Discord: 채널 설정 → Integrations → Webhooks → New Webhook → URL 복사
          <br />
          - Slack: <code className="font-mono">https://api.slack.com/messaging/webhooks</code>
          <br />- 둘 다 미설정 시 stdout 으로만 출력 (DB 기록은 항상 됨)
        </p>
      </div>

      {error ? (
        <EmptyState message={`error: ${error.message}`} />
      ) : alerts.length === 0 ? (
        <EmptyState message="알림 없음 — 봇 실행 시 자동 기록됩니다." />
      ) : (
        <DataTable>
          <THead>
            <tr>
              <TH>Time</TH>
              <TH>Level</TH>
              <TH>Type</TH>
              <TH>Symbol</TH>
              <TH>Title</TH>
              <TH>Body</TH>
            </tr>
          </THead>
          <tbody>
            {alerts.map((a) => (
              <TR key={a.alert_id}>
                <TD className="text-xs text-muted-foreground whitespace-nowrap">
                  {fmtDateTime(a.created_at)}
                </TD>
                <TD>
                  <Badge variant={levelVariant(a.level)}>
                    {LEVEL_EMOJI[a.level]} {a.level}
                  </Badge>
                </TD>
                <TD className="text-xs text-muted-foreground">{a.alert_type}</TD>
                <TD className="font-medium text-xs">{a.symbol ?? "—"}</TD>
                <TD className="text-sm max-w-md truncate" title={a.title}>
                  {a.title}
                </TD>
                <TD
                  className="text-xs text-muted-foreground max-w-md truncate"
                  title={a.body ?? undefined}
                >
                  {a.body ?? ""}
                </TD>
              </TR>
            ))}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
