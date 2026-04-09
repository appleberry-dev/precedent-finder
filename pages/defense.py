"""방어 전략 문서 열람 페이지"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path
import streamlit as st

if hasattr(st, "secrets"):
    for key in ("OPENAI_API_KEY", "LAW_API_OC"):
        if key in st.secrets and key not in os.environ:
            os.environ[key] = st.secrets[key]

st.set_page_config(page_title="방어 전략 문서", page_icon=":shield:", layout="wide")
st.title(":shield: 방어 전략 문서")
st.caption("교육청 무허가교습 고발 대응을 위한 법적 분석 자료")

DOCS_DIR = Path(__file__).parent.parent / "docs"


@st.cache_resource
def get_store():
    from precedent_finder.db.store import PrecedentStore
    return PrecedentStore()


def read_md(filename: str) -> str:
    path = DOCS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"파일을 찾을 수 없습니다: {filename}"


store = get_store()

# --- 탭 구성 ---
tab_overview, tab_precedents, tab_strategy, tab_db, tab_statutes = st.tabs([
    "📋 사건 개요",
    "⚖️ 핵심 판례 분석",
    "🛡️ 방어 전략",
    "🗄️ 전체 판례 DB",
    "📜 관련 법령",
])

# ─── 탭1: 사건 개요 ───
with tab_overview:
    content = read_md("case-context.md")

    # 사실관계 / 핵심쟁점 / 관련법령 섹션만 추출해서 표시
    st.markdown(content)


# ─── 탭2: 핵심 판례 분석 ───
with tab_precedents:
    content = read_md("key-precedents.md")
    st.markdown(content)

    st.divider()
    st.subheader("핵심 판례 원문 확인")

    KEY_CASES = {
        "2021도16198": ("대법원 2023.2.2", "스터디카페 무죄 — 엄격 해석 원칙", "유리"),
        "2014도13280": ("대법원 2017.2.9", "학원은 별표 2 교습과정에 한정", "유리"),
        "2008도3654":  ("대법원 2008.7.24", "별표 미해당 활동 → 등록 불요", "유리"),
        "2012도1268":  ("대법원 2013.12.26", "유아는 과외교습 대상 아님", "유리"),
        "2015두48655": ("대법원 2018.6.21", "별표 해석 불명확 → 기본권 침해 불허", "참조"),
        "2006도2264":  ("대법원 2007.12.14", "실질 판단 — 주의 필요", "불리"),
        "2004도6717":  ("대법원 2004.12.10", "10인·30일 요건 해석 — 주의 필요", "불리"),
    }

    tag_color = {"유리": "green", "참조": "blue", "불리": "red"}

    for case_num, (date, desc, tag) in KEY_CASES.items():
        color = tag_color[tag]
        label = f":{color}[{tag}] **{date}** [{case_num}] {desc}"
        with st.expander(label, expanded=False):
            prec = store.search_precedents(case_num)
            if prec:
                p = prec[0]
                col1, col2, col3 = st.columns(3)
                col1.markdown(f"**법원**: {p.get('court_name','?')}")
                col2.markdown(f"**선고일**: {p.get('judgment_date','?')}")
                col3.markdown(f"**사건유형**: {p.get('case_type','?')}")

                if p.get("source_url"):
                    st.markdown(f"[원문 보기]({p['source_url']})")

                st.divider()
                for field, label_text in [
                    ("issues", "판시사항"),
                    ("summary", "판결요지"),
                    ("reference_articles", "참조조문"),
                    ("full_text", "판례내용"),
                ]:
                    content_val = p.get(field, "")
                    if content_val:
                        st.markdown(f"**{label_text}**")
                        st.text_area("", value=content_val, height=200,
                                     key=f"{case_num}_{field}", disabled=True)
            else:
                st.warning("DB에서 해당 판례를 찾을 수 없습니다.")


# ─── 탭3: 방어 전략 ───
with tab_strategy:
    st.header("4단계 방어 전략")

    st.markdown("""
    > **기본 원칙**: 형벌 법규는 **엄격 해석** (대법원 2021도16198 명시)
    > 피고인에게 불리한 확대해석은 죄형법정주의 위반
    """)

    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.subheader("1차 방어 — 구성요건 불해당 ⭐ 가장 강력")
            st.markdown("""
            **핵심 주장**: 체험활동은 학원법상 "교습"에 해당하지 않는다

            - 서적 판매 사업장이지, 교습 시설이 아님
            - 체험활동 = 서적 구매에 부수된 서비스 (독립된 교습 아님)
            - 정규 교습과정(커리큘럼·시간표·수강료) 없음
            - 시행령 [별표 2] 교습과정 목록에 해당하는 활동 아님

            **근거 판례**
            - `대법원 2008도3654` — 별표 미해당 → 무죄
            - `대법원 2014도13280` — 등록 대상은 별표 한정
            - `대법원 2021도16198` — 엄격 해석 원칙
            """)

        with st.container(border=True):
            st.subheader("3차 방어 — 죄형법정주의 / 엄격 해석")
            st.markdown("""
            **핵심 주장**: 체험활동을 "교습"으로 확대 해석 = 죄형법정주의 위반

            - 학원법 제22조는 형사처벌 조항 → 엄격 해석 의무
            - 시행령 별표에 없는 활동까지 확대 적용 불가
            - 불명확한 구성요건으로 형사처벌 불허 (명확성 원칙)

            **근거 판례**
            - `대법원 2021도16198` — 엄격 해석 원칙 명시
            - `대법원 2015두48655` — 별표 불명확 적용 = 기본권 침해
            """)

    with col2:
        with st.container(border=True):
            st.subheader("2차 방어 — 학원/교습소 정의 불해당")
            st.markdown("""
            **핵심 주장**: 설령 "교습"이라 하더라도, 학원·교습소 요건 미충족

            **학원 요건 불충족**
            - 동시 10인 이상 교습 시설 아님 (학원법 §2①, 시행령 §2②)
            - 30일 이상 교습과정 없음 (비정기 체험)
            - 교습과정의 반복으로 30일 성립 안 됨

            **교습소 요건 불충족**
            - 유아 대상이면 "과외교습" 정의에서 제외 (§2④)
            - 학부모 대상이면 과외교습 정의 해당 안 됨

            **근거 판례**
            - `대법원 2012도1268` — 유아 제외
            - `대법원 2004도6717` — 10인·30일 요건 해석
            """)

        with st.container(border=True):
            st.subheader("4차 방어 — 법률의 착오 (형법 §16)")
            st.markdown("""
            **핵심 주장**: 학원법 적용 대상이라는 인식이 없었음 (고의 없음)

            - 서적 판매업으로 인식하여 운영
            - 학원·교습소에 해당한다는 인식 없었음
            - 형법 제16조: 자기 행위가 법령에 의해 죄가 되지 않는다고 오인한 경우, 정당한 이유가 있으면 처벌 불가

            **실무 활용**
            - 1~3차 방어가 받아들여지지 않을 경우 보충적 활용
            - 별표 해석의 불명확성이 오인의 "정당한 이유"가 될 수 있음
            """)

    st.divider()
    st.subheader("교육청 예상 반론 및 재반박")

    with st.expander("\"서적 판매는 형식이고 실질은 교습소\" (2006도2264 원용)", expanded=False):
        st.markdown("""
        **교육청 주장**: 형식이 서점이라도 실질적으로 교습을 하면 학원법 적용

        **재반박**:
        1. `2006도2264` 사건은 10인 이상·30일 이상 **정규 교습**을 전제로 함
        2. 우리 사건은 비정기 체험활동으로 정규 교습과정 자체가 없음
        3. 시행령 별표에 없는 활동 → 실질 판단 전에 구성요건 불해당
        4. 엄격 해석 원칙상 "실질 유사"만으로 처벌 확장 불가
        """)

    with st.expander("\"반복 체험 = 30일 이상 교습과정\" (2004도6717 원용)", expanded=False):
        st.markdown("""
        **교육청 주장**: 반복적 체험활동이 누적 30일 이상이면 학원

        **재반박**:
        1. 30일 요건의 "반복"은 동일 교습과정이 반복되는 것을 의미
        2. 매번 다른 내용의 체험활동은 동일 교습과정의 반복이 아님
        3. 비정기적·비연속적 참여는 30일 요건 미충족
        4. 참여자별로 독립적이므로 연속성 없음
        """)


# ─── 탭4: 전체 판례 DB ───
with tab_db:
    col_filter1, col_filter2, col_filter3 = st.columns(3)

    precedents = store.list_precedents()

    courts = sorted(set(p["court_name"] for p in precedents if p.get("court_name")))
    with col_filter1:
        court_filter = st.selectbox("법원 필터", ["전체"] + courts, key="db_court")
    with col_filter2:
        keyword_filter = st.text_input("키워드 필터", placeholder="학원, 교습소...", key="db_keyword")
    with col_filter3:
        sort_by = st.selectbox("정렬", ["선고일 (최신순)", "선고일 (오래된순)"], key="db_sort")

    filtered = precedents
    if court_filter != "전체":
        filtered = [p for p in filtered if p.get("court_name") == court_filter]
    if keyword_filter:
        kw = keyword_filter.lower()
        filtered = [
            p for p in filtered
            if kw in (p.get("case_name", "") + p.get("issues", "") + p.get("summary", "")).lower()
        ]

    if sort_by == "선고일 (오래된순)":
        filtered.sort(key=lambda x: x.get("judgment_date", ""))
    else:
        filtered.sort(key=lambda x: x.get("judgment_date", ""), reverse=True)

    st.caption(f"총 **{len(filtered)}건** / 전체 {len(precedents)}건")

    for prec in filtered:
        case_num = prec.get("case_number", "번호미상")
        case_name = prec.get("case_name", "제목 없음")[:60]
        court = prec.get("court_name") or "법원미상"
        date = (prec.get("judgment_date") or "?")[:10]

        header = f"**{court}** {date} `{case_num}` {case_name}"

        with st.expander(header, expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**법원**: {court}")
            c2.markdown(f"**선고일**: {date}")
            c3.markdown(f"**판결유형**: {prec.get('judgment_type','')}")

            if prec.get("source_url"):
                st.markdown(f"[원문 보기]({prec['source_url']})")

            st.divider()
            for field, label_text in [
                ("issues", "판시사항"),
                ("summary", "판결요지"),
                ("reference_articles", "참조조문"),
                ("full_text", "판례내용"),
            ]:
                val = prec.get(field, "")
                if val:
                    st.markdown(f"**{label_text}**")
                    st.text_area("", value=val, height=150,
                                 key=f"db_{prec.get('id','')}_{field}", disabled=True)


# ─── 탭5: 관련 법령 ───
with tab_statutes:
    statutes = store.list_statutes()

    laws = sorted(set(s["law_name"] for s in statutes if s.get("law_name")))
    law_filter = st.selectbox("법령 선택", ["전체"] + laws, key="stat_law")

    filtered_stat = statutes
    if law_filter != "전체":
        filtered_stat = [s for s in filtered_stat if s.get("law_name") == law_filter]

    st.caption(f"총 **{len(filtered_stat)}개** 조문")

    # 중요 조항 하이라이트
    IMPORTANT_ARTICLES = {
        "학원의 설립·운영 및 과외교습에 관한 법률": ["제2조", "제6조", "제14조의2", "제22조"],
        "학원법": ["제2조", "제6조", "제22조"],
        "형법": ["제16조"],
    }

    for s in filtered_stat:
        law_name = s.get("law_name", "")
        art_num = s.get("article_number", "")
        art_title = s.get("article_title", "")

        is_important = any(
            art_num.startswith(imp_art)
            for imp_law, imp_arts in IMPORTANT_ARTICLES.items()
            for imp_art in imp_arts
            if imp_law in law_name or law_name in imp_law
        )

        prefix = "⭐ " if is_important else ""
        header = f"{prefix}{law_name} {art_num} {art_title}"

        with st.expander(header, expanded=is_important):
            if is_important:
                st.info("방어 전략 핵심 조문")
            st.text(s.get("content", ""))
