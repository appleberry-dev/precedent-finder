"""질의응답 엔진 — RAG 기반 LLM 질의"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv()

from .chunker import Chunk
from .retriever import Retriever


SYSTEM_PROMPT = """당신은 한국 법률 전문 AI입니다.
아래 판례와 법령 자료를 참고하여 질문에 답변하세요.

규칙:
- 반드시 근거가 되는 판례 번호(예: 2015두48655)나 법령 조문(예: 학원법 제2조)을 인용하세요.
- 자료에 없는 내용은 추측하지 말고 "확인된 자료에서 찾을 수 없습니다"라고 답하세요.
- 형량, 벌금 등 처벌 수위는 판례 원문을 그대로 인용하세요.
- 답변은 한국어로 작성하세요."""


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
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    def _call_openai_stream(self, system: str, user: str):
        stream = self._openai.chat.completions.create(
            model="gpt-4o-mini",
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

    def _build_context(self, chunks: list[Chunk]) -> str:
        """청크를 컨텍스트 문자열로 구성"""
        parts = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk.metadata
            if chunk.source_type == "precedent" or meta.get("case_number"):
                header = f"[판례 {i}] {meta.get('court_name', '?')} {meta.get('judgment_date', '?')} {meta.get('case_number', '?')}"
            else:
                header = f"[법령 {i}] {meta.get('law_name', '?')} {meta.get('article_number', '?')}"
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
