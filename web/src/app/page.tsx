import Link from "next/link";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center gap-6 px-6 text-center">
      <div>
        <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
          Hello VeloTrade
        </h1>
        <p className="mt-2 text-muted-foreground text-base sm:text-lg">
          한국·미국 주식 데이터 분석 서비스 — 14일 MVP
        </p>
      </div>
      <Link
        href="/dashboard/positions"
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
      >
        Dashboard →
      </Link>
    </main>
  );
}
