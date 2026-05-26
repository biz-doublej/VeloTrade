import { cn } from "@/lib/utils";

type Variant =
  | "default"
  | "buy"
  | "sell"
  | "filled"
  | "submitted"
  | "cancelled"
  | "rejected"
  | "warn"
  | "info"
  | "muted";

const VARIANT_CLASS: Record<Variant, string> = {
  default: "bg-secondary text-secondary-foreground",
  buy: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  sell: "bg-rose-500/15 text-rose-400 border border-rose-500/30",
  filled: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  submitted: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  cancelled: "bg-zinc-500/20 text-zinc-300 border border-zinc-500/30",
  rejected: "bg-rose-500/15 text-rose-400 border border-rose-500/30",
  warn: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  info: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  muted: "bg-muted text-muted-foreground",
};

export function Badge({
  children,
  variant = "default",
  className,
}: {
  children: React.ReactNode;
  variant?: Variant;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-md",
        VARIANT_CLASS[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
