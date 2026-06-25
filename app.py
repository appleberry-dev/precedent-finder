"""교육청 고발 방어 디팬스타워 — Streamlit 웹 UI"""

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
    page_title="교육청 고발 방어 디팬스타워",
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
    st.markdown("**LLM**: OpenAI (gpt-5.5)")
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

st.title(":shield: 교육청 고발 방어 디팬스타워")
st.caption("교육청 고발 사건의 방어 측을 지원하는 한국 법률 전문 AI. 판례·법령·회사 자료를 근거로 변호인 의견서·방어 서면 톤으로 답변합니다. 채팅창에 PDF/이미지를 첨부할 수 있습니다.")


# --- 업데이트 내역 ---

LAST_UPDATED = "2026-06-25"

# 최신 항목이 맨 위. 새 업데이트 시 맨 앞에 dict 추가.
UPDATE_LOG = [
    {
        "date": "2026-06-25",
        "items": [
            "**변호인 의견서 초안 v1** 작성 — 수집 자료·판례 기반 (데이터 관리 → "
            ":shield: 의견서·참고자료 탭)",
            "**참고판례 정리** 추가 — 유리(2008도3654 제한해석·2021도16198 시설 엄격해석) / "
            "불리(2011도9013 유아 대상 교습) 구분",
            "**애플베리 교재 자료 적재** — SCIENCE 5·Literacy Sprout 1 (ISBN 등재 도서, "
            "표지·본문 이미지) → '직접 개발·판매하는 도서' 입증",
            "방어 증거 정비 — 사업자등록(동탄=도서 도소매업)·구매계약서·약관·키즈노트·현장사진",
            "벡터 DB 재인덱싱(문서 57건 → 청크 200개)",
        ],
    },
    {
        "date": "2026-06-23",
        "items": [
            "법제처 Open API로 판례 최신화 — 172건 재수집(중복 갱신·신규 추가)",
            "법령 조문 갱신: **학원법 시행령**(별표 포함)·**평생교육법** 신규 수집",
            "핵심 판례 최신 본문 반영 — 스터디카페(2021도16198), 댄스스포츠(2015두48655), "
            "별표 한정(2014도13280·2008도3654), 유아 제외(2012도1268)",
            "벡터 DB 재인덱싱 및 용량 최적화(55MB→36MB)",
        ],
    },
    {
        "date": "2026-04-09",
        "items": [
            "핵심 판례 7건 분석 정리 및 방어전략 문서 열람 페이지 추가",
        ],
    },
]


def render_update_log():
    try:
        prec_count = store.count_precedents()
        stat_count = store.count_statutes()
    except Exception:
        prec_count = stat_count = None
    try:
        doc_count = store.count_documents()
    except Exception:
        doc_count = None

    with st.expander(f":calendar: 데이터 업데이트 내역 (최종 {LAST_UPDATED})", expanded=True):
        if prec_count is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("판례", f"{prec_count}건")
            c2.metric("법령 조문", f"{stat_count}건")
            c3.metric("수집 자료", f"{doc_count}건" if doc_count is not None else "-")
            c4.metric("최종 업데이트", LAST_UPDATED)
        for entry in UPDATE_LOG:
            st.markdown(f"**{entry['date']}**")
            for item in entry["items"]:
                st.markdown(f"- {item}")
        st.caption("출처: 법제처 국가법령정보 Open API (law.go.kr)")


render_update_log()


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
        model="gpt-5.5",
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
