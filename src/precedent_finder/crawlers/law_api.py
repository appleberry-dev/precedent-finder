"""법제처 Open API 클라이언트 - 판례 검색 및 본문 조회"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from xml.etree import ElementTree

import httpx

BASE_URL = "http://www.law.go.kr/DRF"
SEARCH_URL = f"{BASE_URL}/lawSearch.do"
DETAIL_URL = f"{BASE_URL}/lawService.do"


@dataclass
class PrecedentSummary:
    """판례 목록 검색 결과 (요약)"""
    serial_number: str  # 판례일련번호
    case_name: str  # 사건명
    case_number: str  # 사건번호
    judgment_date: str  # 선고일자
    court_name: str  # 법원명
    case_type: str  # 사건종류명
    judgment_type: str  # 판결유형
    detail_link: str  # 판례상세링크


@dataclass
class PrecedentDetail:
    """판례 본문 조회 결과 (상세)"""
    serial_number: str = ""
    case_name: str = ""
    case_number: str = ""
    judgment_date: str = ""
    court_name: str = ""
    case_type: str = ""
    judgment_type: str = ""
    issues: str = ""  # 판시사항
    summary: str = ""  # 판결요지
    reference_articles: str = ""  # 참조조문
    reference_cases: str = ""  # 참조판례
    full_text: str = ""  # 판례내용


class LawAPIClient:
    """법제처 Open API 클라이언트"""

    def __init__(self, oc: str = "test"):
        """
        Args:
            oc: 사용자 이메일 ID (예: test@gmail.com → "test")
        """
        self.oc = oc
        self.client = httpx.Client(timeout=30.0)

    def search_precedents(
        self,
        query: str,
        display: int = 10,
        page: int = 1,
    ) -> list[PrecedentSummary]:
        """판례 목록 검색

        Args:
            query: 검색 키워드
            display: 결과 수 (최대 100)
            page: 페이지 번호
        """
        params = {
            "OC": self.oc,
            "target": "prec",
            "type": "XML",
            "query": query,
            "display": display,
            "page": page,
        }

        resp = self.client.get(SEARCH_URL, params=params)
        resp.raise_for_status()

        return self._parse_search_results(resp.text)

    def get_precedent_detail(self, serial_number: str) -> PrecedentDetail:
        """판례 본문 조회

        Args:
            serial_number: 판례일련번호
        """
        params = {
            "OC": self.oc,
            "target": "prec",
            "type": "XML",
            "ID": serial_number,
        }

        resp = self.client.get(DETAIL_URL, params=params)
        resp.raise_for_status()

        return self._parse_detail_result(resp.text)

    def search_and_fetch(
        self,
        query: str,
        max_results: int = 10,
        delay: float = 0.5,
    ) -> list[PrecedentDetail]:
        """검색 후 각 판례 본문까지 모두 가져오기

        Args:
            query: 검색 키워드
            max_results: 최대 결과 수
            delay: API 호출 간 대기 시간 (초)
        """
        summaries = self.search_precedents(query, display=max_results)
        print(f"[검색 완료] '{query}' → {len(summaries)}건 발견")

        details = []
        for i, s in enumerate(summaries):
            print(f"  [{i+1}/{len(summaries)}] {s.case_name} ({s.case_number}) 본문 조회 중...")
            try:
                detail = self.get_precedent_detail(s.serial_number)
                details.append(detail)
            except Exception as e:
                print(f"    ⚠ 본문 조회 실패: {e}")

            if delay > 0 and i < len(summaries) - 1:
                time.sleep(delay)

        print(f"[완료] {len(details)}건 본문 수집 완료")
        return details

    def _parse_search_results(self, xml_text: str) -> list[PrecedentSummary]:
        """검색 결과 XML 파싱"""
        root = ElementTree.fromstring(xml_text)
        results = []

        for item in root.findall(".//prec"):
            results.append(PrecedentSummary(
                serial_number=self._text(item, "판례일련번호"),
                case_name=self._text(item, "사건명"),
                case_number=self._text(item, "사건번호"),
                judgment_date=self._text(item, "선고일자"),
                court_name=self._text(item, "법원명"),
                case_type=self._text(item, "사건종류명"),
                judgment_type=self._text(item, "판결유형"),
                detail_link=self._text(item, "판례상세링크"),
            ))

        return results

    def _parse_detail_result(self, xml_text: str) -> PrecedentDetail:
        """판례 본문 XML 파싱"""
        root = ElementTree.fromstring(xml_text)

        return PrecedentDetail(
            serial_number=self._text(root, "판례정보일련번호"),
            case_name=self._text(root, "사건명"),
            case_number=self._text(root, "사건번호"),
            judgment_date=self._text(root, "선고일자"),
            court_name=self._text(root, "법원명"),
            case_type=self._text(root, "사건종류명"),
            judgment_type=self._text(root, "판결유형"),
            issues=self._text(root, "판시사항"),
            summary=self._text(root, "판결요지"),
            reference_articles=self._text(root, "참조조문"),
            reference_cases=self._text(root, "참조판례"),
            full_text=self._text(root, "판례내용"),
        )

    @staticmethod
    def _text(element, tag: str) -> str:
        """XML 엘리먼트에서 태그 텍스트 추출"""
        el = element.find(tag)
        return (el.text or "").strip() if el is not None else ""

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def save_results(details: list[PrecedentDetail], output_path: str | Path):
    """판례 결과를 JSON 파일로 저장"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = [asdict(d) for d in details]
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[저장] {output_path} ({len(data)}건)")


if __name__ == "__main__":
    # 테스트: 10건 크롤링
    with LawAPIClient(oc="test") as client:
        details = client.search_and_fetch("학원", max_results=10, delay=0.5)
        save_results(details, "data/test_precedents.json")

        # 결과 미리보기
        for d in details[:3]:
            print(f"\n{'='*60}")
            print(f"사건명: {d.case_name}")
            print(f"사건번호: {d.case_number}")
            print(f"선고일자: {d.judgment_date}")
            print(f"법원: {d.court_name}")
            print(f"판결요지: {d.summary[:200]}...")
