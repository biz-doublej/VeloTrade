import Link from "next/link";
import { createAuthClient } from "@/lib/supabase/server-auth";
import { fmtAge, liveness, type TrainingRun } from "@/lib/training";

/** 대시보드 사이드바용 작은 위젯 — 최신 학습 run 1건. 실패/없음이면 아무것도 렌더링하지 않는다. */
export async function TrainingWidget() {
  try {
    const supabase = createAuthClient();
    const { data } = await supabase
      .schema("vt")
      .from("training_runs")
      .select("*")
      .order("updated_at", { ascending: false })
      .limit(1);
    const run = (data?.[0] ?? null) as TrainingRun | null;
    if (!run) return null;
    const lv = liveness(run, Date.now());
    const pct = run.progress === null ? null : Math.round(run.progress * 100);
    return (
      <Link
        href={`/training/${encodeURIComponent(run.run_id)}`}
        className="block rounded-md border border-border px-3 py-2 text-xs hover:bg-muted/40"
      >
        <div className="text-muted-foreground">Model Training</div>
        <div className="font-medium truncate">{run.experiment_name ?? run.run_id}</div>
        <div className="font-mono text-muted-foreground">
          {run.status}
          {pct !== null ? ` · ${pct}%` : ""}
          {run.current_epoch !== null ? ` · Ep ${run.current_epoch}/${run.total_epochs ?? "?"}` : ""}
        </div>
        <div className="text-[11px] text-muted-foreground">
          {lv.state === "ENDED" ? "ended" : lv.state.toLowerCase()} · {fmtAge(lv.ageSec)}
        </div>
      </Link>
    );
  } catch {
    return null;
  }
}
