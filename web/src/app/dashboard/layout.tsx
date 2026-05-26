import Link from "next/link";
import { SidebarNav } from "@/components/sidebar-nav";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex">
      <aside className="w-56 border-r border-border bg-card/30 px-4 py-6 flex flex-col gap-6">
        <Link href="/" className="flex items-center gap-2 px-3">
          <span className="text-lg font-bold tracking-tight">VeloTrade</span>
        </Link>
        <SidebarNav />
        <div className="mt-auto px-3 text-xs text-muted-foreground">
          dev · {new Date().getFullYear()}
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <div className="px-8 py-6 max-w-7xl mx-auto">{children}</div>
      </main>
    </div>
  );
}
