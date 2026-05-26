/**
 * Supabase client-side 클라이언트 (Client Components 전용).
 *
 * anon/publishable key 사용 — 브라우저 노출 OK.
 * Day 6 에선 SSR 위주 — 이 모듈은 추후 realtime 구독 등에 사용.
 */
"use client";

import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabaseBrowser = createClient(url, anonKey, {
  db: { schema: "vt" },
});
