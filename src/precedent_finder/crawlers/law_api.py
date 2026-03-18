"""법제처 Open API 클라이언트 - 판례 검색/본문 조회 + 법령 조문 조회"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from xml.etree import ElementTree

import httpx
from dotenv import load_dotenv

load_dotenv()

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

    def __init__(self, oc: str | None = None):
        """
        Args:
            oc: OC 인증값 (미지정 시 환경변수 LAW_API_OC 사용)
        """
        self.oc = oc or os.getenv("LAW_API_OC", "")
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
        max_results: int = 100,
        delay: float = 0.3,
    ) -> list[PrecedentDetail]:
        """검색 후 각 판례 본문까지 모두 가져오기 (페이징 지원)

        Args:
            query: 검색 키워드
            max_results: 최대 결과 수
            delay: API 호출 간 대기 시간 (초)
        """
        # 페이징으로 전체 목록 수집
        summaries = []
        page = 1
        per_page = min(max_results, 100)
        while len(summaries) < max_results:
            batch = self.search_precedents(query, display=per_page, page=page)
            if not batch:
                break
            summaries.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
            time.sleep(delay)
        summaries = summaries[:max_results]
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

    # ── 법령 조문 조회 ──

    def search_laws(self, query: str, display: int = 10) -> list[dict]:
        """법령 검색 → 법령일련번호 목록 반환"""
        params = {
            "OC": self.oc,
            "target": "law",
            "type": "XML",
            "query": query,
            "display": display,
        }
        resp = self.client.get(SEARCH_URL, params=params)
        resp.raise_for_status()

        root = ElementTree.fromstring(resp.text)
        results = []
        for item in root.findall(".//law"):
            results.append({
                "mst": self._text(item, "법령일련번호"),
                "name": self._text(item, "법령명한글"),
                "short_name": self._text(item, "법령약칭명"),
                "law_id": self._text(item, "법령ID"),
                "proclamation_date": self._text(item, "공포일자"),
                "enforcement_date": self._text(item, "시행일자"),
            })
        return results

    def get_statute_articles(self, mst: str) -> list[dict]:
        """법령 본문 조회 → 조문 목록 반환

        Args:
            mst: 법령일련번호
        """
        params = {
            "OC": self.oc,
            "target": "law",
            "type": "XML",
            "MST": mst,
        }
        resp = self.client.get(DETAIL_URL, params=params)
        resp.raise_for_status()

        root = ElementTree.fromstring(resp.text)
        law_name = self._text(root, ".//법령명_한글")

        articles = []
        for art in root.findall(".//조문단위"):
            art_num = self._text(art, "조문번호")
            art_branch = self._text(art, "조문가지번호")
            art_title = self._text(art, "조문제목")
            art_content = self._text(art, "조문내용")

            # 항/호/목 내용 수집
            sub_parts = []
            for ho in art.findall(".//호"):
                ho_content = self._text(ho, "호내용")
                if ho_content:
                    sub_parts.append(ho_content)
                for mok in ho.findall("목"):
                    mok_content = self._text(mok, "목내용")
                    if mok_content:
                        sub_parts.append(f"  {mok_content}")

            # 조번호 구성
            if art_branch:
                article_number = f"제{art_num}조의{art_branch}"
            else:
                article_number = f"제{art_num}조"

            # 전체 내용 조합
            full_content = art_content
            if sub_parts:
                full_content += "\n" + "\n".join(sub_parts)

            articles.append({
                "law_name": law_name,
                "article_number": article_number,
                "article_title": art_title,
                "content": full_content.strip(),
            })

        return articles

    # 약칭 → 정식명칭 매핑 (검색 정확도 향상)
    LAW_NAME_MAP = {
        "학원법": "학원의 설립 운영 및 과외교습에 관한 법률",
        "학원법 시행령": "학원의 설립 운영 및 과외교습에 관한 법률 시행령",
        "아동복지법": "아동복지법",
        "교육기본법": "교육기본법",
        "형법": "형법",
    }

    def _find_best_match(self, query: str, results: list[dict]) -> dict | None:
        """검색 결과에서 가장 적합한 법령 선택"""
        if not results:
            return None

        # 1) 약칭이 정확히 일치하는 것
        for r in results:
            if r["short_name"] == query:
                return r

        # 2) 법령명이 정확히 일치하는 것
        for r in results:
            if r["name"] == query:
                return r

        # 3) 법령명에 query가 포함되고, 시행령/시행규칙이 아닌 것
        for r in results:
            if query in r["name"] and "시행령" not in r["name"] and "시행규칙" not in r["name"]:
                return r

        return results[0]

    def fetch_statutes(
        self,
        law_names: list[str],
        delay: float = 0.3,
    ) -> dict[str, list[dict]]:
        """법령명 목록으로 조문 일괄 수집

        Args:
            law_names: 법령명 또는 약칭 목록 (예: ["학원법", "형법"])
            delay: API 호출 간 대기 시간

        Returns:
            {법령명: [조문 dict 목록]}
        """
        result = {}
        for name in law_names:
            # 약칭 → 정식명칭 변환
            search_query = self.LAW_NAME_MAP.get(name, name)
            print(f"[법령] '{name}' 검색 중... (query: '{search_query}')")
            laws = self.search_laws(search_query, display=10)
            if not laws:
                print(f"  ⚠ '{name}' 검색 결과 없음")
                continue

            law = self._find_best_match(name, laws)
            if not law:
                print(f"  ⚠ '{name}' 매칭 실패")
                continue

            print(f"  → {law['name']} (MST: {law['mst']})")
            time.sleep(delay)

            articles = self.get_statute_articles(law["mst"])
            print(f"  [완료] {len(articles)}개 조문 수집")
            result[law["name"]] = articles
            time.sleep(delay)

        return result

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
    with LawAPIClient() as client:
        details = client.search_and_fetch("학원", max_results=10, delay=0.3)
        save_results(details, "data/test_precedents.json")

        for d in details[:3]:
            print(f"\n{'='*60}")
            print(f"사건명: {d.case_name}")
            print(f"사건번호: {d.case_number}")
            print(f"선고일자: {d.judgment_date}")
            print(f"법원: {d.court_name}")
            print(f"판결요지: {d.summary[:200]}...")
