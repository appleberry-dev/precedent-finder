"""법원 판결서 크롤러 — 법고을(lx.scourt.go.kr) + 개별법원 열람 서비스

데이터 소스:
1. 법고을 (lx.scourt.go.kr/search/precedent) — 대법원~하급심 판례 통합 검색
2. 개별법원 열람 (*.scourt.go.kr/common/wcd/wcd.jsp) — 2013.1.1 이후 확정 형사 판결서
"""

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .court_scraper import Precedent, create_driver


# ---------------------------------------------------------------------------
# 법고을 (lx.scourt.go.kr) — 주요 검색 경로
# ---------------------------------------------------------------------------

LAWGOEUL_SEARCH_URL = "https://lx.scourt.go.kr/search/precedent"


def search_lawgoeul(
    driver,
    keyword: str,
    court_type: str = "",
    case_type: str = "",
    max_results: int = 20,
) -> list[dict]:
    """법고을 판례 검색

    Args:
        court_type: "" (전체), "대법원", "고등법원", "하급심", "헌법재판소"
        case_type: "" (전체), "민사", "형사", "가사", "행정", "특허", "조세"
    """
    driver.get(LAWGOEUL_SEARCH_URL)
    time.sleep(3)

    wait = WebDriverWait(driver, 10)
    results = []

    try:
        # 검색어 입력 — 여러 가능한 selector 시도
        search_input = None
        for selector in ["#search_txt", "#search_txt_detail", "input[name='query']", "input.search_input"]:
            try:
                search_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                break
            except Exception:
                continue

        if not search_input:
            print(f"  [오류] 검색 입력창을 찾을 수 없습니다")
            return []

        search_input.clear()
        search_input.send_keys(keyword)
        search_input.send_keys(Keys.RETURN)
        time.sleep(5)

        # 검색 결과 파싱
        soup = BeautifulSoup(driver.page_source, "lxml")

        # 결과 건수
        count_el = soup.select_one(".result_count, .search_count, .total_count")
        if count_el:
            print(f"  [법고을] '{keyword}' → {count_el.get_text(strip=True)}")

        # 결과 목록 추출 — 다양한 구조 대응
        items = soup.select(".search_list li, .result_list li, .list_type li, table.list tbody tr, .srch_list > ul > li")
        if not items:
            # fallback: 링크가 있는 모든 목록 항목
            items = soup.select("ul li a, .content_area a")

        for item in items[:max_results]:
            link = item if item.name == "a" else item.find("a")
            if not link:
                continue

            href = link.get("href", "")
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            # 메타 정보 추출 (사건번호, 법원, 날짜)
            item_text = item.get_text(" ", strip=True)
            case_num_match = re.search(r'(\d{4}[가-힣]{1,4}\d+)', item_text)
            date_match = re.search(r'(\d{4}\.\d{1,2}\.\d{1,2})', item_text)
            court_match = re.search(r'(대법원|고등법원|지방법원|지법|서울[가-힣]+법원|[가-힣]+지법)', item_text)

            result = {
                "title": title,
                "href": href if href.startswith("http") else f"https://lx.scourt.go.kr{href}" if href.startswith("/") else href,
                "case_number": case_num_match.group(1) if case_num_match else "",
                "judgment_date": date_match.group(1) if date_match else "",
                "court_name": court_match.group(1) if court_match else "",
                "source": "lawgoeul",
                "item_text": item_text[:200],
            }
            results.append(result)

    except Exception as e:
        print(f"  [오류] 법고을 검색 실패: {e}")

    print(f"  [법고을] '{keyword}' → {len(results)}건 추출")
    return results


def scrape_lawgoeul_detail(driver, result_info: dict) -> Precedent | None:
    """법고을 판례 상세 스크래핑"""
    href = result_info.get("href", "")
    if not href:
        return None

    try:
        driver.get(href)
        time.sleep(3)

        soup = BeautifulSoup(driver.page_source, "lxml")
        full_text = soup.get_text("\n")

        prec = Precedent(
            case_name=result_info.get("title", ""),
            case_number=result_info.get("case_number", ""),
            judgment_date=result_info.get("judgment_date", ""),
            court_name=result_info.get("court_name", ""),
            source_url=href,
        )

        # 메타 정보 보완 — [대법원 2018. 6. 21. 선고 2015두48655 판결] 패턴
        meta_match = re.search(
            r'\[(?P<court>[가-힣]+)\s+'
            r'(?P<date>\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\.\s*'
            r'선고\s+'
            r'(?P<case_num>\d{4}[가-힣]{1,4}\d+)\s*'
            r'(?P<jtype>[^\]]*)\]',
            full_text,
        )
        if meta_match:
            if not prec.court_name:
                prec.court_name = meta_match.group("court")
            if not prec.case_number:
                prec.case_number = meta_match.group("case_num")
            if not prec.judgment_date:
                prec.judgment_date = meta_match.group("date").replace(" ", "")
            prec.judgment_type = meta_match.group("jtype").strip()

        # 섹션 파싱 — 【판시사항】, 【판결요지】 등
        section_ids = {
            "판시사항": "issues",
            "판결요지": "summary",
            "참조조문": "reference_articles",
            "참조판례": "reference_cases",
            "판례내용": "full_text",
            "주문": "full_text",
            "이유": "full_text",
        }

        for section_name, field in section_ids.items():
            start = full_text.find(f"【{section_name}】")
            if start == -1:
                continue
            start += len(f"【{section_name}】")

            # 다음 【 까지
            end = full_text.find("【", start)
            if end == -1:
                end = len(full_text)

            content = full_text[start:end].strip()[:5000]
            if content:
                current = getattr(prec, field)
                if current and field == "full_text":
                    setattr(prec, field, current + "\n\n" + content)
                elif not current:
                    setattr(prec, field, content)

        return prec

    except Exception as e:
        print(f"    [오류] 상세 스크래핑 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 개별법원 판결서 열람 서비스 (wcd.jsp) — 기존 로직 유지
# ---------------------------------------------------------------------------

COURT_CODES = {
    "서울중앙": "scourt",
    "서울동부": "sdcourt",
    "서울서부": "swcourt",
    "서울남부": "sncourt",
    "서울북부": "sbcourt",
    "인천": "iccourt",
    "수원": "swjcourt",
    "대전": "djcourt",
    "대구": "dgcourt",
    "부산": "bscourt",
    "광주": "gwjcourt",
}


def search_court_wcd(
    driver,
    court_name: str,
    keyword: str,
    max_results: int = 20,
) -> list[dict]:
    """개별법원 wcd.jsp 판결서 검색"""
    code = COURT_CODES.get(court_name)
    if not code:
        print(f"  [경고] 지원하지 않는 법원: {court_name}")
        return []

    url = f"https://{code}.scourt.go.kr/common/wcd/wcd.jsp"
    driver.get(url)
    time.sleep(3)

    results = []
    try:
        wait = WebDriverWait(driver, 10)

        # 키워드 입력 — 여러 selector 시도
        search_input = None
        for sel in ["#searchWord", "input[name='searchWord']", "input.input_text"]:
            try:
                search_input = driver.find_element(By.CSS_SELECTOR, sel)
                break
            except Exception:
                continue

        if not search_input:
            print(f"  [{court_name}] 검색 입력창 못 찾음")
            return []

        search_input.clear()
        search_input.send_keys(keyword)

        # 검색 버튼
        for btn_sel in ["#searchBtn", "input[value='검색']", "button.btn_search", "a.btn_search"]:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, btn_sel)
                btn.click()
                break
            except Exception:
                continue
        else:
            search_input.send_keys(Keys.RETURN)

        time.sleep(5)

        soup = BeautifulSoup(driver.page_source, "lxml")
        rows = soup.select("table tbody tr")

        for row in rows[:max_results]:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            link = row.find("a")
            result = {
                "court_name": court_name,
                "cols": [c.get_text(strip=True) for c in cols],
                "title": link.get_text(strip=True) if link else "",
                "onclick": link.get("onclick", "") if link else "",
                "href": link.get("href", "") if link else "",
                "source": "wcd",
            }
            results.append(result)

    except Exception as e:
        print(f"  [오류] {court_name} wcd 검색 실패: {e}")

    print(f"  [{court_name}] '{keyword}' → {len(results)}건")
    return results


def scrape_wcd_detail(driver, result_info: dict) -> Precedent | None:
    """wcd 판결서 상세 스크래핑"""
    court_name = result_info.get("court_name", "")
    prec = Precedent(court_name=court_name)

    try:
        onclick = result_info.get("onclick", "")
        if onclick:
            driver.execute_script(onclick)
            time.sleep(3)
        elif result_info.get("href"):
            driver.get(result_info["href"])
            time.sleep(3)
        else:
            return None

        soup = BeautifulSoup(driver.page_source, "lxml")
        full_text = soup.get_text("\n")

        # 사건번호
        case_num_match = re.search(r'(\d{4}[가-힣]{1,4}\d+)', full_text)
        if case_num_match:
            prec.case_number = case_num_match.group(1)

        # 선고일
        date_match = re.search(r'(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\.\s*선고', full_text)
        if date_match:
            prec.judgment_date = date_match.group(1).replace(" ", "")

        prec.case_name = result_info.get("title", "")

        # 본문 추출
        content_div = soup.select_one("#contentBody, .content_area, #viewContent")
        if content_div:
            prec.full_text = content_div.get_text("\n").strip()
        else:
            prec.full_text = full_text[:10000]

        # 섹션 파싱
        for section_name, field in [("주문", "summary"), ("이유", "full_text"), ("판시사항", "issues"), ("판결요지", "summary")]:
            start = full_text.find(f"【{section_name}】")
            if start == -1:
                continue
            start += len(f"【{section_name}】")
            end = full_text.find("【", start)
            if end == -1:
                end = len(full_text)
            content = full_text[start:end].strip()[:5000]
            if content and not getattr(prec, field):
                setattr(prec, field, content)

        prec.source_url = driver.current_url

    except Exception as e:
        print(f"    [오류] wcd 상세 스크래핑 실패: {e}")
        return None

    return prec


# ---------------------------------------------------------------------------
# 통합 크롤링
# ---------------------------------------------------------------------------

def crawl_court_viewer(
    courts: list[str] | None = None,
    keywords: list[str] | None = None,
    max_per_search: int = 20,
    use_lawgoeul: bool = True,
    use_wcd: bool = True,
    output_dir: str = "data",
) -> list[Precedent]:
    """판결서 통합 크롤링

    Args:
        courts: wcd 대상 법원 목록
        keywords: 검색 키워드 목록
        use_lawgoeul: 법고을 검색 사용
        use_wcd: 개별법원 wcd 검색 사용
        output_dir: 출력 디렉토리
    """
    if courts is None:
        courts = ["서울중앙", "인천", "수원"]
    if keywords is None:
        keywords = ["학원법", "교습소", "과외교습"]

    driver = create_driver()
    all_results = []
    seen = set()

    try:
        # 1) 법고을 검색
        if use_lawgoeul:
            for keyword in keywords:
                print(f"\n{'='*50}")
                print(f"[법고을] '{keyword}' 검색")
                print(f"{'='*50}")

                search_results = search_lawgoeul(driver, keyword, max_results=max_per_search)
                for i, info in enumerate(search_results):
                    key = info.get("case_number") or info.get("title", "")[:80]
                    if key in seen:
                        continue
                    seen.add(key)

                    print(f"  [{i+1}/{len(search_results)}] 상세 스크래핑...")
                    prec = scrape_lawgoeul_detail(driver, info)
                    if prec and (prec.case_number or prec.full_text):
                        all_results.append(prec)
                        print(f"    -> {prec.case_number or '?'}: {prec.case_name[:50]}")
                    time.sleep(2)

        # 2) 개별법원 wcd 검색
        if use_wcd:
            for court in courts:
                for keyword in keywords:
                    print(f"\n{'='*50}")
                    print(f"[{court} wcd] '{keyword}' 검색")
                    print(f"{'='*50}")

                    search_results = search_court_wcd(driver, court, keyword, max_results=max_per_search)
                    for i, info in enumerate(search_results):
                        key = info.get("title", info.get("cols", [""])[0])[:80]
                        if key in seen:
                            continue
                        seen.add(key)

                        print(f"  [{i+1}/{len(search_results)}] 상세 스크래핑...")
                        prec = scrape_wcd_detail(driver, info)
                        if prec and (prec.case_number or prec.full_text):
                            all_results.append(prec)
                            print(f"    -> {prec.case_number or '?'}: {prec.case_name[:50] if prec.case_name else '제목 없음'}")
                        time.sleep(2)

    finally:
        driver.quit()

    # 저장
    if all_results:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        save_path = output_path / "court_viewer_results.json"
        data = [asdict(p) for p in all_results]
        save_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[저장] {save_path} ({len(all_results)}건)")

    print(f"\n[완료] 판결서 {len(all_results)}건 수집")
    return all_results
