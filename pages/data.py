"""데이터 관리 페이지"""

import json
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import streamlit as st
import pandas as pd

st.set_page_config(page_title="데이터 관리", page_icon=":card_file_box:", layout="wide")
st.title(":card_file_box: 데이터 관리")


# 스키마 변경 시 버전을 올리면 cache_resource가 자동 갱신됨(stale store 방지)
STORE_SCHEMA_VERSION = "2026-06-25c"


@st.cache_resource
def get_store(schema_version: str = STORE_SCHEMA_VERSION):
    from precedent_finder.db.store import PrecedentStore
    return PrecedentStore()


store = get_store()

# --- 공통 라벨/렌더 ---
TYPE_LABELS = {
    "opinion": ":scales: 변호인 의견서",
    "precedent_ref": ":mag: 참고판례 정리",
    "defense": ":shield: 방어 논리",
    "company": ":office: 회사 기초정보",
    "contract": ":page_facing_up: 계약서",
    "notice": ":bell: 학부모 안내",
    "evidence": ":camera_with_flash: 현장 증거",
    "book": ":books: 도서·서지(ISBN)",
    "product": ":package: 콘텐츠 상품",
    "promo": ":star2: 브랜드 홍보",
    "blog": ":memo: 블로그",
    "news": ":newspaper: 뉴스 기사",
    "youtube": ":tv: 유튜브",
    "sns": ":camera: SNS",
    "manual": ":pushpin: 메모",
    "research": ":mag: 업계조사",
    "reference": ":books: 참고자료",
    "web": ":globe_with_meridians: 웹",
}
# 마크다운으로 렌더할 유형 (그 외는 일반 텍스트)
_MD_TYPES = {"opinion", "precedent_ref", "defense", "company"}


def render_doc_body(d):
    """문서 한 건의 본문(링크·이미지·내용)을 렌더한다."""
    stype = d.get("source_type", "web")
    if d.get("url"):
        st.markdown(f":link: [원문 보기]({d['url']})")

    meta = {}
    if d.get("metadata"):
        try:
            meta = json.loads(d["metadata"])
        except (ValueError, TypeError):
            meta = {}

    # 도서: 이미지 갤러리(표지+본문) / 그 외: 단일 이미지
    gallery = [p for p in meta.get("image_paths", []) if Path(p).exists()]
    if gallery:
        cols = st.columns(3)
        for i, p in enumerate(gallery):
            cols[i % 3].image(p, use_container_width=True)
    else:
        img_path = meta.get("image_path", "")
        if img_path and Path(img_path).exists():
            st.image(img_path, use_container_width=True)

    content = d.get("content", "")
    if stype in _MD_TYPES:
        st.markdown(content)
    else:
        st.text(content[:5000] + ("..." if len(content) > 5000 else ""))


# --- 탭 ---
tab_opinion, tab_company, tab_prec, tab_statute, tab_search = st.tabs(
    [":shield: 의견서·참고자료", "수집 자료", "판례", "법령", "검색"]
)

# --- 의견서·참고자료 탭 ---
with tab_opinion:
    docs = store.list_documents()
    opinions = [d for d in docs if d.get("source_type") == "opinion"]
    refs = [d for d in docs if d.get("source_type") == "precedent_ref"]

    st.subheader(":scales: 변호인 의견서 초안")
    st.caption("수집 자료(사업자등록·계약서·약관·키즈노트·현장사진·ISBN 교재)와 판례를 토대로 작성된 초안입니다.")
    if not opinions:
        st.info("아직 작성된 의견서가 없습니다.")
    for d in sorted(opinions, key=lambda x: x.get("id", 0), reverse=True):
        title = d.get("title") or "(제목 없음)"
        with st.expander(f":scales: {title}", expanded=True):
            render_doc_body(d)

    st.divider()
    st.subheader(":mag: 참고판례·법령 정리")
    st.caption("의견서가 인용하는 핵심 판례를 유리/불리로 정리했습니다. (원문은 '판례' 탭에서 사건번호로 조회)")
    if not refs:
        st.info("아직 정리된 참고판례가 없습니다.")
    for d in refs:
        title = d.get("title") or "(제목 없음)"
        with st.expander(f":mag: {title}", expanded=True):
            render_doc_body(d)

# --- 판례 탭 ---
with tab_prec:
    precedents = store.list_precedents()

    if not precedents:
        st.info("수집된 판례가 없습니다. 먼저 크롤링을 실행하세요.")
    else:
        # 필터
        col1, col2 = st.columns(2)
        courts = sorted(set(p["court_name"] for p in precedents if p["court_name"]))
        with col1:
            court_filter = st.selectbox("법원", ["전체"] + courts)
        with col2:
            sort_by = st.selectbox("정렬", ["선고일 (최신순)", "선고일 (오래된순)", "사건번호"])

        # 필터링
        filtered = precedents
        if court_filter != "전체":
            filtered = [p for p in filtered if p["court_name"] == court_filter]

        # 정렬
        if sort_by == "선고일 (오래된순)":
            filtered.sort(key=lambda x: x.get("judgment_date", ""))
        elif sort_by == "사건번호":
            filtered.sort(key=lambda x: x.get("case_number", ""))

        st.caption(f"총 {len(filtered)}건")

        # 판례 목록 — 각 항목을 expander로 표시 (클릭하면 상세)
        for i, prec in enumerate(filtered):
            case_num = prec.get("case_number", "?")
            case_name = prec.get("case_name", "제목 없음")[:70]
            court = prec.get("court_name", "?")
            date = prec.get("judgment_date", "?")
            jtype = prec.get("judgment_type", "")

            header = f"{court} {date} [{case_num}] {case_name}"

            with st.expander(header, expanded=False):
                # 메타 정보
                col1, col2, col3 = st.columns(3)
                col1.markdown(f"**법원**: {court}")
                col2.markdown(f"**선고일**: {date}")
                col3.markdown(f"**판결유형**: {jtype}")

                if prec.get("source_url"):
                    st.markdown(f":link: [원문 보기]({prec['source_url']})")

                st.divider()

                # 본문 섹션들
                for field, label in [
                    ("issues", "판시사항"),
                    ("summary", "판결요지"),
                    ("reference_articles", "참조조문"),
                    ("reference_cases", "참조판례"),
                    ("full_text", "판례내용"),
                ]:
                    content = prec.get(field, "")
                    if content:
                        st.markdown(f"**{label}**")
                        st.text(content)
                        st.markdown("---")

# --- 법령 탭 ---
with tab_statute:
    statutes = store.list_statutes()

    if not statutes:
        st.info("수집된 법령이 없습니다. `precedent-finder crawl --source statutes` 를 실행하세요.")
    else:
        laws = sorted(set(s["law_name"] for s in statutes))
        law_filter = st.selectbox("법령", ["전체"] + laws)

        filtered_stat = statutes
        if law_filter != "전체":
            filtered_stat = [s for s in filtered_stat if s["law_name"] == law_filter]

        st.caption(f"총 {len(filtered_stat)}개 조문")

        for s in filtered_stat:
            art_num = s.get("article_number", "")
            art_title = s.get("article_title", "")
            header = f"{art_num} {art_title}" if art_title else art_num

            with st.expander(header):
                st.text(s.get("content", ""))

# --- 회사정보·자료 탭 ---
with tab_company:
    documents = store.list_documents()

    if not documents:
        st.info(
            "수집된 회사 자료가 없습니다.\n\n"
            "`precedent-finder crawl-company` (홈페이지+블로그) 또는 "
            "`precedent-finder add-url <URL> --type news` 로 수집하세요."
        )
    else:
        # 의견서·참고판례는 전용 탭에서 표시 → 여기서는 제외
        documents = [d for d in documents if d.get("source_type") not in ("opinion", "precedent_ref")]

        # 유형별 건수 요약
        counts = {}
        for d in documents:
            counts[d.get("source_type", "web")] = counts.get(d.get("source_type", "web"), 0) + 1
        summary = " · ".join(f"{TYPE_LABELS.get(t, t)} {c}건" for t, c in counts.items())
        st.caption(f"총 {len(documents)}건  |  {summary}")

        # 유형 필터 (방어·회사정보를 앞으로)
        _order = {"defense": 0, "company": 1, "contract": 2, "notice": 3,
                  "evidence": 4, "book": 5, "product": 6, "promo": 7}
        types = sorted(counts.keys(), key=lambda t: (_order.get(t, 2), t))
        type_filter = st.selectbox(
            "자료 유형",
            ["전체"] + types,
            format_func=lambda t: "전체" if t == "전체" else TYPE_LABELS.get(t, t),
        )

        shown = documents if type_filter == "전체" else [d for d in documents if d.get("source_type") == type_filter]

        # 방어 논리·회사 기초정보를 항상 위로
        shown = sorted(shown, key=lambda d: (_order.get(d.get("source_type"), 2), d.get("id", 0)))

        for d in shown:
            stype = d.get("source_type", "web")
            badge = TYPE_LABELS.get(stype, stype)
            title = d.get("title") or "(제목 없음)"
            pub = d.get("published_date", "")
            header = f"{badge}  ·  {title[:70]}"
            if pub:
                header += f"  ·  {pub[:16]}"

            with st.expander(header, expanded=(stype in ("defense", "company"))):
                render_doc_body(d)


# --- 검색 탭 ---
with tab_search:
    query = st.text_input("키워드 검색", placeholder="학원, 교습소, 과외교습...")

    if query:
        results = store.search_precedents(query)
        st.caption(f"'{query}' 검색 결과: {len(results)}건")

        for i, prec in enumerate(results, 1):
            case_num = prec.get("case_number", "?")
            case_name = prec.get("case_name", "")[:60]
            court = prec.get("court_name", "?")
            date = prec.get("judgment_date", "?")

            with st.expander(f"{i}. {court} {date} [{case_num}] {case_name}"):
                # 메타
                st.markdown(f"**법원**: {court} | **선고일**: {date} | **판결유형**: {prec.get('judgment_type', '')}")

                if prec.get("source_url"):
                    st.markdown(f":link: [원문 보기]({prec['source_url']})")

                st.divider()

                for field, label in [
                    ("issues", "판시사항"),
                    ("summary", "판결요지"),
                    ("reference_articles", "참조조문"),
                    ("full_text", "판례내용"),
                ]:
                    content = prec.get(field, "")
                    if content:
                        st.markdown(f"**{label}**")
                        st.text(content)
                        st.markdown("---")
