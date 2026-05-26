"""LLM 시그널 전략 — VeloTrade RAG 분석 결과를 매매 신호로 변환.

핵심 차별화: 가격 지표가 아닌 "공시/뉴스 이벤트 + RAG 답변"을 트리거로 사용.

플로우:
  1. web/ (Next.js) 또는 crawler/ 가 새 이벤트 감지 → vt.query_logs 또는 vt.events 에 저장.
  2. 봇은 on_event(event, ctx) 를 통해 이벤트를 받음.
  3. LLM 에 정형 프롬프트로 의견 요청 → JSON 응답 (side/size_pct/confidence/reasoning).
  4. 응답을 Signal 로 래핑.

지금 단계(Day 1)는 LLM 호출을 stub 으로 두고 인터페이스만 확정. 실제 RAG 연동은 Day 11.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import httpx

from velotrade_trading.core.types import Quote, Signal
from velotrade_trading.strategies.base import Strategy, StrategyContext


SYSTEM_PROMPT = """You are a careful financial assistant for the VeloTrade user's personal
auto-trading bot. Given a market event and a watchlist symbol, output ONLY JSON with keys:
  side: "buy" | "sell" | "hold"
  size_pct: 0.0 to 0.10
  confidence: 0.0 to 1.0
  reasoning: <= 200 chars, English
Be conservative. Default to "hold" if the event is ambiguous or off-topic.
NEVER recommend size_pct > 0.10 or confidence > 0.9.
"""


class LLMSignalStrategy(Strategy):
    name = "llm_signal"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        p = self.params
        self.provider: str = p.get("provider", "openai")  # 'openai' | 'gemini'
        self.model: str = p.get(
            "model",
            "gpt-4o-mini" if self.provider == "openai" else "gemini-1.5-flash",
        )
        self.symbols: list[str] = list(p.get("symbols", []))
        self.max_size_pct: Decimal = Decimal(str(p.get("max_size_pct", "0.05")))
        self.min_confidence: float = float(p.get("min_confidence", 0.6))

    # --- on_quote: tick 으로는 시그널 안 냄 (이벤트 기반) ---------------------

    async def on_quote(self, quote: Quote, ctx: StrategyContext) -> Signal | None:
        return None

    # --- on_event: VeloTrade RAG 이벤트 ---------------------------------------

    async def on_event(
        self, event: dict[str, Any], ctx: StrategyContext
    ) -> Signal | None:
        """event 예시:
        {
            "symbol": "AAPL",
            "title": "Apple beats Q2 estimates...",
            "summary": "...",
            "rag_answer": "...",     # VeloTrade RAG 결과
            "sources": [...],        # 근거 url
            "category": "earnings"
        }
        """
        symbol = event.get("symbol")
        if not symbol or (self.symbols and symbol not in self.symbols):
            return None

        try:
            parsed = await self._ask_llm(event)
        except Exception as e:
            return self._signal(
                symbol=symbol,
                side="hold",
                size_pct=Decimal(0),
                confidence=0.0,
                reasoning=f"LLM error: {e!r}",
                meta={"error": True},
            )

        side = parsed.get("side", "hold")
        if side == "hold":
            return None

        confidence = float(parsed.get("confidence", 0.0))
        if confidence < self.min_confidence:
            return None

        size_pct = min(Decimal(str(parsed.get("size_pct", 0.0))), self.max_size_pct)
        if size_pct <= 0:
            return None

        return self._signal(
            symbol=symbol,
            side=side,
            size_pct=size_pct,
            confidence=confidence,
            reasoning=str(parsed.get("reasoning", ""))[:200],
            meta={
                "event_category": event.get("category"),
                "sources": event.get("sources", []),
                "llm_provider": self.provider,
                "llm_model": self.model,
            },
        )

    # --- LLM 호출 -----------------------------------------------------------

    async def _ask_llm(self, event: dict[str, Any]) -> dict[str, Any]:
        if self.provider == "openai":
            return await self._ask_openai(event)
        if self.provider == "gemini":
            return await self._ask_gemini(event)
        raise RuntimeError(f"unknown provider: {self.provider}")

    async def _ask_openai(self, event: dict[str, Any]) -> dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY missing")
        user_content = json.dumps(event, ensure_ascii=False)[:6000]
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)

    async def _ask_gemini(self, event: dict[str, Any]) -> dict[str, Any]:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY missing")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={api_key}"
        )
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                url,
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": json.dumps(event, ensure_ascii=False)[:6000]}
                            ],
                        }
                    ],
                    "generationConfig": {
                        "response_mime_type": "application/json",
                        "temperature": 0.2,
                    },
                },
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
