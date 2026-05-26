import { NextResponse, type NextRequest } from "next/server";
import { createAuthClient } from "@/lib/supabase/server-auth";

/**
 * Supabase Magic link callback.
 * Email 의 링크 → ?code=XXXX → 세션 교환 → /dashboard 로 redirect.
 */
export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  const next = request.nextUrl.searchParams.get("next") || "/dashboard/positions";

  if (code) {
    const supabase = createAuthClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) {
      const url = request.nextUrl.clone();
      url.pathname = "/login";
      url.searchParams.set("error", "auth_exchange_failed");
      url.search = `?error=${encodeURIComponent(error.message)}`;
      return NextResponse.redirect(url);
    }
  }

  return NextResponse.redirect(new URL(next, request.url));
}
