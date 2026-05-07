# VeloTrade

한국+미국 주식 데이터 분석 MVP. 14일 출시 목표.

## 모노레포 구조

```
.
├── web/              # Next.js 14 + Supabase 풀스택 (Day 1 추가, 14일 MVP의 메인)
├── crawler/          # Python 크롤러 (자체 호스팅, MVP 이후 통합 검토)
├── training/         # LLaMA QLoRA 학습 (MVP 이후)
├── vectorstore/      # 벡터 저장소 모듈 (MVP 이후)
├── infra/db/         # PostgreSQL/pgvector 스키마 (Supabase 마이그레이션 원본)
└── keywords/         # 크롤링 키워드/쿼리 템플릿 (영문)
```

## 14일 MVP 스코프

### Must
- Next.js 14 + Supabase (Auth, Postgres + pgvector, RLS)
- 한국 시장: DART 공시, 네이버 검색
- 미국 시장: Alpha Vantage, FMP
- LLM 답변: OpenAI 또는 Gemini API
- 사용자 워치리스트 + 질문 → 답변 + 히스토리
- Vercel 자동 배포 + 다크 모드 UI

### Drop (MVP 이후)
- LLaMA 3.1 8B 자체 호스팅 + QLoRA
- Fast Lane 30초 속보 크롤링
- 예측 엔진(50.1% 적중)
- Playwright 동적 크롤링
- 모바일 앱, 다국어, 결제

## 개발 시작 (Day 1 이후)

```powershell
cd web
npm install
npm run dev
# http://localhost:3000
```

`.env.local`은 `web/.env.example`을 복사해 채운다.

## 기획 문서

- `crawler/README.md` — 시스템 전체 기획서 (LLaMA 자체 호스팅 포함, 일부는 Drop)
- `infra/db/init/02_schema.sql` — DB 스키마 (Supabase로 마이그레이션됨)
