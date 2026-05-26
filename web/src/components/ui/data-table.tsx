import { cn } from "@/lib/utils";

export function DataTable({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <table className={cn("w-full text-sm", className)}>{children}</table>
    </div>
  );
}

export function THead({ children }: { children: React.ReactNode }) {
  return (
    <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
      {children}
    </thead>
  );
}

export function TH({
  children,
  className,
  align = "left",
}: {
  children: React.ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      className={cn(
        "px-4 py-2.5 font-medium",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TR({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <tr className={cn("border-t border-border/50 hover:bg-muted/20", className)}>
      {children}
    </tr>
  );
}

export function TD({
  children,
  className,
  align = "left",
  mono = false,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
  mono?: boolean;
  title?: string;
}) {
  return (
    <td
      className={cn(
        "px-4 py-2.5",
        align === "right" && "text-right tabular-nums",
        align === "center" && "text-center",
        mono && "font-mono",
        className,
      )}
      title={title}
    >
      {children}
    </td>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}
