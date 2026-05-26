import Link from "next/link";
import { LoginForm } from "./login-form";

export default function LoginPage() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center gap-6 p-6">
      <Link href="/" className="text-lg font-bold tracking-tight">
        VeloTrade
      </Link>
      <LoginForm />
      <p className="text-xs text-muted-foreground">
        본인 인증된 이메일만 접근 가능합니다.
      </p>
    </main>
  );
}
