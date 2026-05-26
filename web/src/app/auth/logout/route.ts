import { NextResponse, type NextRequest } from "next/server";
import { createAuthClient } from "@/lib/supabase/server-auth";

/** POST/GET /auth/logout — 세션 종료 + /login redirect. */
export async function POST(request: NextRequest) {
  const supabase = createAuthClient();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/login", request.url), { status: 302 });
}

export async function GET(request: NextRequest) {
  return POST(request);
}
