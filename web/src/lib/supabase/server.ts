/**
 * Supabase server-side 클라이언트 (Server Components / Route Handlers 전용).
 *
 * service_role 키 사용 → vt 스키마 자유 접근.
 * 브라우저로 절대 노출 금지 — server-only 모듈에서만 import.
 */
import { createClient } from "@supabase/supabase-js";
import "server-only";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!url) throw new Error("NEXT_PUBLIC_SUPABASE_URL is required");
if (!serviceRoleKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY is required");

/** vt 스키마 전용 client (Python trading bot 과 같은 데이터 영역). */
export const supabaseVt = createClient(url, serviceRoleKey, {
  db: { schema: "vt" },
  auth: { persistSession: false, autoRefreshToken: false },
});

/** public 스키마 (auth, 사용자 데이터 등). */
export const supabasePublic = createClient(url, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});
