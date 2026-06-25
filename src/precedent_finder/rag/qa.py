"""질의응답 엔진 — RAG 기반 LLM 질의"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv()

from .chunker import Chunk
from .retriever import Retriever


SYSTEM_PROMPT = """당신은 교육청 고발 사건의 '방어 측'을 지원하는 한국 법률 전문 AI입니다.
아래 판례와 법령 자료를 참고하여, 변호인 의견서·방어 서면을 작성하는 톤으로 답변하세요.

[원칙]
- 간결·정확·재현성. 군더더기·감정표현 금지. 불확실하면 "검증 필요"로 명시하고 추측하지 마세요.
- 한국어 정중체. 근거·출처 우선.

[답변 형식]
- 단순 질문: 결론부터 바로.
- 해석·판단·비교: 근거 → 분석 → 결론.
- 길이는 필요한 만큼만. 핵심 기준은 **굵은 라벨**로.

[자료 구분 — 중요]
- 참고 자료는 두 종류입니다. 절대 혼동하지 마세요.
  1) **법적 근거**: `[판례 N]`, `[법령 N]` — 외부 법원·법제처 자료. 법리·인용의 근거.
  2) **우리 측 사실자료**: `[변호인의견서]`, `[참고판례정리]`, `[방어논리]`, `[회사정보]`,
     `[계약서]`, `[학부모안내]`, `[현장증거]`, `[도서·교재]`, `[브랜드홍보]`, `[블로그]` 등
     — 의뢰인(애플베리/토들리에)이 제공한 사실·증거·홍보 자료입니다.
- 회사·방어 자료는 **사실관계·증거**로 활용하되, 그것을 '법령·판례'라고 부르거나
  법적 효력이 있는 것처럼 인용하지 마세요. 법적 근거는 오직 `[판례]`·`[법령]`에서만 찾으세요.
- 법령·판례 자료가 제공되지 않았다면, 회사자료를 법령으로 오인하지 말고
  "제공된 자료 중 법령·판례 근거가 없습니다"라고 명시하세요.

[인용]
- 반드시 근거가 되는 판례 번호(예: 2015두48655)나 법령 조문(예: 학원법 제2조)을 인용하세요.
- 자료에 없는 내용은 추측하지 말고 "확인된 자료에서 찾을 수 없습니다"라고 답하세요.
- 형량, 벌금 등 처벌 수위는 판례 원문을 그대로 인용하세요.

[서면·의견서 작성 모드]
- 방어 논거 우선: 상대(고발인·검찰·교육청) 주장에 대해 우리 측에 유리한 방어 논리를
  '사실관계 → 적용 법리 → 결론(주장)' 순으로 구성하세요.
- 반박: 상대 주장·전제·증거의 허점을 적극 지적하고, 가능하면 판례·법령으로 반론하세요.
- 약점 자기진단: 우리 측 주장의 약한 고리(반박 가능 지점, 입증 부족, 불리한 판례)를
  숨기지 말고 먼저 짚으세요. 그대로 두면 상대가 파고들 지점을 명시하세요.
- 추가 자료·서류 요청: 약점 보완이나 주장 입증에 필요한 자료가 있으면
  '무엇이·왜·어떤 형식으로' 필요한지 구체적으로 요청하세요.
  예) "○○ 주장 입증을 위해 [문서명/기간/발신처]가 필요합니다 — 없으면 해당 주장은 약화됨."
- 균형: 방어에 유리하게 쓰되 사실을 왜곡하지 마세요. 불리한 사실은 인정하되,
  그 영향을 최소화하는 법리·정상참작 논거를 함께 제시하세요.

답변은 한국어로 작성하세요."""


@dataclass
class Answer:
    """질의응답 결과"""
    question: str = ""
    answer: str = ""
    sources: list[dict] = field(default_factory=list)
    chunks_used: int = 0


class QAEngine:
    """RAG 기반 질의응답"""

    def __init__(
        self,
        retriever: Retriever | None = None,
        llm_backend: str = "openai",
    ):
        self.retriever = retriever or Retriever()
        self.llm_backend = llm_backend
        self._llm_fn = None

    def _get_llm_fn(self):
        """LLM 호출 함수 반환"""
        if self._llm_fn:
            return self._llm_fn

        backend = self.llm_backend

        if backend == "auto":
            # 자동 감지: Ollama → Claude → OpenAI
            for try_backend in ["ollama", "claude", "openai"]:
                try:
                    self.llm_backend = try_backend
                    fn = self._get_llm_fn()
                    self.llm_backend = "auto"  # 리셋
                    return fn
                except Exception:
                    continue
            raise RuntimeError("사용 가능한 LLM 없음. Ollama, Claude API, 또는 OpenAI API를 설정하세요.")

        if backend == "ollama":
            import ollama
            ollama.list()  # 연결 테스트
            self._llm_fn = self._call_ollama
            print("[LLM] Ollama")
            return self._llm_fn

        if backend == "claude":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY 없음")
            from anthropic import Anthropic
            self._anthropic = Anthropic(api_key=api_key)
            self._llm_fn = self._call_claude
            print("[LLM] Claude API")
            return self._llm_fn

        if backend == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY 없음")
            from openai import OpenAI
            self._openai = OpenAI(api_key=api_key)
            self._llm_fn = self._call_openai
            print("[LLM] OpenAI API")
            return self._llm_fn

        raise ValueError(f"지원하지 않는 LLM 백엔드: {backend}")

    def _call_ollama(self, system: str, user: str) -> str:
        import ollama
        resp = ollama.chat(
            model="llama3.2",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp["message"]["content"]

    def _call_ollama_stream(self, system: str, user: str):
        import ollama
        stream = ollama.chat(
            model="llama3.2",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        for chunk in stream:
            yield chunk["message"]["content"]

    def _call_claude(self, system: str, user: str) -> str:
        resp = self._anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text

    def _call_claude_stream(self, system: str, user: str):
        with self._anthropic.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    def _call_openai(self, system: str, user: str) -> str:
        resp = self._openai.chat.completions.create(
            model="gpt-5.5",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    def _call_openai_stream(self, system: str, user: str):
        stream = self._openai.chat.completions.create(
            model="gpt-5.5",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    # 회사·방어 자료(문서) 유형별 한글 라벨 — 법령/판례와 구분하기 위함
    _DOC_LABEL = {
        "opinion": "변호인의견서", "precedent_ref": "참고판례정리",
        "defense": "방어논리", "company": "회사정보", "contract": "계약서",
        "notice": "학부모안내", "evidence": "현장증거", "book": "도서·교재",
        "product": "콘텐츠상품", "promo": "브랜드홍보", "blog": "블로그",
        "news": "뉴스", "youtube": "유튜브", "sns": "SNS",
        "research": "업계조사", "reference": "참고자료", "manual": "메모",
    }

    def _build_context(self, chunks: list[Chunk]) -> str:
        """청크를 컨텍스트 문자열로 구성.

        판례/법령(외부 법적 근거)과 회사·방어 자료(우리 측 사실자료)를 실제 유형에
        맞게 라벨링한다. (홍보·교재 문서가 '법령'으로 오표기되던 버그 수정)
        """
        parts = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk.metadata
            stype = chunk.source_type or meta.get("source_type") or ""
            if meta.get("case_number") or meta.get("court_name") or meta.get("case_name"):
                header = (
                    f"[판례 {i}] {meta.get('court_name', '?')} "
                    f"{meta.get('judgment_date', '?')} {meta.get('case_number') or '사건번호미상'}"
                )
            elif meta.get("law_name"):
                header = f"[법령 {i}] {meta.get('law_name', '?')} {meta.get('article_number', '')}".rstrip()
            else:
                # 회사·방어 자료(문서)
                label = self._DOC_LABEL.get(stype, "회사·방어자료")
                title = meta.get("title", "")
                header = f"[{label} {i}] {title}".rstrip()
            parts.append(f"{header}\n{chunk.content}")
        return "\n\n---\n\n".join(parts)

    def _extract_sources(self, chunks: list[Chunk]) -> list[dict]:
        """청크에서 출처 목록 추출"""
        sources = []
        seen = set()
        for chunk in chunks:
            meta = chunk.metadata
            key = meta.get("case_number") or meta.get("article_number") or chunk.id
            if key in seen:
                continue
            seen.add(key)

            if meta.get("case_number"):
                sources.append({
                    "type": "precedent",
                    "case_number": meta.get("case_number", ""),
                    "court_name": meta.get("court_name", ""),
                    "judgment_date": meta.get("judgment_date", ""),
                    "case_name": meta.get("case_name", ""),
                })
            elif meta.get("law_name"):
                sources.append({
                    "type": "statute",
                    "law_name": meta.get("law_name", ""),
                    "article_number": meta.get("article_number", ""),
                    "article_title": meta.get("article_title", ""),
                })
        return sources

    def ask(self, question: str, top_k: int = 5) -> Answer:
        """질의응답"""
        llm_fn = self._get_llm_fn()

        # 관련 청크 검색
        chunks = self.retriever.hybrid_search(question, top_k=top_k)
        if not chunks:
            return Answer(
                question=question,
                answer="관련 자료를 찾을 수 없습니다. 먼저 데이터를 수집하고 인덱싱하세요.",
            )

        # 컨텍스트 구성
        context = self._build_context(chunks)
        user_prompt = f"[참고 자료]\n{context}\n\n[질문]\n{question}"

        # LLM 호출
        answer_text = llm_fn(SYSTEM_PROMPT, user_prompt)

        return Answer(
            question=question,
            answer=answer_text,
            sources=self._extract_sources(chunks),
            chunks_used=len(chunks),
        )

    def ask_stream(self, question: str, top_k: int = 5):
        """스트리밍 질의응답 — (chunks, answer_generator) 반환"""
        self._get_llm_fn()  # 초기화

        chunks = self.retriever.hybrid_search(question, top_k=top_k)
        if not chunks:
            def empty():
                yield "관련 자료를 찾을 수 없습니다."
            return chunks, empty()

        context = self._build_context(chunks)
        user_prompt = f"[참고 자료]\n{context}\n\n[질문]\n{question}"

        # 스트리밍 함수 선택
        if self.llm_backend == "ollama" or (self.llm_backend == "auto" and self._llm_fn == self._call_ollama):
            stream_fn = self._call_ollama_stream
        elif self.llm_backend == "claude" or (self.llm_backend == "auto" and self._llm_fn == self._call_claude):
            stream_fn = self._call_claude_stream
        elif self.llm_backend == "openai" or (self.llm_backend == "auto" and self._llm_fn == self._call_openai):
            stream_fn = self._call_openai_stream
        else:
            # fallback: 일반 호출을 스트리밍처럼
            def fake_stream():
                yield self._llm_fn(SYSTEM_PROMPT, user_prompt)
            return chunks, fake_stream()

        return chunks, stream_fn(SYSTEM_PROMPT, user_prompt)
