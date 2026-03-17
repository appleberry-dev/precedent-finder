# 다음 작업 — API 승인 후 진행사항

> 작성일: 2026-03-17

## 대기 중인 API

| API | 신청 페이지 | 용도 | 상태 |
|-----|------------|------|------|
| 법제처 Open API | https://open.law.go.kr/LSO/openApi/guideList.do | 판례 본문 + 법령 조문 조회 | 승인 대기 |
| 대법원 개방형 API | https://openapi.scourt.go.kr | 하급심 판례 조회 | 승인 대기 |

---

## 승인 후 할 일

### 1. 법제처 Open API 연동

**법령 조문 수집** (현재 0건):
```bash
# law_scraper.py를 API 기반으로 수정 후
precedent-finder crawl --source statutes --laws "학원법,형법,교육기본법,아동복지법"
```
- 학원의 설립·운영 및 과외교습에 관한 법률 (전문)
- 형법 (관련 조항)
- 교육기본법 (전문)
- 아동복지법 (관련 조항)

**판례 추가 수집** (현재 204건 → 목표 500건+):
```bash
# API로 수집하면 Selenium 불필요, 더 빠르고 안정적
precedent-finder crawl --source law-api --keywords "학원,교습소,학원법위반" --max 100
```

### 2. 대법원 개방형 API 연동 (Step 9)

```bash
# court_api.py 구현 후
precedent-finder crawl --source court-api --keywords "학원법,과외교습"
```
- API KEY를 `.env`에 추가: `SCOURT_API_KEY=...`
- 인증: API-KEY 헤더, JSON 응답
- 유효기간 2년, 초당 10건 제한

### 3. 재인덱싱

```bash
# 법령 + 추가 판례 수집 후 반드시 재실행
precedent-finder index
```

### 4. Streamlit Cloud 배포

1. https://share.streamlit.io 접속
2. GitHub 로그인 → `appleberry-dev/precedent-finder` 선택
3. Main file: `app.py`
4. Secrets에 `OPENAI_API_KEY` 추가
5. Deploy

---

## 참고: API 신청 시 필요 정보

### 법제처 Open API
- 서버 IP 등록 필요 (공인 IP)
- 공인 IP 확인: `curl ifconfig.me`
- OC 파라미터 = 신청 시 등록한 이메일 ID

### 대법원 개방형 API
- 회원가입 → API KEY 신청
- 유효기간: 2년 (무제한 옵션 가능)
- 트래픽: 초당 10건 (기본값)
