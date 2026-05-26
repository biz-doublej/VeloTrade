/**
 * Supabase auth (cookies 기반) — Server Components / Server Actions / Route Handlers.
 *
 * service_role (server.ts) 와는 별도 client.
 * 이 client 는 사용자 세션 쿠키를 읽고 auth.getUser() 등을 호출하기 위한 용도.
 * RLS 우회 안 함 — anon key 사용.
 */
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";
import "server-only";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url) throw new Error("NEXT_PUBLIC_SUPABASE_URL is required");
if (!anonKey) throw new Error("NEXT_PUBLIC_SUPABASE_ANON_KEY is required");

/**
 * Server Component / Server Action 용.
 * 매 요청마다 cookies() 새로 가져옴.
 */
export function createAuthClient() {
  const cookieStore = cookies();
  return createServerClient(url!, anonKey!, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }: { name: string; value: string; options: CookieOptions }) =>
            cookieStore.set(name, value, options),
          );
        } catch {
          // Server Component 에서는 set 불가 — middleware 가 처리.
        }
      },
    },
  });
}
