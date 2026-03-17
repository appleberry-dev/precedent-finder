"""법제처 국가법령정보센터 판례 웹 스크래핑 (Selenium 기반)"""

import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


@dataclass
class Precedent:
    """판례 데이터"""
    prec_seq: str = ""         # 판례 일련번호
    case_name: str = ""        # 사건명
    case_number: str = ""      # 사건번호
    judgment_date: str = ""    # 선고일자
    court_name: str = ""       # 법원명
    case_type: str = ""        # 사건종류
    judgment_type: str = ""    # 판결유형
    issues: str = ""           # 판시사항
    summary: str = ""          # 판결요지
    full_text: str = ""        # 판례내용
    reference_articles: str = ""  # 참조조문
    reference_cases: str = ""    # 참조판례
    source_url: str = ""       # 원본 URL


def create_driver() -> webdriver.Chrome:
    """헤드리스 Chrome 드라이버 생성"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def search_precedents(
    driver: webdriver.Chrome,
    query: str,
    max_results: int = 10,
    max_pages: int = 1,
) -> list[str]:
    """판례 검색 후 판례 일련번호(precSeq) 목록 반환

    Args:
        max_pages: 수집할 최대 페이지 수 (1페이지 = 약 20건)
    """
    base_url = f"https://www.law.go.kr/LSW/precSc.do?menuId=7&subMenuId=47&tabMenuId=213&query={query}"
    all_seq_ids = []
    seen = set()

    for page in range(1, max_pages + 1):
        url = base_url if page == 1 else f"{base_url}&page={page}"
        driver.get(url)
        time.sleep(5)

        page_source = driver.page_source

        if page == 1:
            count_match = re.search(r'총\s*([\d,]+)건', page_source)
            total = count_match.group(1) if count_match else "?"
            print(f"[검색] '{query}' → 총 {total}건")

        # lsEmpViewWideAll('206093') 패턴에서 판례 ID 추출
        seq_ids = re.findall(r"lsEmpViewWideAll\('(\d+)'\)", page_source)

        new_count = 0
        for sid in seq_ids:
            if sid not in seen:
                seen.add(sid)
                all_seq_ids.append(sid)
                new_count += 1

        print(f"  [페이지 {page}] {new_count}건 신규 ID 추출")

        if new_count == 0:
            break
        if len(all_seq_ids) >= max_results:
            break

    all_seq_ids = all_seq_ids[:max_results]
    print(f"[수집] 총 {len(all_seq_ids)}건 판례 ID")
    return all_seq_ids


def scrape_detail(driver: webdriver.Chrome, prec_seq: str) -> Precedent:
    """판례 상세 페이지 스크래핑"""
    url = f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={prec_seq}"
    driver.get(url)
    time.sleep(3)

    soup = BeautifulSoup(driver.page_source, "lxml")
    prec = Precedent(prec_seq=prec_seq, source_url=url)

    full_text = soup.get_text("\n")

    # 사건명 - 두 번째 h2 태그 (첫 번째는 "판례정보")
    h2_tags = soup.find_all("h2")
    for h2 in h2_tags:
        text = h2.get_text(strip=True)
        if text and text != "판례정보":
            prec.case_name = text
            break

    # 메타 정보 - [대법원 2018. 6. 21. 선고 2015두48655 전원합의체 판결] 패턴
    meta_match = re.search(
        r'\[(?P<court>[가-힣]+)\s+'
        r'(?P<date>\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\.\s*'
        r'선고\s+'
        r'(?P<case_num>\d{4}[가-힣]{1,4}\d+)\s*'
        r'(?P<jtype>[^\]]*)\]',
        full_text,
    )
    if meta_match:
        prec.court_name = meta_match.group("court")
        prec.judgment_date = meta_match.group("date").replace(" ", "")
        prec.case_number = meta_match.group("case_num")
        prec.judgment_type = meta_match.group("jtype").strip()

    # 본문 영역 - 【섹션명】 패턴으로 추출
    section_ids = {
        "판시사항": "issues",
        "판결요지": "summary",
        "참조조문": "reference_articles",
        "참조판례": "reference_cases",
        "판례내용": "full_text",
    }

    section_names = list(section_ids.keys())
    for i, section_name in enumerate(section_names):
        start = full_text.find(f"【{section_name}】")
        if start == -1:
            continue

        start += len(f"【{section_name}】")

        # 다음 섹션 시작 위치 (끝 경계)
        end = len(full_text)
        for next_name in section_names[i+1:]:
            next_pos = full_text.find(f"【{next_name}】", start)
            if next_pos != -1:
                end = next_pos
                break

        content = full_text[start:end].strip()
        if content:
            setattr(prec, section_ids[section_name], content)

    return prec


def crawl(
    keywords: list[str],
    max_per_keyword: int = 10,
    max_pages: int = 1,
    output_dir: str = "data",
) -> list[Precedent]:
    """키워드 목록으로 판례 크롤링

    Args:
        max_pages: 키워드당 검색 페이지 수 (1페이지 ≈ 20건)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    driver = create_driver()
    all_results = []
    seen_seqs = set()

    try:
        for keyword in keywords:
            print(f"\n{'='*50}")
            print(f"키워드: {keyword}")
            print(f"{'='*50}")

            seq_ids = search_precedents(driver, keyword, max_results=max_per_keyword, max_pages=max_pages)

            for i, seq_id in enumerate(seq_ids):
                if seq_id in seen_seqs:
                    print(f"  [{i+1}/{len(seq_ids)}] 중복 건너뜀 (seq={seq_id})")
                    continue
                seen_seqs.add(seq_id)

                print(f"  [{i+1}/{len(seq_ids)}] 판례 {seq_id} 스크래핑...")
                try:
                    prec = scrape_detail(driver, seq_id)
                    all_results.append(prec)
                    print(f"    -> {prec.case_name[:50] if prec.case_name else '제목 없음'}")
                except Exception as e:
                    print(f"    X 실패: {e}")

    finally:
        driver.quit()

    # 기존 데이터 로드 & 병합
    all_path = output_path / "precedents.json"
    existing_data = []
    if all_path.exists():
        try:
            existing_data = json.loads(all_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass

    existing_seqs = {d["prec_seq"] for d in existing_data}
    new_data = [asdict(p) for p in all_results if p.prec_seq not in existing_seqs]
    merged = existing_data + new_data
    all_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장 완료] {all_path} (기존 {len(existing_data)}건 + 신규 {len(new_data)}건 = 총 {len(merged)}건)")

    return all_results


if __name__ == "__main__":
    results = crawl(
        keywords=["학원", "교습소", "교육서비스", "학원법위반", "무등록학원", "과외교습", "교육청"],
        max_per_keyword=50,
        max_pages=3,
    )

    for p in results[:3]:
        print(f"\n{'='*60}")
        print(f"사건명: {p.case_name}")
        print(f"사건번호: {p.case_number}")
        print(f"법원: {p.court_name}")
        print(f"판결요지: {p.summary[:300]}..." if p.summary else "판결요지: 없음")
