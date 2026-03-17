# 판례 기반 법률 대응 시스템 (Precedent Finder)

> "법령 + 판례 + 크롤링 데이터를 기반으로 AI가 근거를 찾아주는 법률 대응 시스템"

---

## 프로젝트 개요

교육청 고발 대응을 위한 **근거 중심 판례 추천 엔진**.
GPT로 답변을 생성하는 것이 아니라, **관련 판례와 법령 근거를 자동 수집·정렬**하는 시스템.

### 핵심 철학
- ❌ GPT로 답변 생성 → 의미 없음
- ✅ 관련 판례 + 법령 근거 자동 수집 & 정렬

### 목적
1. 형사 사건 대응을 위한 "판례 기반 근거 시스템" 구축
2. 유리/불리 판례를 모두 수집하여 전략적 대응
3. 변호사에게 넘기기 전 "1차 정리 자동화"
4. 정보공개청구 이후 재분석 가능한 구조

---

## 기술 스택

| 영역 | 기술 | 이유 |
|------|------|------|
| **언어** | Python 3.12+ | 크롤링, PDF 파싱, AI 연동 생태계 최강 |
| **API 서버** | FastAPI | 비동기, 자동 문서화, 타입 안전 |
| **DB** | PostgreSQL + pgvector | 관계형 데이터 + 벡터 유사도 검색 통합 |
| **ORM** | SQLAlchemy 2.0 | Python 표준 ORM, async 지원 |
| **크롤링** | Scrapy + BeautifulSoup4 | 대규모 크롤링 + 단순 파싱 |
| **PDF 파싱** | pdfplumber | 법원 판례 PDF 텍스트 추출 |
| **AI (분석)** | OpenAI GPT-4o | 판례 분류, 유불리 판단, 요약 |
| **AI (임베딩)** | OpenAI text-embedding-3-small | 판례/법령 벡터화, 유사도 검색 |
| **태스크 큐** | Celery + Redis | 크롤링/분석 비동기 작업 처리 |
| **CLI** | Typer | 명령줄 인터페이스 |
| **테스트** | pytest | Python 표준 테스트 |
| **패키지 관리** | uv | 빠르고 현대적인 Python 패키지 관리 |

---

## 시스템 아키텍처

```
[데이터 수집]                    [데이터 통합]           [AI 분석]              [결과]
┌─────────────┐
│ 법제처 API   │──┐
│ (법령)       │  │
└─────────────┘  │
┌─────────────┐  │   ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│ 법원 크롤링  │──┼──▶│ PostgreSQL   │──▶│ GPT-4o       │──▶│ 유사 판례         │
│ (판례 PDF)   │  │   │ + pgvector   │   │ 유불리 분류   │   │ 불리 판례         │
└─────────────┘  │   └──────────────┘   └──────────────┘   │ 반박 법 조항      │
┌─────────────┐  │                                          └──────────────────┘
│ 교육청 크롤링│──┤                                                  │
└─────────────┘  │                                                  ▼
┌─────────────┐  │                                          ┌──────────────────┐
│ 뉴스 크롤링  │──┘                                          │ 변호사 리포트     │
└─────────────┘                                             │ (JSON/MD/PDF)    │
                                                            └──────────────────┘
```

---

## 프로젝트 구조

```
precedent-finder/
├── pyproject.toml
├── .env.example
├── alembic/                        # DB 마이그레이션
│   └── versions/
├── src/
│   └── precedent_finder/
│       ├── __init__.py
│       ├── main.py                 # FastAPI 앱 진입점
│       ├── cli.py                  # Typer CLI 진입점
│       ├── config.py               # 설정 관리
│       ├── db/
│       │   ├── __init__.py
│       │   ├── session.py          # DB 세션
│       │   └── models.py           # SQLAlchemy 모델
│       ├── crawlers/
│       │   ├── __init__.py
│       │   ├── base.py             # 크롤러 베이스 클래스
│       │   ├── court.py            # 법원 판례 크롤러
│       │   ├── law_api.py          # 법제처 API 클라이언트
│       │   ├── education.py        # 교육청 공개자료 크롤러
│       │   └── news.py             # 뉴스/기사 크롤러
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── pdf_parser.py       # PDF 판례 파싱
│       │   └── law_parser.py       # 법령 텍스트 파싱
│       ├── ai/
│       │   ├── __init__.py
│       │   ├── embeddings.py       # 임베딩 생성/관리
│       │   ├── analyzer.py         # GPT 기반 판례 분석
│       │   └── prompts.py          # 프롬프트 템플릿
│       ├── search/
│       │   ├── __init__.py
│       │   └── engine.py           # 유사도 검색 엔진
│       ├── api/
│       │   ├── __init__.py
│       │   ├── routes/
│       │   │   ├── cases.py        # 사건 분석 API
│       │   │   ├── search.py       # 판례 검색 API
│       │   │   └── crawl.py        # 크롤링 관리 API
│       │   └── schemas.py          # Pydantic 스키마
│       └── reports/
│           ├── __init__.py
│           └── generator.py        # 변호사 전달용 리포트 생성
└── tests/
    ├── test_crawlers/
    ├── test_parsers/
    ├── test_ai/
    └── test_search/
```

---

## 데이터베이스 스키마

### precedents (판례)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| case_number | VARCHAR | 사건번호 (예: 2023고단1234) |
| court | VARCHAR | 법원명 |
| case_type | ENUM | 형사/행정/민사 |
| date | DATE | 판결일 |
| charges | TEXT[] | 적용 죄명/혐의 |
| summary | TEXT | 판결 요지 |
| full_text | TEXT | 판결문 전문 |
| result | VARCHAR | 판결 결과 (유죄/무죄/기각 등) |
| keywords | TEXT[] | 키워드 |
| embedding | vector(1536) | 임베딩 벡터 |
| source_url | VARCHAR | 원본 URL |
| created_at | TIMESTAMP | 수집일시 |

### laws (법령)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| law_name | VARCHAR | 법령명 |
| article_number | VARCHAR | 조항 번호 |
| article_title | VARCHAR | 조항 제목 |
| content | TEXT | 조문 내용 |
| embedding | vector(1536) | 임베딩 벡터 |
| effective_date | DATE | 시행일 |
| source | VARCHAR | 출처 |

### analyses (분석 결과)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| case_description | TEXT | 사건 설명 (사용자 입력) |
| favorable_precedents | JSONB | 유리한 판례 목록 + 이유 |
| unfavorable_precedents | JSONB | 불리한 판례 목록 + 이유 |
| relevant_laws | JSONB | 관련 법 조항 + 반박 포인트 |
| strategy_notes | TEXT | 전략 메모 |
| created_at | TIMESTAMP | 분석일시 |

### news_articles (기사)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| title | VARCHAR | 기사 제목 |
| content | TEXT | 기사 내용 |
| url | VARCHAR | 원본 URL |
| published_at | DATE | 게시일 |
| embedding | vector(1536) | 임베딩 벡터 |

---

## 핵심 기능

### 1. 데이터 수집 파이프라인

| 소스 | 모듈 | 설명 |
|------|------|------|
| 법제처 API | `law_api.py` | 법령 조회 (학원법, 형법 등), 조문 단위 파싱 |
| 법원 판례 | `court.py` | 대법원 종합법률정보 크롤링, 하급심 PDF 포함 |
| 교육청 | `education.py` | 공개자료/행정심판 결과 |
| 뉴스 | `news.py` | 네이버/다음 뉴스 키워드 크롤링 |

### 2. 판례 검색 엔진

```
사건 설명 입력
    ↓ 임베딩 변환 (text-embedding-3-small)
    ↓ pgvector 코사인 유사도 검색
    ↓ 상위 N개 판례 추출
    ↓ GPT-4o로 유불리 분류
    ↓ 결과 정렬 및 반환
```

- **유사도 검색**: pgvector `<=>` 코사인 거리 연산자
- **유불리 분류**: GPT-4o에 사건 상황 + 판례 요지 → 유리/불리 판단
- **반박 법령 매칭**: 불리 판례에 대한 반박 가능 법 조항 자동 매칭

### 3. 리포트 생성

변호사 전달용 포맷:
- 사건 개요
- 유리한 판례 (유사도순): 사건번호, 요지, 유사 포인트
- 불리한 판례: 사건번호, 요지, 위험 포인트
- 반박 가능 법령: 조항, 활용 방안
- 전략 제안

출력: JSON / Markdown / PDF

---

## 실행 순서

| Phase | 내용 | 기간 |
|-------|------|------|
| **1. 초기화** | 프로젝트 구조, DB 설정, 모델 정의 | Day 1 |
| **2. 데이터 수집** | 법제처 API, 법원/교육청/뉴스 크롤러 | Day 2-4 |
| **3. AI 연동** | 임베딩 생성, GPT 분석 프롬프트, 분석기 | Day 5-6 |
| **4. 검색 엔진** | 유사도 검색, 유불리 분류, 반박 매칭 | Day 7-8 |
| **5. API + CLI** | FastAPI 라우트, Typer CLI, 리포트 생성 | Day 9-10 |
| **6. 통합 테스트** | E2E 테스트, 1차 분석, 결과 검증 | Day 11-12 |

---

## 핵심 전략

1. **GPT에 답변 맡기지 말 것** → 판례 추천 엔진으로만 사용
2. **판례는 많을수록 좋음** → 최소 수십~수백 건 확보
3. **불리한 판례도 반드시 포함** → 대응 전략 핵심
4. **형사 중심으로 설계** → 민사는 데이터 접근 어려움

---

## 분석 파이프라인

- **1차 분석**: 판례 수집 및 정렬 → 변호사 전달
- **2차 분석**: 정보공개청구 후 추가 데이터로 재분석

---

## 환경 변수

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/precedent_finder

# OpenAI
OPENAI_API_KEY=sk-...

# 법제처 API
LAW_API_KEY=...

# Redis (Celery)
REDIS_URL=redis://localhost:6379/0
```

---

## CLI 사용법 (예정)

```bash
# 크롤링 실행
precedent-finder crawl --source court --keyword "학원법"
precedent-finder crawl --source law-api --law "학원의 설립·운영 및 과외교습에 관한 법률"
precedent-finder crawl --source news --keyword "교육청 고발"

# 판례 검색
precedent-finder search "교육청 신고 학원 무등록 운영"

# 사건 분석
precedent-finder analyze "사건 설명..."

# 리포트 생성
precedent-finder report --analysis-id <uuid> --format markdown
```
