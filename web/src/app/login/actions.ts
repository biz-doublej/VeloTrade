"use server";

import { headers } from "next/headers";
import { createAuthClient } from "@/lib/supabase/server-auth";

export async function sendMagicLink(formData: FormData) {
  const email = String(formData.get("email") || "").trim().toLowerCase();
  if (!email) return { error: "email required" };

  const allowed = (process.env.ALLOWED_EMAIL || "")
    .toLowerCase()
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  if (allowed.length > 0 && !allowed.includes(email)) {
    // 보안: 허용 안 된 이메일도 generic 에러로
    return { error: "this email is not authorized for this instance" };
  }

  const headersList = headers();
  const host = headersList.get("host") || "localhost:3000";
  const proto = headersList.get("x-forwarded-proto") || "http";
  const origin = `${proto}://${host}`;

  const supabase = createAuthClient();
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${origin}/auth/callback` },
  });

  if (error) return { error: error.message };
  return { sent: true };
}
