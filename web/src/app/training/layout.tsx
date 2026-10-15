import Link from "next/link";
import { SidebarNav } from "@/components/sidebar-nav";
import { requireTrainingViewer } from "@/lib/training-auth";

export const dynamic = "force-dynamic";

export default async function TrainingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user } = await requireTrainingViewer();

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      <aside className="md:w-56 border-b md:border-b-0 md:border-r border-border bg-card/30 px-4 py-4 md:py-6 flex md:flex-col gap-4 md:gap-6 items-center md:items-stretch overflow-x-auto">
        <Link href="/" className="flex items-center gap-2 px-3">
          <span className="text-lg font-bold tracking-tight">VeloTrade</span>
        </Link>
        <div className="hidden md:block">
          <SidebarNav />
        </div>
        <div className="md:mt-auto px-3 flex md:flex-col gap-2 items-center md:items-start ml-auto md:ml-0">
          <div className="text-xs text-muted-foreground truncate max-w-[160px]" title={user.email ?? undefined}>
            {user.email}
          </div>
          <form action="/auth/logout" method="POST">
            <button type="submit" className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline">
              Sign out →
            </button>
          </form>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="px-4 md:px-8 py-6 max-w-7xl mx-auto">{children}</div>
      </main>
    </div>
  );
}
