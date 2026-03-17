"""법제처 법령 조문 스크래퍼

대상 법령의 조문을 파싱하여 구조화된 데이터로 저장
"""

import json
import re
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .court_scraper import create_driver


@dataclass
class Article:
    """법령 조문"""
    law_name: str = ""         # 법령명
    article_number: str = ""   # 조번호 (제1조)
    article_title: str = ""    # 조제목
    content: str = ""          # 조문 내용
    paragraphs: list[str] = field(default_factory=list)  # 항 목록


@dataclass
class Statute:
    """법령 정보"""
    name: str = ""             # 법령명
    law_id: str = ""           # 법령 ID
    proclamation: str = ""     # 공포일/번호
    enforcement_date: str = "" # 시행일
    articles: list[Article] = field(default_factory=list)
    source_url: str = ""


# 크롤링 대상 법령 목록
TARGET_LAWS = {
    "학원법": "학원의 설립·운영 및 과외교습에 관한 법률",
    "형법": "형법",
    "교육기본법": "교육기본법",
    "아동복지법": "아동복지법",
}


def search_law(driver, law_name: str) -> str | None:
    """법령명으로 검색하여 법령 상세 URL 반환"""
    url = f"https://www.law.go.kr/LSW/lsSc.do?menuId=1&subMenuId=15&tabMenuId=81&query={law_name}"
    driver.get(url)
    time.sleep(4)

    soup = BeautifulSoup(driver.page_source, "lxml")

    # 검색 결과에서 법률 링크 찾기
    for link in soup.select("a"):
        text = link.get_text(strip=True)
        if law_name in text:
            href = link.get("href", "")
            if "lsInfoP" in href or "lsEfInfoP" in href:
                if href.startswith("/"):
                    return f"https://www.law.go.kr{href}"
                return href

    # 직접 링크 패턴 시도
    for link in soup.select("a[href*='lsInfoP'], a[href*='lsEfInfoP']"):
        href = link.get("href", "")
        if href.startswith("/"):
            return f"https://www.law.go.kr{href}"
        return href

    return None


def scrape_statute(driver, law_name: str) -> Statute | None:
    """법령 조문 전체 스크래핑"""
    print(f"\n[법령] '{law_name}' 검색 중...")

    statute_url = search_law(driver, law_name)
    if not statute_url:
        print(f"  [실패] '{law_name}' 법령을 찾을 수 없습니다.")
        return None

    print(f"  URL: {statute_url}")
    driver.get(statute_url)
    time.sleep(5)

    soup = BeautifulSoup(driver.page_source, "lxml")
    full_text = soup.get_text("\n")

    statute = Statute(name=law_name, source_url=statute_url)

    # 법령 메타 정보
    proclamation_match = re.search(r'(법률\s*제\d+호[^,\n]*)', full_text)
    if proclamation_match:
        statute.proclamation = proclamation_match.group(1).strip()

    enforcement_match = re.search(r'시행\s*(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})', full_text)
    if enforcement_match:
        statute.enforcement_date = enforcement_match.group(1).replace(" ", "")

    # 조문 파싱
    # 패턴: 제X조(제목) 또는 제X조의Y(제목)
    article_pattern = re.compile(
        r'(제\d+조(?:의\d+)?)\s*(?:\(([^)]+)\))?\s*'
    )

    # 조문 영역 찾기 - <div class="lawcon"> 또는 본문 영역
    content_area = soup.select_one(".lawcon, #conScroll, .law_body, #lsData")
    if content_area:
        parse_text = content_area.get_text("\n")
    else:
        parse_text = full_text

    # 조문 분리
    matches = list(article_pattern.finditer(parse_text))

    for i, match in enumerate(matches):
        art_num = match.group(1)
        art_title = match.group(2) or ""

        # 조문 내용: 현재 매치부터 다음 매치까지
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(parse_text)
        content = parse_text[start:end].strip()

        # 항 분리 (①, ②, ③ ... 또는 1., 2., 3. ...)
        paragraphs = re.split(r'(?=[①②③④⑤⑥⑦⑧⑨⑩])', content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        article = Article(
            law_name=law_name,
            article_number=art_num,
            article_title=art_title,
            content=content[:5000],  # 안전 제한
            paragraphs=paragraphs,
        )
        statute.articles.append(article)

    print(f"  [완료] {law_name}: {len(statute.articles)}개 조문 파싱")
    return statute


def statute_to_markdown(statute: Statute) -> str:
    """Statute를 Markdown으로 변환"""
    lines = [f"# {statute.name}"]
    lines.append("")
    if statute.proclamation:
        lines.append(f"- 공포: {statute.proclamation}")
    if statute.enforcement_date:
        lines.append(f"- 시행일: {statute.enforcement_date}")
    if statute.source_url:
        lines.append(f"- 출처: {statute.source_url}")
    lines.append("")

    for art in statute.articles:
        title_part = f" ({art.article_title})" if art.article_title else ""
        lines.append(f"## {art.article_number}{title_part}")
        lines.append("")
        lines.append(art.content)
        lines.append("")

    return "\n".join(lines)


def crawl_statutes(
    law_names: list[str] | None = None,
    output_dir: str = "data",
) -> list[Statute]:
    """법령 조문 크롤링

    Args:
        law_names: 수집할 법령 약칭 목록 (None이면 TARGET_LAWS 전체)
        output_dir: 출력 디렉토리
    """
    if law_names is None:
        law_names = list(TARGET_LAWS.keys())

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    nb_dir = output_path / "notebook_lm"
    nb_dir.mkdir(parents=True, exist_ok=True)

    driver = create_driver()
    statutes = []

    try:
        for short_name in law_names:
            full_name = TARGET_LAWS.get(short_name, short_name)
            statute = scrape_statute(driver, full_name)
            if statute:
                statutes.append(statute)
                time.sleep(2)
    finally:
        driver.quit()

    # JSON 저장
    json_path = output_path / "statutes.json"
    json_data = []
    for s in statutes:
        sd = asdict(s)
        json_data.append(sd)
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장] {json_path} ({len(statutes)}개 법령)")

    # NotebookLM Markdown
    for s in statutes:
        md = statute_to_markdown(s)
        safe_name = re.sub(r'[<>:"/\\|?*]', '', s.name)
        md_path = nb_dir / f"법령_{safe_name}.md"
        md_path.write_text(md, encoding="utf-8")
        print(f"[내보내기] {md_path}")

    return statutes


if __name__ == "__main__":
    crawl_statutes()
