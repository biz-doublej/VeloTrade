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

export const revalidate = 30;

interface Document {
  doc_id: string;
  url: string;
  title: string | null;
  published_at: string | null;
  lang: string;
  raw_text_min: string | null;
  entity_tags: {
    source?: string;
    category?: string;
    symbol?: string;
  };
  fetched_at: string;
}

function sourceVariant(source: string | undefined) {
  switch (source) {
    case "dart":
      return "warn" as const;
    case "naver_news":
      return "info" as const;
    case "crawler":
      return "muted" as const;
    default:
      return "default" as const;
  }
}

export default async function EventsPage() {
  const { data, error } = await supabaseVt
    .from("documents")
    .select("*")
    .order("fetched_at", { ascending: false })
    .limit(100);

  const events = (data || []) as Document[];

  const sources = new Map<string, number>();
  events.forEach((e) => {
    const s = e.entity_tags?.source || "other";
    sources.set(s, (sources.get(s) || 0) + 1);
  });

  return (
    <>
      <PageHeader
        title="Events"
        description={
          events.length === 0
            ? "DART 공시 + 네이버 뉴스 + 매크로 이벤트 (LLM 시그널 트리거)"
            : `최근 ${events.length}건 — ${Array.from(sources.entries()).map(([s, n]) => `${s}: ${n}`).join(" · ")}`
        }
      />

      <div className="mb-6 rounded-lg border border-border bg-card/30 p-4 text-sm">
        <h3 className="font-medium mb-2">📡 이벤트 폴러 실행</h3>
        <pre className="text-xs text-muted-foreground font-mono leading-relaxed bg-background border border-border rounded p-3">
{`# trading/.env 에 DART_API_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 설정 후:
python -m velotrade_trading events --interval 300

# 봇이 같이 돌고 있으면 새 이벤트는 LLM signal strategy 가 받아
# 자동으로 매매 시그널 생성 → RiskManager → paper 주문.`}
        </pre>
      </div>

      {error ? (
        <EmptyState message={`error: ${error.message}`} />
      ) : events.length === 0 ? (
        <EmptyState message="이벤트 없음 — events 폴러를 실행하면 자동 채워집니다." />
      ) : (
        <DataTable>
          <THead>
            <tr>
              <TH>Published</TH>
              <TH>Source</TH>
              <TH>Category</TH>
              <TH>Symbol</TH>
              <TH>Title</TH>
              <TH>Link</TH>
            </tr>
          </THead>
          <tbody>
            {events.map((e) => {
              const tags = e.entity_tags || {};
              return (
                <TR key={e.doc_id}>
                  <TD className="text-xs text-muted-foreground whitespace-nowrap">
                    {fmtDateTime(e.published_at)}
                  </TD>
                  <TD>
                    <Badge variant={sourceVariant(tags.source)}>
                      {tags.source ?? "?"}
                    </Badge>
                  </TD>
                  <TD className="text-xs text-muted-foreground">
                    {tags.category ?? "—"}
                  </TD>
                  <TD className="font-medium text-xs">{tags.symbol ?? "—"}</TD>
                  <TD
                    className="text-sm max-w-md truncate"
                    title={e.raw_text_min ?? undefined}
                  >
                    {e.title ?? "(no title)"}
                  </TD>
                  <TD>
                    {e.url ? (
                      <a
                        href={e.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-sky-400 hover:underline"
                      >
                        ↗ open
                      </a>
                    ) : (
                      "—"
                    )}
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
