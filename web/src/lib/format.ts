/**
 * 화면 표시용 포맷 헬퍼.
 * 금액은 통화별 다르게 (USD/USDT $, KRW ₩, 그 외 prefix 없음).
 */

export function fmtNumber(
  v: number | string | null | undefined,
  decimals = 2,
): string {
  if (v === null || v === undefined) return "-";
  const n = typeof v === "string" ? Number(v) : v;
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function fmtCurrency(
  v: number | string | null | undefined,
  currency = "USD",
  decimals?: number,
): string {
  if (v === null || v === undefined) return "-";
  const n = typeof v === "string" ? Number(v) : v;
  if (Number.isNaN(n)) return String(v);
  const dp = decimals ?? (currency === "KRW" ? 0 : 2);
  const symbol = currency === "USD" || currency === "USDT" ? "$" : currency === "KRW" ? "₩" : "";
  return `${symbol}${n.toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })}`;
}

export function fmtPct(v: number | string | null | undefined, decimals = 2): string {
  if (v === null || v === undefined) return "-";
  const n = typeof v === "string" ? Number(v) : v;
  if (Number.isNaN(n)) return String(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(decimals)}%`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("ko-KR", {
      year: "2-digit",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("en-CA"); // YYYY-MM-DD
  } catch {
    return iso;
  }
}

/** 부호에 따라 emerald/rose 색상. neutral 은 muted. */
export function pnlColor(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  const n = typeof v === "string" ? Number(v) : v;
  if (Number.isNaN(n) || n === 0) return "text-muted-foreground";
  return n > 0 ? "text-emerald-400" : "text-rose-400";
}
