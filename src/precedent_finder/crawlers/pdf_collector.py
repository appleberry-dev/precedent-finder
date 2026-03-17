"""PDF 수집 파이프라인

판결서 페이지를 PDF로 저장하고 텍스트를 추출한다.

전략 (우선순위):
1. 페이지 내 PDF 다운로드 링크 탐지 → 직접 다운로드
2. Chrome CDP Page.printToPDF로 현재 페이지를 PDF 변환
3. pdfplumber로 텍스트 추출
"""

import base64
import re
import time
from pathlib import Path

import pdfplumber
from selenium.webdriver.common.by import By


def sanitize_filename(name: str) -> str:
    """파일명에 사용할 수 없는 문자 제거"""
    name = re.sub(r'[<>:"/\\|?*\s]', '_', name)
    return name[:100]


def find_pdf_download_link(driver) -> str | None:
    """페이지에서 PDF 다운로드 링크 탐지"""
    try:
        # PDF 다운로드 버튼/링크 찾기
        for selector in [
            "a[href$='.pdf']",
            "a[href*='download']",
            "a[href*='pdf']",
            "button[onclick*='pdf']",
            "a.btn_download",
            "a[title*='다운로드']",
            "a[title*='PDF']",
        ]:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                href = el.get_attribute("href")
                if href and href.startswith("http"):
                    return href
    except Exception:
        pass
    return None


def print_page_to_pdf(driver) -> bytes:
    """Chrome CDP를 사용하여 현재 페이지를 PDF로 변환"""
    result = driver.execute_cdp_cmd("Page.printToPDF", {
        "printBackground": True,
        "preferCSSPageSize": True,
        "marginTop": 0.4,
        "marginBottom": 0.4,
        "marginLeft": 0.4,
        "marginRight": 0.4,
    })
    return base64.b64decode(result["data"])


def save_pdf_from_page(
    driver,
    court_name: str = "",
    case_number: str = "",
    output_dir: str = "data/pdfs",
) -> Path | None:
    """현재 페이지를 PDF로 저장

    Returns:
        저장된 PDF 파일 경로 (실패 시 None)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 파일명 생성
    parts = []
    if court_name:
        parts.append(sanitize_filename(court_name))
    if case_number:
        parts.append(sanitize_filename(case_number))
    if not parts:
        parts.append(f"page_{int(time.time())}")

    filename = "_".join(parts) + ".pdf"
    pdf_path = output_path / filename

    # 이미 존재하면 스킵
    if pdf_path.exists():
        print(f"    [스킵] 이미 존재: {pdf_path}")
        return pdf_path

    try:
        # 1순위: PDF 다운로드 링크
        pdf_url = find_pdf_download_link(driver)
        if pdf_url:
            import httpx
            resp = httpx.get(pdf_url, follow_redirects=True, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 1000:
                pdf_path.write_bytes(resp.content)
                print(f"    [PDF 다운로드] {pdf_path}")
                return pdf_path

        # 2순위: Chrome CDP print-to-pdf
        pdf_bytes = print_page_to_pdf(driver)
        if pdf_bytes and len(pdf_bytes) > 1000:
            pdf_path.write_bytes(pdf_bytes)
            print(f"    [PDF 생성] {pdf_path}")
            return pdf_path

    except Exception as e:
        print(f"    [PDF 오류] {e}")

    return None


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """PDF에서 텍스트 추출"""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return ""

    text_parts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        print(f"    [텍스트 추출 오류] {pdf_path}: {e}")
        return ""

    return "\n\n".join(text_parts)


def collect_pdf(
    driver,
    court_name: str = "",
    case_number: str = "",
    output_dir: str = "data/pdfs",
) -> tuple[Path | None, str]:
    """현재 페이지의 PDF 저장 + 텍스트 추출

    Returns:
        (pdf_path, extracted_text) 튜플
    """
    pdf_path = save_pdf_from_page(driver, court_name, case_number, output_dir)
    if pdf_path:
        text = extract_text_from_pdf(pdf_path)
        return pdf_path, text
    return None, ""
