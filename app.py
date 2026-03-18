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
    from precedent_finder.db.store import PrecedentStore
    import tempfile
    chat_db = Path(tempfile.gettempdir()) / "precedent_finder_chat.db"
    return PrecedentStore(db_path=chat_db)


def get_qa_engine(llm_backend: str):
    from precedent_finder.rag.retriever import Retriever
    from precedent_finder.rag.qa import QAEngine
    retriever = Retriever()
    return QAEngine(retriever=retriever, llm_backend=llm_backend)


def extract_pdf_text(file_data: bytes) -> str:
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(file_data)) as pdf:
            texts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
            return "\n".join(texts)
    except ImportError:
        return "[PDF 텍스트 추출 실패: pdfplumber 미설치]"
    except Exception as e:
        return f"[PDF 텍스트 추출 실패: {e}]"


store = get_store()
chat_store = get_chat_store()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None


def start_new_conversation():
    st.session_state.messages = []
    st.session_state.conversation_id = None


def load_conversation(conv_id: int):
    msgs = chat_store.get_conversation_messages(conv_id)
    st.session_state.messages = [
        {"role": m["role"], "content": m["content"], "sources": m.get("sources")}
        for m in msgs
    ]
    st.session_state.conversation_id = conv_id


# --- 사이드바 ---

with st.sidebar:
    st.header("설정")
    llm_backend = "openai"
    st.markdown("**LLM**: OpenAI (gpt-5.4)")
    top_k = st.slider("참고 자료 수", min_value=3, max_value=15, value=5,
                       help="질문 시 GPT에게 넘길 판례/법령 조각 수. 5~7 권장.")

    st.divider()
    st.header("데이터 현황")
    try:
        prec_count = store.count_precedents()
        stat_count = store.count_statutes()
        col1, col2 = st.columns(2)
        col1.metric("판례", f"{prec_count}건")
        col2.metric("법령 조문", f"{stat_count}건")
        chroma_exists = Path("data/chroma_db").exists()
        col3, col4 = st.columns(2)
        col3.metric("벡터 DB", "O" if chroma_exists else "X")
    except Exception as e:
        st.warning(f"DB 연결 실패: {e}")

    st.divider()
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
st.caption("수집된 판례와 법령을 기반으로 법률 질의에 답변합니다. 채팅창에 PDF/이미지를 첨부할 수 있습니다.")


def render_sources(sources):
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


def call_openai_with_images(system_prompt, user_text, image_list):
    from openai import OpenAI
    client = OpenAI()
    content = [{"type": "text", "text": user_text}]
    for b64, mime in image_list:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
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
        if msg.get("images"):
            for img in msg["images"]:
                st.image(f"data:{img['mime']};base64,{img['b64']}", width=300)
        render_sources(msg.get("sources"))


# 채팅 입력 (파일 첨부 지원)
chat_input = st.chat_input(
    "질문을 입력하세요 (클립 아이콘으로 PDF/이미지 첨부 가능)",
    accept_file="multiple",
    file_type=["pdf", "png", "jpg", "jpeg", "webp"],
)

if chat_input:
    prompt = chat_input.text or ""
    attached_files = chat_input.files or []

    # 첨부 파일 처리
    pdf_texts = []
    image_list = []       # [(b64, mime), ...]
    image_history = []    # 히스토리 저장용
    file_names = []

    for f in attached_files:
        file_data = f.read()
        file_names.append(f.name)

        if f.type == "application/pdf":
            text = extract_pdf_text(file_data)
            pdf_texts.append((f.name, text))
        elif f.type and f.type.startswith("image/"):
            b64 = base64.b64encode(file_data).decode("utf-8")
            mime = f.type
            image_list.append((b64, mime))
            image_history.append({"b64": b64, "mime": mime})

    # 사용자 메시지 구성
    display_text = prompt
    if file_names:
        display_text = f"{prompt}\n\n> 첨부: {', '.join(file_names)}" if prompt else f"> 첨부: {', '.join(file_names)}"

    if not prompt and not file_names:
        st.stop()

    user_msg = {"role": "user", "content": display_text}
    if image_history:
        user_msg["images"] = image_history
    st.session_state.messages.append(user_msg)

    with st.chat_message("user"):
        st.markdown(display_text)
        for img in image_history:
            st.image(f"data:{img['mime']};base64,{img['b64']}", width=300)

    # 대화 생성
    if st.session_state.conversation_id is None:
        title_text = prompt or file_names[0] if file_names else "새 대화"
        title = title_text[:30] + ("..." if len(title_text) > 30 else "")
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
                # 질문에 PDF 텍스트 포함
                full_prompt = prompt
                if pdf_texts:
                    pdf_parts = "\n\n--- 첨부 PDF ---"
                    for name, text in pdf_texts:
                        pdf_parts += f"\n[{name}]\n{text[:8000]}"
                    full_prompt = f"{prompt}\n{pdf_parts}" if prompt else pdf_parts
                if image_list:
                    full_prompt += "\n\n(첨부된 이미지도 함께 분석해주세요)"

                # RAG 검색
                chunks, stream = qa.ask_stream(full_prompt or "첨부된 파일을 분석해주세요", top_k=top_k)

                # 이미지가 있으면 Vision API로 대체
                if image_list:
                    from precedent_finder.rag.qa import SYSTEM_PROMPT
                    context = qa._build_context(chunks)
                    user_text = f"[참고 자료]\n{context}\n\n[질문]\n{full_prompt}"
                    stream = call_openai_with_images(SYSTEM_PROMPT, user_text, image_list)

                answer_text = st.write_stream(stream)

                sources = qa._extract_sources(chunks)
                render_sources(sources)

                st.session_state.messages.append({
                    "role": "assistant", "content": answer_text, "sources": sources,
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
