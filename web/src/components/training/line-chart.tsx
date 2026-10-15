/**
 * 의존성 없는 SVG 라인 차트 (server-renderable).
 * null/NaN 값은 0 으로 그리지 않고 건너뛴다.
 */
export interface Series {
  label: string;
  color: string;
  points: { x: number; y: number | null }[];
}

export function LineChart({
  title,
  series,
  xLabel,
  height = 150,
}: {
  title: string;
  series: Series[];
  xLabel: string;
  height?: number;
}) {
  const W = 360;
  const H = height;
  const pad = { l: 44, r: 10, t: 10, b: 22 };
  const all = series.flatMap((s) =>
    s.points.filter((p) => p.y !== null && Number.isFinite(p.y)),
  ) as { x: number; y: number }[];

  if (all.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card/30 p-3">
        <div className="text-xs font-medium text-muted-foreground mb-2">{title}</div>
        <div className="text-xs text-muted-foreground py-8 text-center">No data yet</div>
      </div>
    );
  }
  const xs = all.map((p) => p.x);
  const ys = all.map((p) => p.y);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  let y0 = Math.min(...ys);
  let y1 = Math.max(...ys);
  if (y0 === y1) {
    y0 -= 0.5;
    y1 += 0.5;
  }
  const sx = (x: number) =>
    pad.l + (x1 === x0 ? 0.5 : (x - x0) / (x1 - x0)) * (W - pad.l - pad.r);
  const sy = (y: number) => H - pad.b - ((y - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  const fmt = (v: number) =>
    Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toPrecision(2);

  return (
    <div className="rounded-lg border border-border bg-card/30 p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-muted-foreground">{title}</span>
        <span className="flex gap-3 text-[11px]">
          {series.map((s) => (
            <span key={s.label} className="flex items-center gap-1 text-muted-foreground">
              <i className="inline-block w-2 h-2 rounded-sm" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={title}>
        {[0, 0.5, 1].map((t) => {
          const y = pad.t + t * (H - pad.t - pad.b);
          const v = y1 - t * (y1 - y0);
          return (
            <g key={t}>
              <line x1={pad.l} x2={W - pad.r} y1={y} y2={y} stroke="currentColor" opacity={0.12} />
              <text x={pad.l - 6} y={y + 3} textAnchor="end" fontSize="9" fill="currentColor" opacity={0.6}>
                {fmt(v)}
              </text>
            </g>
          );
        })}
        <text x={W / 2} y={H - 4} textAnchor="middle" fontSize="9" fill="currentColor" opacity={0.6}>
          {xLabel} {x0 === x1 ? x0 : `${x0} → ${x1}`}
        </text>
        {series.map((s) => {
          const pts = s.points.filter((p) => p.y !== null && Number.isFinite(p.y)) as {
            x: number;
            y: number;
          }[];
          if (pts.length === 0) return null;
          const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");
          return (
            <g key={s.label}>
              <path d={d} fill="none" stroke={s.color} strokeWidth={1.8} />
              {pts.length <= 40 &&
                pts.map((p, i) => (
                  <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={2.2} fill={s.color} />
                ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
