"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "/dashboard/positions", label: "Positions", emoji: "📊" },
  { href: "/dashboard/orders", label: "Orders", emoji: "📝" },
  { href: "/dashboard/signals", label: "Signals", emoji: "📡" },
  { href: "/dashboard/backtests", label: "Backtests", emoji: "🔬" },
  { href: "/dashboard/watchlist", label: "Watchlist", emoji: "👁️" },
  { href: "/dashboard/strategies", label: "Strategies", emoji: "⚙️" },
];

export function SidebarNav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-1">
      {ITEMS.map((item) => {
        const active = pathname?.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              active
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <span className="text-base">{item.emoji}</span>
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
