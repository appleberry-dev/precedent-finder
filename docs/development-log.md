# 판례 파인더 — 개발 완료 내역

> 최종 업데이트: 2026-03-17

## 프로젝트 개요

교육청 고발 대응을 위한 판례/법령 수집 + RAG 질의응답 시스템.
법제처·지방법원에서 판례를 크롤링하고, 수집된 데이터를 기반으로 자연어 질의에 답변한다.

---

## 구현 완료 현황

| Step | 내용 | 상태 |
|------|------|------|
| 1 | 사법정보공개포털 크롤러 리팩토링 | 완료 |
| 2 | PDF 수집 파이프라인 | 완료 |
| 3 | SQLite DB 구축 | 완료 |
| 4 | 기존 데이터 마이그레이션 | 완료 |
| 5 | 텍스트 청킹 | 완료 |
| 6 | 임베딩 & 벡터 DB (ChromaDB) | 완료 |
| 7 | 질의응답 엔진 (RAG) | 완료 |
| 8 | Streamlit 웹 UI + 배포 설정 | 완료 |
| 9 | 대법원 개방형 API 연동 | 대기 (API KEY 승인 필요) |

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| 패키지 관리 | uv |
| 크롤링 | Selenium, BeautifulSoup, lxml |
| PDF | pdfplumber, Chrome CDP (Page.printToPDF) |
| DB | SQLite |
| 벡터 DB | ChromaDB |
| 임베딩 | OpenAI text-embedding-3-small (또는 Ollama bge-m3) |
| LLM | OpenAI gpt-4o-mini / Claude claude-sonnet-4-6 / Ollama (자동 선택) |
| 웹 UI | Streamlit |
| CLI | Typer + Rich |
| 배포 | Streamlit Community Cloud (예정) |

---

## 파일 구조

```
precedent-finder/
├── app.py                              # Streamlit 메인 (채팅 UI)
├── pages/
│   └── data.py                         # Streamlit 데이터 관리 페이지
├── .streamlit/
│   └── config.toml                     # Streamlit 테마 설정
├── .env                                # API 키 (gitignore 대상)
│
├── src/precedent_finder/
│   ├── cli.py                          # 통합 CLI (5개 커맨드)
│   │
│   ├── crawlers/                       # 크롤러 모듈
│   │   ├── court_scraper.py            # 법제처 판례 (Selenium, 235줄)
│   │   ├── court_viewer.py             # 법고을 + 개별법원 판결서 (433줄)
│   │   ├── pdf_collector.py            # PDF 수집/텍스트 추출 (152줄)
│   │   ├── law_scraper.py              # 법령 조문 크롤러 (221줄)
│   │   └── law_api.py                  # 법제처 Open API 클라이언트 (210줄)
│   │
│   ├── db/                             # 데이터 저장소
│   │   └── store.py                    # SQLite PrecedentStore (211줄)
│   │
│   ├── rag/                            # RAG 파이프라인
│   │   ├── chunker.py                  # 텍스트 분할 (159줄)
│   │   ├── retriever.py                # 벡터 검색 (165줄)
│   │   └── qa.py                       # LLM 질의응답 (251줄)
│   │
│   └── exporters/
│       └── notebook_lm.py              # NotebookLM Markdown 내보내기
│
├── data/
│   ├── precedent_finder.db             # SQLite DB (10건 판례)
│   ├── chroma_db/                      # 벡터 DB (126 청크)
│   ├── precedents.json                 # 판례 JSON 백업
│   └── pdfs/                           # PDF 저장 디렉토리
│
├── docs/
│   ├── implementation-plan-v3.md       # 구현 계획서
│   └── development-log.md              # 이 파일
│
├── pyproject.toml                      # 프로젝트 설정 + 의존성
└── README.md                           # 프로젝트 개요
```

총 소스 코드: **2,575줄** (16개 Python 파일)

---

## 각 모듈 상세

### 1. 크롤러 (crawlers/)

#### court_scraper.py — 법제처 판례 크롤러
- 법제처 국가법령정보센터(law.go.kr) Selenium 스크래핑
- 키워드 검색 → 판례 ID 추출 → 상세 페이지 파싱
- 페이징 지원 (`max_pages` 파라미터)
- 기존 JSON과 병합 (prec_seq 기준 중복 제거)
- 검증: 10건 크롤링 성공

#### court_viewer.py — 판결서 크롤러
- 2개 데이터 소스 통합:
  - **법고을** (`lx.scourt.go.kr/search/precedent`) — 대법원~하급심 통합 검색
  - **개별법원 wcd.jsp** — 11개 지방법원 판결서 열람
- 법원 11곳: 서울중앙/동부/서부/남부/북부, 인천, 수원, 대전, 대구, 부산, 광주
- 판결서 상세 파싱: 【주문】,【이유】,【판시사항】,【판결요지】 섹션 분리
- 메타 정보 추출: 사건번호, 법원명, 선고일, 판결유형

#### pdf_collector.py — PDF 수집
- 3단계 PDF 저장 전략:
  1. 페이지 내 PDF 다운로드 링크 탐지
  2. Chrome CDP `Page.printToPDF`로 현재 페이지 PDF 변환
  3. pdfplumber로 텍스트 추출
- 저장 경로: `data/pdfs/{법원}_{사건번호}.pdf`
- 중복 파일 자동 스킵

#### law_scraper.py — 법령 조문 크롤러
- 법제처에서 법령 조문 스크래핑
- 대상 법령: 학원법, 형법, 교육기본법, 아동복지법
- 조문 단위 파싱 (제X조), 항(①②③) 분리
- JSON + Markdown 출력

#### law_api.py — 법제처 Open API
- law.go.kr REST API 클라이언트 (XML 파싱)
- 검색 + 상세 조회 + Rate limiting
- 상태: API 승인 대기 (OC 인증 필요)

### 2. 데이터베이스 (db/)

#### store.py — PrecedentStore
- SQLite 기반 (`data/precedent_finder.db`)
- 테이블: `precedents` (판례), `statutes` (법령 조문)
- UPSERT (중복 시 업데이트, 빈 필드만 덮어쓰기)
- 인덱스: case_number, court_name, judgment_date, law_name
- JSON → DB 마이그레이션 메서드 내장
- 법원별/출처별 통계 조회

### 3. RAG 파이프라인 (rag/)

#### chunker.py — 텍스트 분할
- 판례: 섹션별 분할 (메타, 판시사항, 판결요지, 본문, 참조조문)
- 법령: 조문 단위 분할
- 청크 크기: 800자, 오버랩: 100자, 문장 경계 분할
- 검증: 10건 판례 → **126개 청크**

#### retriever.py — 벡터 검색
- ChromaDB 기반 (`data/chroma_db/`)
- 임베딩 모델 자동 선택: Ollama bge-m3 → OpenAI text-embedding-3-small
- 하이브리드 검색: 벡터 유사도(0.7) + 키워드 매칭(0.3)
- 배치 인덱싱 (50개 단위)

#### qa.py — 질의응답 엔진
- LLM 자동 선택: Ollama → Claude → OpenAI
- 스트리밍 응답 지원 (Streamlit `st.write_stream` 연동)
- 법률 전문 시스템 프롬프트 (판례번호/법조문 인용 강제)
- Answer 구조체: 답변 + 출처 목록 + 사용 청크 수
- 검증: "무등록 학원 운영 시 처벌은?" → 판례 5건 검색, 답변 생성 성공

### 4. CLI (cli.py)

5개 커맨드:

| 커맨드 | 설명 |
|--------|------|
| `crawl` | 판례/법령 크롤링 (law-site, court-viewer, statutes) |
| `status` | DB 기반 데이터 현황 (판례 수, 법원별, 출처별, PDF, 벡터 DB) |
| `search` | SQLite LIKE 검색 (키워드 + snippet 표시) |
| `index` | JSON→DB 마이그레이션 + 벡터 DB 구축 |
| `run-all` | 전체 크롤링 (법제처 판례 + 법령) |

### 5. Streamlit 웹 UI (app.py, pages/data.py)

**채팅 페이지** (`app.py`):
- `st.chat_input` + `st.chat_message` 채팅 인터페이스
- RAG 스트리밍 답변 (`st.write_stream`)
- 참고 자료 접이식 표시 (`st.expander`)
- 사이드바: LLM 백엔드 선택, 검색 청크 수 조절, 데이터 현황 메트릭

**데이터 관리 페이지** (`pages/data.py`):
- 판례 탭: 법원별 필터, 정렬, 테이블 + 상세 보기
- 법령 탭: 법령별 조문 목록
- 검색 탭: 키워드 검색 + 결과 표시

---

## 현재 데이터 현황

| 항목 | 값 |
|------|-----|
| 판례 수 | 10건 |
| 법원 | 대법원(5), 대전지방법원(1), 서울행법(1), 청주지법(1), 기타(2) |
| 벡터 DB 청크 | 126개 |
| 법령 조문 | 0건 (미실행) |
| PDF | 0건 |
| 임베딩 모델 | OpenAI text-embedding-3-small |
| LLM | OpenAI gpt-4o-mini |

---

## 운영 구조

```
[로컬 환경]                              [Streamlit Cloud]
┌──────────────────────┐                ┌──────────────────────┐
│ CLI                  │                │ Streamlit 웹 UI      │
│  crawl (Selenium)    │   git push →   │  채팅 (RAG 질의)     │
│  index (임베딩)      │   DB 포함      │  데이터 열람          │
│                      │                │  OpenAI API 연동      │
│ Ollama (로컬 LLM)   │                │                      │
└──────────────────────┘                └──────────────────────┘
```

- 크롤링/인덱싱: 로컬 CLI에서만 (Selenium 필요)
- 질의: 로컬 또는 Streamlit Cloud (OpenAI API)
- 배포: git push로 DB 포함하여 반영

---

## 미완료 / 향후 작업

| 항목 | 상태 | 비고 |
|------|------|------|
| 대법원 개방형 API (Step 9) | 대기 | API KEY 승인 필요 (`openapi.scourt.go.kr`) |
| 대량 크롤링 | 미실행 | `crawl --max 50 --pages 3`으로 200건+ 수집 필요 |
| 법령 조문 크롤링 | 미실행 | `crawl --source statutes` |
| Streamlit Cloud 배포 | 미배포 | `share.streamlit.io` → GitHub 연결 |
| 판결서 PDF 수집 | 미실행 | court_viewer + pdf_collector 연동 |

---

## 실행 방법

```bash
# 1. 의존성 설치
uv sync
uv pip install -e .

# 2. .env에 API 키 설정
OPENAI_API_KEY=sk-...

# 3. 인덱싱 (JSON→DB + 벡터 DB 구축)
precedent-finder index

# 4. 웹 UI 실행
streamlit run app.py

# 5. 추가 크롤링
precedent-finder crawl --source law-site --keywords "학원,교습소,학원법위반" --max 50 --pages 3
precedent-finder crawl --source statutes
precedent-finder index   # 재인덱싱
```
