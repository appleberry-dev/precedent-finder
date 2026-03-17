# 판례 파인더 - 구현 계획서 (v3)

> 작성일: 2026-03-17

## 목표

1. **지방법원 판결서 PDF 수집** — 사법정보공개포털에서 판결서 열람 + PDF 저장
2. **자체 질의 시스템** — 수집된 판례/법령 데이터를 기반으로 자연어 질의응답 (RAG)
3. **Streamlit 웹 UI** — 채팅 인터페이스로 판례 질의, Streamlit Community Cloud 배포

---

## 현재 상태

| 구성요소 | 상태 | 비고 |
|----------|------|------|
| 법제처 판례 크롤러 | 동작 확인 | 10건 수집, 페이징 지원 |
| 법제처 Open API | 승인 대기 | OC 인증 필요 |
| 지방법원 판결서 크롤러 | 골격만 구현 | PDF 수집 미구현 |
| 법령 조문 크롤러 | 구현 완료 | 미실행 |
| CLI | 동작 확인 | crawl, search, status, run-all |
| DB / 검색엔진 | 없음 | JSON 파일 기반 |
| 질의 시스템 | 없음 | - |

---

## 9단계 구현 상세

---

### Step 1. 사법정보공개포털 크롤러 리팩토링

**목적**: 기존 `court_viewer.py`의 진입점을 개별 법원 wcd.jsp에서 통합 포털로 변경

**대상 사이트**: `portal.scourt.go.kr` (사법정보공개포털)

**수정 파일**: `src/precedent_finder/crawlers/court_viewer.py`

**열람 가능 범위**:
- 형사: 2013.1.1 이후 확정 판결
- 민사/행정/특허: 2015.1.1 이후 확정 또는 2023.1.1 이후 선고

**구현 내용**:
1. 사법정보공개포털 통합 검색 페이지(`portal.scourt.go.kr/pgp/index.on`)로 진입
2. 검색 조건 자동 설정
   - 사건 유형 선택 (형사/민사/행정)
   - 법원 선택 (서울중앙, 인천, 수원 등)
   - 기간 설정 (선고일 기준)
   - 키워드 입력
3. 검색 결과 목록 파싱
   - 사건번호, 법원명, 선고일, 사건명 추출
   - 페이징 처리 (다음 페이지 자동 이동)
4. 판결서 상세 페이지 진입 → 본문 텍스트 추출
   - 【주문】, 【이유】 등 섹션별 파싱
   - 기존 Precedent 데이터 구조로 변환
5. 기존 `COURT_CODES` dict 제거 → 포털 통합 검색으로 대체

**기술적 고려사항**:
- nProtect, IPinside 등 보안 프로그램 요구 가능 → 헤드리스 모드에서 우회 전략 필요
- JS 렌더링 필수 → Selenium 유지
- 로그인 불필요 (공개 열람 서비스)
- 비실명 처리된 판결문 제공 (개인정보 마스킹)

**완료 기준**: 사법정보공개포털에서 "학원법" 검색 → 판결서 목록 파싱 → 상세 텍스트 추출 1건 이상 성공

---

### Step 2. PDF 수집 파이프라인

**목적**: 판결서를 PDF 파일로 저장하고 텍스트를 추출하는 파이프라인

**신규 파일**: `src/precedent_finder/crawlers/pdf_collector.py`

**구현 내용**:
1. **PDF 다운로드 전략 (우선순위)**:
   ```
   1순위: 페이지 내 PDF 다운로드 버튼/링크 탐지 → 직접 다운로드
   2순위: streamdocs 뷰어(pvo-psp.scourt.go.kr/streamdocs)에서 원본 PDF URL 추출
   3순위: Chrome DevTools Protocol의 Page.printToPDF로 현재 페이지를 PDF 변환
   ```
2. **PDF 저장**:
   - 경로: `data/pdfs/{법원}_{사건번호}.pdf`
   - 파일명 정규화 (특수문자 제거)
   - 중복 파일 스킵
3. **PDF → 텍스트 변환**:
   - `pdfplumber`로 페이지별 텍스트 추출 (이미 의존성에 포함)
   - 추출 실패 시 fallback: `PyMuPDF(fitz)` 시도
   - 추출된 텍스트를 Precedent의 `full_text` 필드에 저장
4. **Chrome print-to-pdf 구현**:
   ```python
   # Selenium CDP 명령으로 PDF 생성
   result = driver.execute_cdp_cmd("Page.printToPDF", {
       "printBackground": True,
       "preferCSSPageSize": True,
   })
   pdf_bytes = base64.b64decode(result["data"])
   ```
5. **court_viewer.py 연동**:
   - `scrape_decision_detail()` 호출 후 자동으로 PDF 저장
   - `Precedent.pdf_path` 필드 추가 (PDF 파일 경로)

**완료 기준**: 판결서 1건 → PDF 저장(`data/pdfs/`) → pdfplumber로 텍스트 추출 성공

---

### Step 3. SQLite DB 구축

**목적**: JSON 파일 기반 → 구조화된 DB로 전환, 검색 성능 확보

**신규 파일**: `src/precedent_finder/db/store.py`

**구현 내용**:
1. **DB 파일**: `data/precedent_finder.db` (SQLite)
2. **테이블 스키마**:
   ```sql
   -- 판례
   CREATE TABLE precedents (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       prec_seq TEXT UNIQUE,           -- 판례 일련번호 (법제처)
       case_name TEXT,                 -- 사건명
       case_number TEXT,               -- 사건번호 (2015두48655)
       judgment_date TEXT,             -- 선고일자
       court_name TEXT,                -- 법원명
       case_type TEXT,                 -- 사건종류 (형사/민사/행정)
       judgment_type TEXT,             -- 판결유형
       issues TEXT,                    -- 판시사항
       summary TEXT,                   -- 판결요지
       full_text TEXT,                 -- 판례내용/판결서 전문
       reference_articles TEXT,        -- 참조조문
       reference_cases TEXT,           -- 참조판례
       source_url TEXT,                -- 원본 URL
       pdf_path TEXT,                  -- PDF 파일 경로
       source TEXT DEFAULT 'law_site', -- 출처 (law_site/court_viewer/api)
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );

   -- 법령 조문
   CREATE TABLE statutes (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       law_name TEXT,                  -- 법령명
       article_number TEXT,            -- 조번호 (제1조)
       article_title TEXT,             -- 조제목
       content TEXT,                   -- 조문 내용
       source_url TEXT,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       UNIQUE(law_name, article_number)
   );
   ```
3. **PrecedentStore 클래스**:
   ```python
   class PrecedentStore:
       def __init__(self, db_path="data/precedent_finder.db")
       def init_db(self)                    # 테이블 생성
       def upsert_precedent(self, prec)     # 판례 저장 (중복 시 업데이트)
       def upsert_statute(self, statute)    # 법령 저장
       def get_precedent(self, prec_seq)    # 단건 조회
       def search(self, query, fields)      # LIKE 검색
       def list_all(self)                   # 전체 목록
       def count(self)                      # 건수
       def import_from_json(self, path)     # JSON → DB
   ```
4. **인덱스**:
   ```sql
   CREATE INDEX idx_prec_case_number ON precedents(case_number);
   CREATE INDEX idx_prec_court ON precedents(court_name);
   CREATE INDEX idx_prec_date ON precedents(judgment_date);
   CREATE INDEX idx_statute_law ON statutes(law_name);
   ```

**완료 기준**: `PrecedentStore` 인스턴스 생성 → `init_db()` → DB 파일 생성 확인

---

### Step 4. 기존 데이터 마이그레이션

**목적**: 현재 `data/precedents.json`의 10건 데이터를 DB로 이관, 크롤러 출력을 DB에 직접 연결

**수정 파일**: `src/precedent_finder/db/store.py`, `src/precedent_finder/crawlers/court_scraper.py`

**구현 내용**:
1. **JSON → DB 마이그레이션**:
   ```python
   store = PrecedentStore()
   store.import_from_json("data/precedents.json")
   # → 10건 판례 DB 저장
   ```
2. **크롤러 출력 연결**:
   - `court_scraper.py`의 `crawl()` 함수에서 결과를 DB에도 저장
   - `court_viewer.py`의 `crawl_court_viewer()` 결과도 DB 저장
   - `law_scraper.py`의 `crawl_statutes()` 결과도 DB 저장
   - JSON 저장은 유지 (백업 용도)
3. **CLI status 명령 수정**:
   - JSON 대신 DB에서 현황 조회
   - 출처별(법제처/지방법원/API) 건수 표시
4. **CLI search 명령 수정**:
   - JSON 선형 탐색 → SQLite LIKE 쿼리로 전환

**완료 기준**: `precedent-finder status` → DB 기반 현황 출력 (10건), `precedent-finder search "학원"` → DB 쿼리 결과 반환

---

### Step 5. 텍스트 청킹

**목적**: 판례/법령 텍스트를 RAG에 적합한 크기로 분할

**신규 파일**: `src/precedent_finder/rag/__init__.py`, `src/precedent_finder/rag/chunker.py`

**구현 내용**:
1. **판례 청킹 전략** (섹션 우선 분할):
   ```
   1개 판례 → 여러 청크:
     - 메타 청크: "[사건번호] 사건명 / 법원 / 선고일 / 판결유형"
     - 판시사항 청크 (500~1000자 단위)
     - 판결요지 청크 (500~1000자 단위)
     - 판례내용(본문) 청크 (500~1000자 단위)
     - 참조조문 청크
   ```
2. **법령 청킹 전략**:
   ```
   1개 법령 → 조문 단위 청크:
     - "학원법 제2조(정의): 조문 내용..."
     - 조문이 길면 항(①②③) 단위로 분할
   ```
3. **청킹 파라미터**:
   - `chunk_size`: 800자 (기본값)
   - `chunk_overlap`: 100자
   - 문장 경계에서 분할 (마침표, 개행 기준)
4. **Chunk 데이터 구조**:
   ```python
   @dataclass
   class Chunk:
       id: str                    # "{source_type}_{source_id}_{chunk_index}"
       source_type: str           # "precedent" | "statute"
       source_id: int             # DB의 id
       chunk_index: int           # 청크 순서
       content: str               # 청크 텍스트
       metadata: dict             # case_number, court_name, section 등
   ```
5. **Chunker 클래스**:
   ```python
   class Chunker:
       def chunk_precedent(self, prec: dict) -> list[Chunk]
       def chunk_statute(self, statute: dict) -> list[Chunk]
       def chunk_all(self, store: PrecedentStore) -> list[Chunk]
   ```

**완료 기준**: 10건 판례 → 청크 분할 → 청크 수 50개 이상 생성, 각 청크 800자 이내

---

### Step 6. 임베딩 & 벡터 DB

**목적**: 청크를 벡터로 변환하고 유사도 검색이 가능한 벡터 DB에 저장

**신규 파일**: `src/precedent_finder/rag/retriever.py`

**신규 의존성**: `chromadb>=0.5`, `ollama>=0.4`

**구현 내용**:
1. **임베딩 모델 (우선순위)**:
   ```
   1순위: Ollama 로컬 - bge-m3 (한국어 우수, 1024차원)
          → ollama pull bge-m3
   2순위: Ollama 로컬 - nomic-embed-text (384차원, 경량)
          → ollama pull nomic-embed-text
   3순위: sentence-transformers - jhgan/ko-sroberta-multitask (한국어 특화)
   4순위: OpenAI text-embedding-3-small (API 비용 발생)
   ```
2. **벡터 DB (ChromaDB)**:
   - 저장 경로: `data/chroma_db/`
   - 컬렉션: `precedents`, `statutes`
   - 메타데이터 필터링 지원 (법원별, 사건유형별)
3. **Retriever 클래스**:
   ```python
   class Retriever:
       def __init__(self, embed_model="bge-m3", db_path="data/chroma_db")
       def embed_text(self, text: str) -> list[float]
       def index_chunks(self, chunks: list[Chunk])     # 청크 임베딩 → 벡터 DB 저장
       def search(self, query: str, top_k=5) -> list[Chunk]  # 유사도 검색
       def hybrid_search(self, query: str, top_k=5)    # 벡터 + 키워드 결합
   ```
4. **하이브리드 검색**:
   - 벡터 유사도 (코사인): 의미 기반 검색
   - 키워드 매칭: 사건번호, 법조문 번호 등 정확한 매칭
   - 가중 결합: `score = 0.7 * vector_score + 0.3 * keyword_score`
5. **인덱싱 프로세스**:
   ```
   DB 판례/법령 → Chunker → Chunk 리스트 → Retriever.index_chunks()
   → 임베딩 생성 → ChromaDB 저장
   ```

**사전 조건**: Ollama 설치 + `ollama pull bge-m3` 실행

**완료 기준**: `Retriever.search("무등록 학원 처벌")` → 관련 청크 5개 반환, 첫 번째 결과가 학원법 관련 판례

---

### Step 7. 질의응답 엔진

**목적**: 검색된 청크를 컨텍스트로 LLM에 전달하여 자연어 답변 생성

**신규 파일**: `src/precedent_finder/rag/qa.py`

**신규 의존성**: `anthropic>=0.40` (Claude API 사용 시)

**구현 내용**:
1. **LLM 백엔드 (우선순위)**:
   ```
   1순위: Ollama 로컬 - llama3.2 (8B), gemma2 (9B), 또는 EEVE-Korean (한국어 특화)
          → ollama pull llama3.2
   2순위: Claude API - claude-sonnet-4-6 (고품질, 비용 발생)
   3순위: OpenAI API - gpt-4o-mini
   ```
2. **프롬프트 템플릿**:
   ```
   당신은 한국 법률 전문 AI입니다.
   아래 판례와 법령 자료를 참고하여 질문에 답변하세요.

   규칙:
   - 반드시 근거가 되는 판례 번호(예: 2015두48655)나 법령 조문(예: 학원법 제2조)을 인용하세요.
   - 자료에 없는 내용은 추측하지 말고 "확인된 자료에서 찾을 수 없습니다"라고 답하세요.
   - 형량, 벌금 등 처벌 수위는 판례 원문을 그대로 인용하세요.

   [참고 자료]
   {context}

   [질문]
   {question}
   ```
3. **QA 클래스**:
   ```python
   class QAEngine:
       def __init__(self, retriever: Retriever, llm_backend="ollama")
       def ask(self, question: str, top_k=5) -> Answer
       def _build_context(self, chunks: list[Chunk]) -> str
       def _call_llm(self, prompt: str) -> str
   ```
4. **Answer 데이터 구조**:
   ```python
   @dataclass
   class Answer:
       question: str              # 원본 질문
       answer: str                # LLM 생성 답변
       sources: list[dict]        # 참고한 판례/법령 목록
           # [{"type": "precedent", "case_number": "2015두48655", "court": "대법원", "snippet": "..."}]
       chunks_used: int           # 사용된 청크 수
   ```
5. **컨텍스트 구성**:
   ```
   [판례 1] 대법원 2018.6.21 선고 2015두48655 전원합의체 판결
   판결요지: ...
   ---
   [판례 2] ...
   ---
   [법령] 학원법 제2조(정의)
   ① ...
   ```

**사전 조건**: Ollama 설치 + LLM 모델 pull, 또는 Claude API 키 설정

**완료 기준**: `QAEngine.ask("무등록 학원 운영 시 처벌은?")` → 판례 인용 포함 답변 반환

---

### Step 8. Streamlit 웹 UI + 배포

**목적**: 채팅 인터페이스로 판례 질의, 데이터 현황 확인, Streamlit Community Cloud 무료 배포

**신규 파일**: `app.py` (프로젝트 루트), `src/precedent_finder/web/__init__.py`, `src/precedent_finder/web/pages/`

**신규 의존성**: `streamlit>=1.40`

**구현 내용**:

1. **메인 앱 (`app.py`)**:
   ```python
   # Streamlit 진입점 (프로젝트 루트)
   import streamlit as st
   st.set_page_config(page_title="판례 파인더", page_icon="???", layout="wide")
   ```

2. **채팅 페이지** — 핵심 기능:
   ```
   ┌─────────────────────────────────────────┐
   │  ?? 판례 파인더                          │
   ├─────────────────────────────────────────┤
   │                                         │
   │  ?? 무등록 학원 운영 시 처벌 수위는?     │
   │                                         │
   │  ?? 무등록 학원 운영은 학원법 제22조에   │
   │     따라 1년 이하의 징역 또는 ...        │
   │                                         │
   │     ???? 참고 판례:                       │
   │     1. 대법원 2023.2.2 2021도16198       │
   │     2. 청주지법 2005.7.22 2005노479      │
   │                                         │
   │     ???? 참고 법령:                       │
   │     - 학원법 제6조(학원의 설립·운영의 등록)│
   │                                         │
   ├─────────────────────────────────────────┤
   │  [질문을 입력하세요...]          [전송]  │
   └─────────────────────────────────────────┘
   ```
   - `st.chat_input()` + `st.chat_message()`로 채팅 UI 구성
   - `st.session_state`로 대화 히스토리 유지
   - 답변 생성 중 `st.spinner()` 또는 `st.write_stream()` 스트리밍
   - 참고 판례/법령을 `st.expander()`로 접이식 표시
   - QAEngine 호출 → Answer 객체 → 채팅 메시지 렌더링

3. **사이드바**:
   ```python
   with st.sidebar:
       st.header("설정")
       llm_backend = st.selectbox("LLM", ["ollama", "claude", "openai"])
       top_k = st.slider("검색 청크 수", 3, 10, 5)
       st.divider()
       st.header("데이터 현황")
       st.metric("판례", f"{prec_count}건")
       st.metric("법령", f"{statute_count}개")
       st.metric("벡터 청크", f"{chunk_count}개")
   ```

4. **데이터 관리 페이지** (`pages/data.py`):
   - 수집된 판례 목록 테이블 (`st.dataframe()`)
   - 법원별/연도별 필터링
   - 판례 상세 보기 (클릭 시 전문 표시)
   - 인덱싱 실행 버튼 (`precedent-finder index` 동등)

5. **CLI 확장** — `index` 커맨드만 CLI에 추가:
   ```bash
   # DB 초기화 & 벡터 인덱싱 (로컬에서 실행)
   precedent-finder index

   # Streamlit 앱 로컬 실행
   streamlit run app.py
   ```

6. **배포 (Streamlit Community Cloud)**:
   - `requirements.txt` 또는 `pyproject.toml`에서 의존성 자동 설치
   - `.streamlit/config.toml` 테마 설정
   - `.streamlit/secrets.toml` → API 키 관리 (Claude, OpenAI 등)
   - GitHub repo 연결 → `share.streamlit.io`에서 Deploy
   - 배포 URL: `https://precedent-finder.streamlit.app`
   - **주의**: Streamlit Cloud에서는 Selenium/크롤링 불가 → 크롤링은 로컬 CLI, 질의만 웹

7. **배포용 파일 구조**:
   ```
   (프로젝트 루트)
   ├── app.py                      # Streamlit 진입점
   ├── pages/
   │   └── data.py                 # 데이터 관리 페이지
   ├── .streamlit/
   │   ├── config.toml             # 테마, 서버 설정
   │   └── secrets.toml            # API 키 (gitignore 대상)
   ├── data/
   │   ├── precedent_finder.db     # SQLite (배포 시 포함)
   │   └── chroma_db/              # 벡터 DB (배포 시 포함)
   └── ...
   ```

8. **배포 시 LLM 전략**:
   - Streamlit Cloud에서는 Ollama 로컬 사용 불가
   - → Claude API 또는 OpenAI API 사용 (secrets.toml로 키 관리)
   - 로컬에서는 Ollama 우선, 배포 환경에서는 API 자동 전환:
     ```python
     if os.getenv("STREAMLIT_CLOUD"):
         backend = "claude"  # secrets에서 API 키 로드
     else:
         backend = "ollama"  # 로컬 LLM
     ```

**완료 기준**:
- 로컬: `streamlit run app.py` → 채팅 UI에서 판례 질의 → 답변 + 출처 표시
- 배포: `https://precedent-finder.streamlit.app` 접속 → 동일 동작 확인

---

### Step 9. 대법원 개방형 API 연동 (선택)

**목적**: 크롤링 보조 수단으로 대법원 공식 API 활용

**대상**: `openapi.scourt.go.kr` (사법정보공유포털 API)

**신규 파일**: `src/precedent_finder/crawlers/court_api.py`

**구현 내용**:
1. **API KEY 발급**:
   - `openapi.scourt.go.kr` 회원가입 → API KEY 신청
   - 유효기간: 2년, 트래픽: 초당 10건
   - KEY를 `.env` 또는 환경변수 `SCOURT_API_KEY`로 관리
2. **API 클라이언트**:
   ```python
   class ScourtAPIClient:
       def __init__(self, api_key: str)
       def search(self, keyword: str, page=1, size=20) -> list[dict]
       def get_detail(self, case_id: str) -> dict
       def search_and_fetch(self, keyword: str, max_results=50) -> list[Precedent]
   ```
3. **인증 방식**: API-KEY 헤더 또는 쿼리 파라미터
4. **응답 형식**: JSON (`Application/Json`)
5. **기존 데이터와 병합**:
   - API 결과를 Precedent 구조로 변환
   - `prec_seq` 또는 `case_number` 기준 중복 제거
   - DB에 `source='court_api'`로 저장
6. **CLI 연동**:
   ```bash
   precedent-finder crawl --source court-api --keywords "학원법"
   ```
7. **크롤링 대비 장점**:
   - 안정적 (HTML 구조 변경에 무관)
   - 빠름 (Selenium 불필요)
   - 구조화된 데이터 (파싱 불필요)

> 참고: API 승인까지는 Selenium 크롤링(Step 1)으로 진행. 승인 후 API 우선 전환.

**완료 기준**: API KEY 발급 → `precedent-finder crawl --source court-api --keywords "학원"` → 판례 수집 성공

---

## 신규 의존성

```toml
# pyproject.toml에 추가
"chromadb>=0.5",           # 벡터 DB
"ollama>=0.4",             # 로컬 LLM/임베딩 클라이언트
"anthropic>=0.40",         # Claude API (배포 환경 LLM)
"streamlit>=1.40",         # 웹 UI
```

## 파일 구조 (완성 시)

```
(프로젝트 루트)
├── app.py                              # Streamlit 진입점 (Step 8)
├── pages/
│   └── data.py                         # 데이터 관리 페이지 (Step 8)
├── .streamlit/
│   ├── config.toml                     # Streamlit 테마/설정
│   └── secrets.toml                    # API 키 (gitignore)
│
├── src/precedent_finder/
│   ├── cli.py                          # CLI (크롤링 + index)
│   ├── crawlers/
│   │   ├── court_scraper.py            # 법제처 판례 (기존)
│   │   ├── court_viewer.py             # 사법정보공개포털 판결서 (Step 1)
│   │   ├── pdf_collector.py            # PDF 수집/텍스트 추출 (Step 2)
│   │   ├── court_api.py                # 대법원 개방형 API (Step 9)
│   │   ├── law_api.py                  # 법제처 API (기존)
│   │   └── law_scraper.py              # 법령 조문 (기존)
│   ├── db/
│   │   ├── __init__.py
│   │   └── store.py                    # SQLite 저장소 (Step 3-4)
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── chunker.py                  # 텍스트 분할 (Step 5)
│   │   ├── retriever.py                # 벡터 검색 (Step 6)
│   │   └── qa.py                       # 질의응답 (Step 7)
│   ├── exporters/
│   │   └── notebook_lm.py
│   └── parsers/
│
├── data/
│   ├── precedent_finder.db             # SQLite DB
│   ├── chroma_db/                      # 벡터 DB
│   ├── pdfs/                           # 판결서 PDF 파일
│   ├── precedents.json                 # 판례 JSON (백업)
│   └── statutes.json                   # 법령 JSON (백업)
│
└── pyproject.toml
```

## 운영 구조

```
[로컬 환경]                              [Streamlit Cloud]
┌──────────────────────┐                ┌──────────────────────┐
│ CLI (크롤링/인덱싱)   │                │ Streamlit 웹 UI      │
│                      │                │                      │
│ precedent-finder     │  git push →    │ app.py               │
│   crawl (Selenium)   │  data/ 포함     │   채팅 (RAG 질의)    │
│   index (임베딩)     │                │   데이터 열람         │
│                      │                │   Claude API 연동     │
│ Ollama (로컬 LLM)   │                │                      │
└──────────────────────┘                └──────────────────────┘
  크롤링 → DB → 벡터DB                    DB + 벡터DB 읽기 전용
```

- **크롤링/인덱싱**: 로컬 CLI에서만 실행 (Selenium 필요)
- **질의**: 로컬(`streamlit run app.py` + Ollama) 또는 배포(`streamlit.app` + Claude API)
- **데이터 동기화**: git push로 DB 파일 포함하여 배포 반영

## 검증 기준 종합

| Step | 검증 |
|------|------|
| 1 | 사법정보공개포털 "학원법" 검색 → 판결서 텍스트 추출 1건 이상 |
| 2 | 판결서 PDF 저장 → pdfplumber 텍스트 추출 성공 |
| 3 | `PrecedentStore.init_db()` → SQLite DB 파일 생성 |
| 4 | `precedent-finder status` → DB 기반 10건 표시 |
| 5 | 10건 판례 → 50개+ 청크 생성, 각 800자 이내 |
| 6 | `Retriever.search("무등록 학원")` → 관련 청크 5개 반환 |
| 7 | `QAEngine.ask("학원법 위반 처벌")` → 판례 인용 답변 |
| 8 | `streamlit run app.py` → 채팅 질의 동작 + Streamlit Cloud 배포 성공 |
| 9 | API KEY 발급 → `crawl --source court-api` 성공 |
