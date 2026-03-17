"""데이터 관리 페이지"""

import streamlit as st
import pandas as pd

st.set_page_config(page_title="데이터 관리", page_icon=":card_file_box:", layout="wide")
st.title(":card_file_box: 데이터 관리")


@st.cache_resource
def get_store():
    from precedent_finder.db.store import PrecedentStore
    return PrecedentStore()


store = get_store()

# --- 탭 ---
tab_prec, tab_statute, tab_search = st.tabs(["판례", "법령", "검색"])

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
