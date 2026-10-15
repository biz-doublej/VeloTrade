/**
 * /training 접근 가드 (server-only, fail-closed).
 *
 * 1) 세션 필수
 * 2) ALLOWED_EMAIL 이 비어 있으면 거부 (다른 페이지와 달리 "열려 있음" 이 기본이 아니다)
 * 3) 데이터는 사용자 세션 + RLS(vt.is_admin()) 로 읽는다 — service_role 을 쓰지 않는다.
 */
import { redirect } from "next/navigation";
import "server-only";
import { createAuthClient } from "@/lib/supabase/server-auth";

export async function requireTrainingViewer() {
  const supabase = createAuthClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/training");

  const allowed = (process.env.ALLOWED_EMAIL || "")
    .toLowerCase()
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const email = (user.email || "").toLowerCase();
  if (allowed.length === 0 || !allowed.includes(email)) {
    redirect("/login?error=forbidden");
  }
  return { supabase, user };
}
