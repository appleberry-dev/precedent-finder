"""판례 파인더 — Streamlit 웹 UI"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import base64
import streamlit as st
from pathlib import Path

# Streamlit Cloud 환경: secrets → 환경변수 매핑
if hasattr(st, "secrets"):
    for key in ("OPENAI_API_KEY", "LAW_API_OC"):
        if key in st.secrets and key not in os.environ:
            os.environ[key] = st.secrets[key]

st.set_page_config(
    page_title="판례 파인더",
    page_icon=":balance_scale:",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --- 초기화 ---

@st.cache_resource
def get_store():
    from precedent_finder.db.store import PrecedentStore
    return PrecedentStore()


@st.cache_resource
def get_chat_store():
    """대화 기록용 DB (쓰기 가능한 경로)"""
    from precedent_finder.db.store import PrecedentStore
    import tempfile
    chat_db = Path(tempfile.gettempdir()) / "precedent_finder_chat.db"
    return PrecedentStore(db_path=chat_db)


def get_qa_engine(llm_backend: str):
    """QAEngine 생성 (캐시하지 않음 — 백엔드 변경 가능)"""
    from precedent_finder.rag.retriever import Retriever
    from precedent_finder.rag.qa import QAEngine
    retriever = Retriever()
    return QAEngine(retriever=retriever, llm_backend=llm_backend)


def extract_pdf_text(uploaded_file) -> str:
    """업로드된 PDF에서 텍스트 추출"""
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(uploaded_file.read())) as pdf:
            texts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
            uploaded_file.seek(0)
            return "\n".join(texts)
    except ImportError:
        # pdfplumber 없으면 안내
        return "[PDF 텍스트 추출 실패: pdfplumber 미설치]"
    except Exception as e:
        return f"[PDF 텍스트 추출 실패: {e}]"


def encode_image_base64(uploaded_file) -> tuple[str, str]:
    """업로드된 이미지를 base64로 인코딩, (base64_str, mime_type) 반환"""
    data = uploaded_file.read()
    uploaded_file.seek(0)
    b64 = base64.b64encode(data).decode("utf-8")
    mime = uploaded_file.type or "image/png"
    return b64, mime


store = get_store()
chat_store = get_chat_store()

# 세션 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "uploaded_files_context" not in st.session_state:
    st.session_state.uploaded_files_context = []


def start_new_conversation():
    """새 대화 시작"""
    st.session_state.messages = []
    st.session_state.conversation_id = None
    st.session_state.uploaded_files_context = []


def load_conversation(conv_id: int):
    """저장된 대화 불러오기"""
    msgs = chat_store.get_conversation_messages(conv_id)
    st.session_state.messages = [
        {"role": m["role"], "content": m["content"], "sources": m.get("sources")}
        for m in msgs
    ]
    st.session_state.conversation_id = conv_id
    st.session_state.uploaded_files_context = []


# --- 사이드바 ---

with st.sidebar:
    st.header("설정")

    llm_backend = "openai"
    st.markdown("**LLM**: OpenAI (gpt-5.4)")

    top_k = st.slider("참고 자료 수", min_value=3, max_value=15, value=5,
                       help="질문 시 GPT에게 넘길 판례/법령 조각 수. 높을수록 답변이 정확하지만 느리고 비용이 증가합니다. 5~7 권장.")

    st.divider()

    # 파일 업로드
    st.header("파일 첨부")
    uploaded_files = st.file_uploader(
        "PDF 또는 이미지를 업로드하세요",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        help="업로드된 파일의 내용이 다음 질문에 포함됩니다.",
    )

    # 업로드된 파일 처리
    if uploaded_files:
        file_contexts = []
        for f in uploaded_files:
            if f.type == "application/pdf":
                text = extract_pdf_text(f)
                file_contexts.append({
                    "type": "pdf",
                    "name": f.name,
                    "text": text,
                })
                st.success(f"PDF: {f.name} ({len(text)}자)")
            elif f.type and f.type.startswith("image/"):
                b64, mime = encode_image_base64(f)
                file_contexts.append({
                    "type": "image",
                    "name": f.name,
                    "base64": b64,
                    "mime": mime,
                })
                st.image(f, caption=f.name, width=200)
        st.session_state.uploaded_files_context = file_contexts
    else:
        st.session_state.uploaded_files_context = []

    st.divider()

    # 데이터 현황
    st.header("데이터 현황")
    try:
        prec_count = store.count_precedents()
        stat_count = store.count_statutes()

        col1, col2 = st.columns(2)
        col1.metric("판례", f"{prec_count}건")
        col2.metric("법령 조문", f"{stat_count}건")

        pdf_dir = Path("data/pdfs")
        pdf_count = len(list(pdf_dir.glob("*.pdf"))) if pdf_dir.exists() else 0
        chroma_exists = Path("data/chroma_db").exists()

        col3, col4 = st.columns(2)
        col3.metric("PDF", f"{pdf_count}개")
        col4.metric("벡터 DB", "O" if chroma_exists else "X")
    except Exception as e:
        st.warning(f"DB 연결 실패: {e}")

    st.divider()

    # 대화 기록
    st.header("대화 기록")

    if st.button("새 대화", use_container_width=True):
        start_new_conversation()
        st.rerun()

    try:
        conversations = chat_store.list_conversations(limit=20)
        for conv in conversations:
            title = conv["title"] or f"대화 #{conv['id']}"
            created = conv["created_at"][:16] if conv["created_at"] else ""

            col_title, col_del = st.columns([4, 1])
            with col_title:
                if st.button(f"{title}\n{created}", key=f"conv_{conv['id']}", use_container_width=True):
                    load_conversation(conv["id"])
                    st.rerun()
            with col_del:
                if st.button(":wastebasket:", key=f"del_{conv['id']}"):
                    chat_store.delete_conversation(conv["id"])
                    if st.session_state.conversation_id == conv["id"]:
                        start_new_conversation()
                    st.rerun()
    except Exception:
        pass


# --- 메인: 채팅 ---

st.title(":balance_scale: 판례 파인더")
st.caption("수집된 판례와 법령을 기반으로 법률 질의에 답변합니다.")


def render_sources(sources):
    """참고 자료 렌더링"""
    if not sources:
        return
    with st.expander("참고 자료", expanded=False):
        for src in sources:
            if src["type"] == "precedent":
                st.markdown(f"- **{src.get('court_name', '?')}** {src.get('judgment_date', '?')} "
                            f"[{src.get('case_number', '?')}] {src.get('case_name', '')[:60]}")
            else:
                st.markdown(f"- **{src.get('law_name', '?')}** {src.get('article_number', '?')} "
                            f"{src.get('article_title', '')}")


def build_prompt_with_files(question: str, file_contexts: list[dict]) -> str:
    """질문에 업로드된 파일 내용을 포함한 프롬프트 생성"""
    if not file_contexts:
        return question

    parts = [question, "\n\n--- 첨부 파일 ---"]
    for fc in file_contexts:
        if fc["type"] == "pdf":
            text = fc["text"][:8000]  # 토큰 제한
            parts.append(f"\n[PDF: {fc['name']}]\n{text}")
        elif fc["type"] == "image":
            parts.append(f"\n[이미지: {fc['name']}] (아래 이미지 참조)")
    return "\n".join(parts)


def call_openai_with_images(system_prompt: str, user_text: str,
                            image_contexts: list[dict]):
    """이미지가 포함된 경우 OpenAI Vision API로 스트리밍 호출"""
    from openai import OpenAI
    client = OpenAI()

    content = [{"type": "text", "text": user_text}]
    for img in image_contexts:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{img['mime']};base64,{img['base64']}",
                "detail": "high",
            },
        })

    stream = client.chat.completions.create(
        model="gpt-5.4-2026-03-05",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


# 히스토리 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        render_sources(msg.get("sources"))

# 입력
if prompt := st.chat_input("질문을 입력하세요 (예: 무등록 학원 운영 시 처벌은?)"):
    file_contexts = st.session_state.uploaded_files_context
    has_images = any(fc["type"] == "image" for fc in file_contexts)
    has_files = len(file_contexts) > 0

    # 사용자 메시지 표시
    display_text = prompt
    if has_files:
        file_names = [fc["name"] for fc in file_contexts]
        display_text = f"{prompt}\n\n> 첨부: {', '.join(file_names)}"

    st.session_state.messages.append({"role": "user", "content": display_text})
    with st.chat_message("user"):
        st.markdown(display_text)

    # 새 대화면 conversation 생성
    if st.session_state.conversation_id is None:
        title = prompt[:30] + ("..." if len(prompt) > 30 else "")
        st.session_state.conversation_id = chat_store.create_conversation(title)

    chat_store.add_message(st.session_state.conversation_id, "user", display_text)

    # 답변 생성
    with st.chat_message("assistant"):
        try:
            qa = get_qa_engine(llm_backend)

            if not Path("data/chroma_db").exists():
                answer_text = "벡터 DB가 없습니다. 먼저 터미널에서 `precedent-finder index`를 실행해주세요."
                st.warning(answer_text)
                st.session_state.messages.append({"role": "assistant", "content": answer_text})
                chat_store.add_message(st.session_state.conversation_id, "assistant", answer_text)
            else:
                # 파일 내용을 질문에 포함
                full_prompt = build_prompt_with_files(prompt, file_contexts)

                # RAG 검색
                chunks, stream = qa.ask_stream(full_prompt, top_k=top_k)

                # 이미지가 있으면 Vision API로 대체
                if has_images:
                    from precedent_finder.rag.qa import SYSTEM_PROMPT
                    context = qa._build_context(chunks)
                    user_text = f"[참고 자료]\n{context}\n\n[질문]\n{full_prompt}"
                    image_contexts = [fc for fc in file_contexts if fc["type"] == "image"]
                    stream = call_openai_with_images(SYSTEM_PROMPT, user_text, image_contexts)

                answer_text = st.write_stream(stream)

                # 출처
                sources = qa._extract_sources(chunks)
                render_sources(sources)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer_text,
                    "sources": sources,
                })
                chat_store.add_message(
                    st.session_state.conversation_id, "assistant",
                    answer_text, sources=sources,
                )

        except Exception as e:
            error_msg = f"오류가 발생했습니다: {e}"
            st.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
            chat_store.add_message(st.session_state.conversation_id, "assistant", error_msg)
