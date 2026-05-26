import Link from "next/link";
import { SidebarNav } from "@/components/sidebar-nav";
import { createAuthClient } from "@/lib/supabase/server-auth";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = createAuthClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <div className="min-h-screen flex">
      <aside className="w-56 border-r border-border bg-card/30 px-4 py-6 flex flex-col gap-6">
        <Link href="/" className="flex items-center gap-2 px-3">
          <span className="text-lg font-bold tracking-tight">VeloTrade</span>
        </Link>
        <SidebarNav />

        <div className="mt-auto px-3 flex flex-col gap-2">
          {user ? (
            <>
              <div
                className="text-xs text-muted-foreground truncate"
                title={user.email ?? undefined}
              >
                {user.email}
              </div>
              <form action="/auth/logout" method="POST">
                <button
                  type="submit"
                  className="w-full text-left text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                >
                  Sign out →
                </button>
              </form>
            </>
          ) : (
            <Link
              href="/login"
              className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
            >
              Sign in →
            </Link>
          )}
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <div className="px-8 py-6 max-w-7xl mx-auto">{children}</div>
      </main>
    </div>
  );
}
