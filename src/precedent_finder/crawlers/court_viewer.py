"""지방법원 판결서 인터넷 열람 서비스 크롤러 (scourt.go.kr)

대상: 2013.1.1 이후 확정된 형사 사건 판결서
"""

import re
import time
from dataclasses import asdict

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select

from .court_scraper import Precedent, create_driver


# 지방법원별 URL 코드
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


def get_viewer_url(court_name: str) -> str:
    """법원명으로 판결서 열람 URL 생성"""
    code = COURT_CODES.get(court_name)
    if not code:
        raise ValueError(f"지원하지 않는 법원: {court_name}. 지원 법원: {list(COURT_CODES.keys())}")
    return f"https://{code}.scourt.go.kr/common/wcd/wcd.jsp"


def search_court_decisions(
    driver,
    court_name: str,
    keyword: str,
    max_results: int = 20,
) -> list[dict]:
    """지방법원 판결서 검색

    Returns:
        검색 결과 목록 (각 항목은 판결 메타 정보 dict)
    """
    url = get_viewer_url(court_name)
    driver.get(url)
    time.sleep(3)

    results = []

    try:
        wait = WebDriverWait(driver, 10)

        # 사건 유형을 형사로 선택 (select box)
        try:
            case_type_select = wait.until(
                EC.presence_of_element_located((By.ID, "saType"))
            )
            Select(case_type_select).select_by_value("3")  # 형사
        except Exception:
            print(f"  [경고] {court_name} 사건유형 선택 실패, 기본값 사용")

        # 키워드 입력
        search_input = wait.until(
            EC.presence_of_element_located((By.ID, "searchWord"))
        )
        search_input.clear()
        search_input.send_keys(keyword)

        # 검색 실행
        search_btn = driver.find_element(By.CSS_SELECTOR, "input[type='button'][value='검색'], button.btn_search, #searchBtn")
        search_btn.click()
        time.sleep(5)

        # 결과 파싱
        soup = BeautifulSoup(driver.page_source, "lxml")

        # 결과 테이블에서 행 추출
        rows = soup.select("table.list tbody tr, table.tb_list tbody tr, #resultList tr")
        if not rows:
            rows = soup.select("table tr")

        for row in rows[:max_results]:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            result = {
                "court_name": court_name,
                "row_text": row.get_text(strip=True),
                "cols": [c.get_text(strip=True) for c in cols],
            }

            # 링크에서 상세 페이지 정보 추출
            link = row.find("a")
            if link:
                onclick = link.get("onclick", "")
                href = link.get("href", "")
                result["onclick"] = onclick
                result["href"] = href
                result["title"] = link.get_text(strip=True)

            results.append(result)

    except Exception as e:
        print(f"  [오류] {court_name} 검색 실패: {e}")

    print(f"  [{court_name}] '{keyword}' → {len(results)}건 검색됨")
    return results


def scrape_decision_detail(driver, court_name: str, result_info: dict) -> Precedent | None:
    """검색 결과에서 판결서 상세 내용 스크래핑"""
    prec = Precedent(court_name=court_name)

    try:
        # onclick 이벤트가 있으면 실행
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

        # 사건번호 추출
        case_num_match = re.search(r'(\d{4}[가-힣]{1,4}\d+)', full_text)
        if case_num_match:
            prec.case_number = case_num_match.group(1)

        # 선고일 추출
        date_match = re.search(r'(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\.\s*선고', full_text)
        if date_match:
            prec.judgment_date = date_match.group(1).replace(" ", "")

        # 사건명 (title에서)
        prec.case_name = result_info.get("title", "")

        # 본문 텍스트
        # 판결서 본문 영역 찾기
        content_div = soup.select_one("#contentBody, .content_area, #viewContent, .judgment_text")
        if content_div:
            prec.full_text = content_div.get_text("\n").strip()
        else:
            # 전체 텍스트에서 주요 부분 추출
            prec.full_text = full_text[:10000]

        # 【주문】, 【이유】 등 섹션 파싱
        sections = {"주문": "", "이유": "", "판시사항": "", "판결요지": ""}
        for section_name in sections:
            start = full_text.find(f"【{section_name}】")
            if start == -1:
                start = full_text.find(section_name)
                if start == -1:
                    continue
                start += len(section_name)
            else:
                start += len(f"【{section_name}】")

            # 다음 섹션까지
            end = len(full_text)
            for other in sections:
                if other == section_name:
                    continue
                next_pos = full_text.find(f"【{other}】", start)
                if next_pos != -1 and next_pos < end:
                    end = next_pos

            sections[section_name] = full_text[start:end].strip()[:5000]

        if sections["판시사항"]:
            prec.issues = sections["판시사항"]
        if sections["판결요지"]:
            prec.summary = sections["판결요지"]
        elif sections["이유"]:
            prec.summary = sections["이유"][:3000]

        prec.source_url = driver.current_url

    except Exception as e:
        print(f"    [오류] 상세 스크래핑 실패: {e}")
        return None

    return prec


def crawl_court_viewer(
    courts: list[str] | None = None,
    keywords: list[str] | None = None,
    max_per_search: int = 10,
) -> list[Precedent]:
    """지방법원 판결서 열람 크롤링

    Args:
        courts: 대상 법원 목록 (None이면 전체)
        keywords: 검색 키워드 목록
        max_per_search: 검색당 최대 수집 건수
    """
    if courts is None:
        courts = ["서울중앙", "인천", "수원"]
    if keywords is None:
        keywords = ["학원법", "교습소", "과외교습"]

    driver = create_driver()
    all_results = []
    seen = set()

    try:
        for court in courts:
            for keyword in keywords:
                print(f"\n{'='*50}")
                print(f"[{court}] '{keyword}' 검색 중...")
                print(f"{'='*50}")

                search_results = search_court_decisions(
                    driver, court, keyword, max_results=max_per_search
                )

                for i, result_info in enumerate(search_results):
                    # 중복 체크 (제목 기준)
                    title = result_info.get("title", result_info.get("row_text", ""))[:100]
                    if title in seen:
                        continue
                    seen.add(title)

                    print(f"  [{i+1}/{len(search_results)}] 상세 스크래핑...")
                    prec = scrape_decision_detail(driver, court, result_info)
                    if prec and (prec.case_number or prec.full_text):
                        all_results.append(prec)
                        print(f"    -> {prec.case_number or '번호미상'}: {prec.case_name[:50] if prec.case_name else '제목 없음'}")

                    time.sleep(2)

    finally:
        driver.quit()

    print(f"\n[완료] 지방법원 판결서 {len(all_results)}건 수집")
    return all_results
