# Precedent Finder (판례 파인더)

교육청 고발 대응을 위한 판례 및 법령 수집 시스템.
법제처, 지방법원 판결서 열람 서비스에서 관련 판례를 크롤링하고, 법령 조문을 수집한다.

## 기술 스택

- **Python 3.11+**
- **Selenium** - JS 렌더링이 필요한 법률 사이트 크롤링
- **BeautifulSoup / lxml** - HTML 파싱
- **Typer + Rich** - CLI
- **Pydantic** - 데이터 모델
- **httpx** - API 클라이언트

## 프로젝트 구조

```
src/precedent_finder/
├── cli.py                          # 통합 CLI (진입점)
├── crawlers/
│   ├── court_scraper.py            # 법제처 판례 크롤러 (Selenium)
│   ├── court_viewer.py             # 지방법원 판결서 열람 크롤러
│   ├── law_api.py                  # 법제처 Open API 클라이언트
│   └── law_scraper.py              # 법령 조문 크롤러
├── exporters/
│   └── notebook_lm.py              # NotebookLM용 Markdown 내보내기
├── db/                             # (예정) 검색 DB
└── parsers/                        # (예정) 텍스트 파서
```

## 데이터 소스

| 소스 | 설명 | 크롤러 | 상태 |
|------|------|--------|------|
| 법제처 판례 (law.go.kr) | 대법원/고등법원 주요 판례 | `court_scraper.py` | 동작 확인 |
| 법제처 Open API | REST API (OC 인증 필요) | `law_api.py` | 승인 대기 |
| 지방법원 판결서 열람 (scourt.go.kr) | 2013년 이후 확정 형사 판결서 | `court_viewer.py` | 구현 완료 |
| 법령 조문 (law.go.kr) | 학원법, 형법 등 관련 법령 | `law_scraper.py` | 구현 완료 |

## 설치

```bash
# uv 사용
uv sync
uv pip install -e .
```

## 사용법

```bash
# 법제처 판례 크롤링
precedent-finder crawl --source law-site --keywords "학원,교습소,학원법위반" --max 50 --pages 3

# 지방법원 판결서 크롤링
precedent-finder crawl --source court-viewer --courts "서울중앙,인천" --keywords "학원법,과외교습"

# 법령 조문 수집
precedent-finder crawl --source statutes --laws "학원법,형법"

# 전체 크롤링 (판례 + 법령)
precedent-finder run-all

# 수집 현황 확인
precedent-finder status

# 수집된 판례 검색
precedent-finder search "무등록학원"
```

## 수집 대상 키워드

학원, 교습소, 교육서비스, 학원법위반, 무등록학원, 과외교습, 교육청, 유아, 초등

## 수집 대상 법령

- 학원의 설립·운영 및 과외교습에 관한 법률
- 형법
- 교육기본법
- 아동복지법

## 출력

- `data/precedents.json` - 수집된 판례 (JSON)
- `data/statutes.json` - 수집된 법령 조문 (JSON)
