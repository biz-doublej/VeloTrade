import Link from "next/link";
import { AutoRefresh } from "@/components/training/auto-refresh";
import {
  LivenessBadge,
  ProgressBar,
  RunStatusBadge,
} from "@/components/training/status-badge";
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
import {
  fmtAge,
  fmtMetric,
  liveness,
  type TrainingRun,
} from "@/lib/training";
import { requireTrainingViewer } from "@/lib/training-auth";

export const dynamic = "force-dynamic";

const ORDER: Record<string, number> = { RUNNING: 0, PENDING: 1, FAILED: 2, INTERRUPTED: 3, COMPLETED: 4, CANCELLED: 5 };

export default async function TrainingRunsPage() {
  const { supabase } = await requireTrainingViewer();
  const { data, error } = await supabase
    .schema("vt")
    .from("training_runs")
    .select("*")
    .order("updated_at", { ascending: false })
    .limit(50);

  const now = Date.now();
  const runs = ((data || []) as TrainingRun[]).sort(
    (a, b) =>
      (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9) ||
      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );

  return (
    <>
      <PageHeader
        title="Training"
        description="Remote training monitor — read-only telemetry from the training machine"
        right={<AutoRefresh seconds={20} />}
      />

      {error ? (
        <EmptyState
          message={`REMOTE TELEMETRY UNAVAILABLE — ${error.message}. (vt.training_runs 마이그레이션 / vt.admin_users 등록 여부를 확인하세요)`}
        />
      ) : runs.length === 0 ? (
        <EmptyState message="NO ACTIVE REMOTE RUN — 학습 머신에서 아직 telemetry 가 도착하지 않았습니다." />
      ) : (
        <DataTable>
          <THead>
            <tr>
              <TH>Experiment</TH>
              <TH>Status</TH>
              <TH>Progress</TH>
              <TH align="right">Epoch</TH>
              <TH align="right">Val loss</TH>
              <TH align="right">Macro F1</TH>
              <TH>GPU</TH>
              <TH>Started</TH>
              <TH>Heartbeat</TH>
            </tr>
          </THead>
          <tbody>
            {runs.map((r) => {
              const lv = liveness(r, now);
              return (
                <TR key={r.id}>
                  <TD>
                    <Link
                      href={`/training/${encodeURIComponent(r.run_id)}`}
                      className="font-medium hover:underline"
                    >
                      {r.experiment_name ?? r.run_id}
                    </Link>
                    <div className="text-[11px] text-muted-foreground font-mono">
                      {r.model_name ?? "-"} · {r.run_id}
                    </div>
                  </TD>
                  <TD>
                    <div className="flex gap-1.5 flex-wrap">
                      <RunStatusBadge status={r.status} />
                      <LivenessBadge state={lv.state} />
                    </div>
                  </TD>
                  <TD>
                    <ProgressBar value={r.progress} />
                  </TD>
                  <TD align="right" mono>
                    {r.current_epoch ?? "-"} / {r.total_epochs ?? "-"}
                  </TD>
                  <TD align="right" mono>{fmtMetric(r.val_loss)}</TD>
                  <TD align="right" mono>{fmtMetric(r.macro_f1)}</TD>
                  <TD className="text-xs text-muted-foreground">{r.gpu_name ?? "-"}</TD>
                  <TD className="text-xs text-muted-foreground whitespace-nowrap">
                    {fmtDateTime(r.started_at)}
                  </TD>
                  <TD className="text-xs whitespace-nowrap">{fmtAge(lv.ageSec)}</TD>
                </TR>
              );
            })}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
