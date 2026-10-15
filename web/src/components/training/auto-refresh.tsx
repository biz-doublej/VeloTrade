"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** 서버 컴포넌트 데이터를 주기적으로 다시 가져온다 (polling; WebSocket 없음). */
export function AutoRefresh({ seconds = 20 }: { seconds?: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, seconds * 1000);
    return () => clearInterval(id);
  }, [router, seconds]);
  return (
    <span className="text-[11px] text-muted-foreground">
      auto-refresh {seconds}s
    </span>
  );
}
