import { Badge } from "@/components/ui/badge";
import type { Liveness, TrainingRun } from "@/lib/training";

export function RunStatusBadge({ status }: { status: TrainingRun["status"] }) {
  const v =
    status === "RUNNING"
      ? "info"
      : status === "COMPLETED"
        ? "filled"
        : status === "FAILED"
          ? "rejected"
          : status === "INTERRUPTED"
            ? "warn"
            : "muted";
  return <Badge variant={v}>{status}</Badge>;
}

export function LivenessBadge({ state }: { state: Liveness }) {
  if (state === "ENDED") return null;
  const v = state === "LIVE" ? "filled" : state === "DELAYED" ? "warn" : "rejected";
  return <Badge variant={v}>{state}</Badge>;
}

export function ProgressBar({ value }: { value: number | null }) {
  const pct = value === null ? null : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="h-2 flex-1 rounded bg-muted overflow-hidden">
        <div className="h-full bg-sky-500" style={{ width: `${pct ?? 0}%` }} />
      </div>
      <span className="text-xs font-mono tabular-nums text-muted-foreground w-12 text-right">
        {pct === null ? "-" : `${pct.toFixed(1)}%`}
      </span>
    </div>
  );
}
