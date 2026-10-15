/**
 * Training monitor 공용 타입/헬퍼. 읽기 전용 — 어떤 실행/주문 기능도 없다.
 */
import "server-only";

export interface TrainingRun {
  id: string;
  run_id: string;
  experiment_name: string | null;
  model_name: string | null;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "INTERRUPTED" | "CANCELLED";
  hostname: string | null;
  gpu_name: string | null;
  started_at: string | null;
  updated_at: string;
  finished_at: string | null;
  current_epoch: number | null;
  total_epochs: number | null;
  current_step: number | null;
  total_steps: number | null;
  progress: number | null;
  train_loss: number | null;
  val_loss: number | null;
  accuracy: number | null;
  macro_f1: number | null;
  mae: number | null;
  rmse: number | null;
  spearman_ic: number | null;
  learning_rate: number | null;
  gpu_utilization: number | null;
  gpu_memory_used_mb: number | null;
  gpu_memory_total_mb: number | null;
  elapsed_seconds: number | null;
  checkpoint_path: string | null;
  log_tail: string | null;
  error_message: string | null;
  git_commit: string | null;
}

export interface MetricRow {
  epoch: number | null;
  step: number | null;
  split: string;
  metric_name: string;
  metric_value: number;
  timestamp: string;
}

export type Liveness = "LIVE" | "DELAYED" | "STALE" | "ENDED";

/** heartbeat 나이로 상태 판단: <2m LIVE, 2~5m DELAYED, >5m STALE. 종료된 run 은 ENDED. */
export function liveness(run: TrainingRun, nowMs: number): { state: Liveness; ageSec: number } {
  const ageSec = Math.max(0, Math.round((nowMs - new Date(run.updated_at).getTime()) / 1000));
  if (run.status !== "RUNNING" && run.status !== "PENDING") return { state: "ENDED", ageSec };
  if (ageSec < 120) return { state: "LIVE", ageSec };
  if (ageSec < 300) return { state: "DELAYED", ageSec };
  return { state: "STALE", ageSec };
}

export function fmtDuration(totalSec: number | null | undefined): string {
  if (totalSec === null || totalSec === undefined || Number.isNaN(totalSec)) return "-";
  const s = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return [h, m, sec].map((v) => String(v).padStart(2, "0")).join(":");
}

export function fmtAge(sec: number): string {
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m ago`;
}

/** 진행률/경과 시간 기반 ETA (추정치). 데이터 부족 시 null. */
export function estimateRemainingSec(run: TrainingRun): number | null {
  const p = run.progress;
  const el = run.elapsed_seconds;
  if (p === null || el === null || p < 0.02 || p >= 1 || el < 60) return null;
  return Math.round((el * (1 - p)) / p);
}

export function num(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = typeof v === "string" ? Number(v) : v;
  return Number.isFinite(n) ? n : null;
}

export function fmtMetric(v: number | null | undefined, digits = 4): string {
  const n = num(v);
  return n === null ? "-" : n.toFixed(digits);
}
