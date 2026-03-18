"""판례 파인더 — Streamlit 웹 UI"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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


def get_qa_engine(llm_backend: str):
    """QAEngine 생성 (캐시하지 않음 — 백엔드 변경 가능)"""
    from precedent_finder.rag.retriever import Retriever
    from precedent_finder.rag.qa import QAEngine
    retriever = Retriever()
    return QAEngine(retriever=retriever, llm_backend=llm_backend)


store = get_store()

# 세션 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None


def start_new_conversation():
    """새 대화 시작"""
    st.session_state.messages = []
    st.session_state.conversation_id = None


def load_conversation(conv_id: int):
    """저장된 대화 불러오기"""
    msgs = store.get_conversation_messages(conv_id)
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
                       help="질문 시 GPT에게 넘길 판례/법령 조각 수. 높을수록 답변이 정확하지만 느리고 비용이 증가합니다. 5~7 권장.")

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
        conversations = store.list_conversations(limit=20)
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
                    store.delete_conversation(conv["id"])
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


# 히스토리 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        render_sources(msg.get("sources"))

# 입력
if prompt := st.chat_input("질문을 입력하세요 (예: 무등록 학원 운영 시 처벌은?)"):
    # 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 새 대화면 conversation 생성
    if st.session_state.conversation_id is None:
        # 첫 질문의 앞 30자를 제목으로
        title = prompt[:30] + ("..." if len(prompt) > 30 else "")
        st.session_state.conversation_id = store.create_conversation(title)

    # 사용자 메시지 DB 저장
    store.add_message(st.session_state.conversation_id, "user", prompt)

    # 답변 생성
    with st.chat_message("assistant"):
        try:
            qa = get_qa_engine(llm_backend)

            # 벡터 DB 존재 확인
            if not Path("data/chroma_db").exists():
                answer_text = "벡터 DB가 없습니다. 먼저 터미널에서 `precedent-finder index`를 실행해주세요."
                st.warning(answer_text)
                st.session_state.messages.append({"role": "assistant", "content": answer_text})
                store.add_message(st.session_state.conversation_id, "assistant", answer_text)
            else:
                # 스트리밍 응답
                chunks, stream = qa.ask_stream(prompt, top_k=top_k)
                answer_text = st.write_stream(stream)

                # 출처
                sources = qa._extract_sources(chunks)
                render_sources(sources)

                # 세션 저장
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer_text,
                    "sources": sources,
                })

                # DB 저장
                store.add_message(
                    st.session_state.conversation_id, "assistant",
                    answer_text, sources=sources,
                )

        except Exception as e:
            error_msg = f"오류가 발생했습니다: {e}"
            st.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
            store.add_message(st.session_state.conversation_id, "assistant", error_msg)
