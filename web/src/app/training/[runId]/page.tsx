import Link from "next/link";
import { notFound } from "next/navigation";
import { AutoRefresh } from "@/components/training/auto-refresh";
import { LineChart, type Series } from "@/components/training/line-chart";
import {
  LivenessBadge,
  ProgressBar,
  RunStatusBadge,
} from "@/components/training/status-badge";
import { EmptyState } from "@/components/ui/data-table";
import { fmtDateTime } from "@/lib/format";
import {
  estimateRemainingSec,
  fmtAge,
  fmtDuration,
  fmtMetric,
  liveness,
  num,
  type MetricRow,
  type TrainingRun,
} from "@/lib/training";
import { requireTrainingViewer } from "@/lib/training-auth";

export const dynamic = "force-dynamic";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card/30 p-4">
      <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-3">
        {title}
      </h2>
      {children}
    </section>
  );
}

function KV({ k, v, mono = true }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="text-muted-foreground">{k}</span>
      <span className={mono ? "font-mono tabular-nums" : ""}>{v}</span>
    </div>
  );
}

function seriesOf(rows: MetricRow[], split: string, name: string, xKey: "epoch" | "step"): Series["points"] {
  return rows
    .filter((r) => r.split === split && r.metric_name === name)
    .map((r) => ({ x: Number(r[xKey] ?? 0), y: num(r.metric_value) }));
}

function downsample<T>(arr: T[], max = 200): T[] {
  if (arr.length <= max) return arr;
  const step = arr.length / max;
  return Array.from({ length: max }, (_, i) => arr[Math.floor(i * step)]);
}

export default async function TrainingDetailPage({
  params,
}: {
  params: { runId: string };
}) {
  const { supabase } = await requireTrainingViewer();
  const runId = decodeURIComponent(params.runId);

  const { data: runData, error } = await supabase
    .schema("vt")
    .from("training_runs")
    .select("*")
    .eq("run_id", runId)
    .maybeSingle();

  if (error) {
    return <EmptyState message={`REMOTE TELEMETRY UNAVAILABLE — ${error.message}`} />;
  }
  if (!runData) notFound();
  const run = runData as TrainingRun;

  const { data: m } = await supabase
    .schema("vt")
    .from("training_metrics")
    .select("epoch, step, split, metric_name, metric_value, timestamp")
    .eq("run_id", runId)
    .order("timestamp", { ascending: true })
    .limit(3000);
  const metrics = (m || []) as MetricRow[];

  const lv = liveness(run, Date.now());
  const eta = run.status === "RUNNING" ? estimateRemainingSec(run) : null;
  const vramPct =
    run.gpu_memory_used_mb !== null && run.gpu_memory_total_mb
      ? (run.gpu_memory_used_mb / run.gpu_memory_total_mb) * 100
      : null;
  const gb = (mb: number | null) => (mb === null ? "-" : (mb / 1024).toFixed(1));

  const trainLoss = downsample(seriesOf(metrics, "train", "train_loss", "step"));
  const valLoss = seriesOf(metrics, "val", "val_loss", "epoch");
  const f1 = seriesOf(metrics, "val", "macro_f1", "epoch");
  const ic = seriesOf(metrics, "val", "spearman_ic", "epoch");
  const acc = seriesOf(metrics, "val", "accuracy", "epoch");

  return (
    <>
      <div className="mb-2 text-xs">
        <Link href="/training" className="text-muted-foreground hover:text-foreground">
          ← Training runs
        </Link>
      </div>

      {/* Header / status / progress */}
      <header className="mb-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {run.experiment_name ?? run.run_id}
            </h1>
            <div className="mt-1 text-xs text-muted-foreground font-mono">
              {run.model_name ?? "-"} · {run.run_id}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <RunStatusBadge status={run.status} />
            <LivenessBadge state={lv.state} />
            <AutoRefresh seconds={15} />
          </div>
        </div>
        <div className="mt-4 max-w-xl">
          <ProgressBar value={run.progress} />
        </div>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span>
            Epoch <b className="font-mono">{run.current_epoch ?? "-"} / {run.total_epochs ?? "-"}</b>
          </span>
          <span>
            Step{" "}
            <b className="font-mono">
              {run.current_step?.toLocaleString() ?? "-"} / {run.total_steps?.toLocaleString() ?? "-"}
            </b>
          </span>
          <span>
            Elapsed <b className="font-mono">{fmtDuration(run.elapsed_seconds)}</b>
          </span>
          <span>
            ETA{" "}
            <b className="font-mono">
              {eta === null ? "-" : `~${fmtDuration(eta)}`}
            </b>{" "}
            {eta !== null ? <i className="text-xs text-muted-foreground">(estimated)</i> : null}
          </span>
          <span>
            Last heartbeat <b className="font-mono">{fmtAge(lv.ageSec)}</b>
          </span>
        </div>
        {lv.state === "STALE" || lv.state === "DELAYED" ? (
          <p className="mt-2 text-xs text-amber-400">
            Heartbeat is {lv.state.toLowerCase()} — the training process may have stopped or lost
            connectivity. Last known values are shown.
          </p>
        ) : null}
      </header>

      {run.status === "FAILED" || run.status === "INTERRUPTED" ? (
        <div className="mb-6 rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-sm">
          <div className="font-medium text-rose-300">
            {run.status} · {fmtDateTime(run.finished_at)}
          </div>
          <div className="mt-1 text-muted-foreground">
            Last epoch: <span className="font-mono">{run.current_epoch ?? "-"}</span> · Last
            checkpoint: <span className="font-mono">{run.checkpoint_path ?? "-"}</span>
          </div>
          {run.error_message ? (
            <pre className="mt-2 whitespace-pre-wrap text-xs text-rose-200/90">{run.error_message}</pre>
          ) : null}
        </div>
      ) : null}

      {/* Cards */}
      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <Card title="GPU">
          <div className="text-sm mb-2">{run.gpu_name ?? "-"}</div>
          <KV k="Utilization" v={run.gpu_utilization === null ? "-" : `${num(run.gpu_utilization)?.toFixed(0)}%`} />
          <KV
            k="VRAM"
            v={`${gb(run.gpu_memory_used_mb)} / ${gb(run.gpu_memory_total_mb)} GB${vramPct === null ? "" : ` (${vramPct.toFixed(0)}%)`}`}
          />
        </Card>
        <Card title="Training">
          <KV k="Learning rate" v={run.learning_rate === null ? "-" : run.learning_rate.toExponential(2)} />
          <KV k="Checkpoint" v={run.checkpoint_path ?? "-"} />
          <KV k="Started" v={fmtDateTime(run.started_at)} mono={false} />
          <KV k="Host" v={run.hostname ?? "-"} mono={false} />
        </Card>
        <Card title="Metrics (latest)">
          <KV k="Train loss" v={fmtMetric(run.train_loss)} />
          <KV k="Validation loss" v={fmtMetric(run.val_loss)} />
          <KV k="Macro F1" v={fmtMetric(run.macro_f1)} />
          <KV k="Accuracy" v={fmtMetric(run.accuracy)} />
          <KV k="MAE" v={fmtMetric(run.mae, 5)} />
          <KV k="RMSE" v={fmtMetric(run.rmse, 5)} />
          <KV k="Spearman IC" v={fmtMetric(run.spearman_ic)} />
        </Card>
      </div>

      {/* Charts */}
      <div className="grid gap-4 md:grid-cols-2 mb-6">
        <LineChart
          title="Loss"
          xLabel="epoch"
          series={[
            { label: "val", color: "#38bdf8", points: valLoss },
          ]}
        />
        <LineChart
          title="Train loss (per log step)"
          xLabel="step"
          series={[{ label: "train", color: "#a78bfa", points: trainLoss }]}
        />
        <LineChart
          title="Macro F1 / Accuracy"
          xLabel="epoch"
          series={[
            { label: "macro F1", color: "#34d399", points: f1 },
            { label: "accuracy", color: "#fbbf24", points: acc },
          ]}
        />
        <LineChart
          title="Spearman IC (val, 3d)"
          xLabel="epoch"
          series={[{ label: "IC", color: "#f472b6", points: ic }]}
        />
      </div>

      {/* Log tail */}
      <Card title="Recent log (sanitized, last lines)">
        {run.log_tail ? (
          <pre className="text-[11px] leading-5 overflow-x-auto text-muted-foreground whitespace-pre-wrap">
            {run.log_tail}
          </pre>
        ) : (
          <div className="text-xs text-muted-foreground">No log lines received.</div>
        )}
      </Card>

      <p className="mt-6 text-[11px] text-muted-foreground">
        Read-only monitor. No training control, order, or trading actions are exposed here.
      </p>
    </>
  );
}
