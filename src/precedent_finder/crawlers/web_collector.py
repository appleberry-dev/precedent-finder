"""범용 웹 문서 수집기 — 회사 홈페이지/블로그/뉴스/유튜브 본문 추출.

판례/법령과 달리 정형 API가 없는 일반 웹 콘텐츠를 수집한다.
httpx + BeautifulSoup만 사용(서버 렌더링 페이지 + RSS 대상이라 Selenium 불필요).

- 일반 웹페이지: 본문 영역 휴리스틱 추출
- 네이버 블로그: RSS 피드로 글 목록을 얻고 모바일 PostView에서 본문 추출
- 유튜브: 영상 페이지에서 제목/설명/채널 메타데이터 추출
"""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup


UA_DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"


@dataclass
class CollectedDoc:
    """수집된 문서 1건"""
    source_type: str = "web"        # company | blog | news | youtube | sns | manual
    title: str = ""
    url: str = ""
    published_date: str = ""
    content: str = ""
    summary: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def doc_key(self) -> str:
        return self.url or self.title


def _clean_text(text: str) -> str:
    """공백/개행 정규화"""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fetch(url: str, mobile: bool = False, timeout: float = 20.0) -> httpx.Response:
    headers = {"User-Agent": UA_MOBILE if mobile else UA_DESKTOP,
               "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
    return httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)


def _extract_main_text(soup: BeautifulSoup) -> str:
    """페이지에서 읽을 수 있는 본문 추출 (네비/스크립트 제거)"""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                     "form", "button", "svg", "iframe"]):
        tag.decompose()

    # 본문스러운 컨테이너 우선 (일반 + 국내 뉴스사 선택자 포함)
    candidates = soup.select(
        "article, main, #content, .content, .article, .post, "
        ".board_view, .view_content, #bo_v_con, .se-main-container, "
        # 매일경제/네이버뉴스/연합 등 국내 언론 본문 영역
        ".news_cnt_detail_wrap, #article_body, .art_txt, #dic_area, "
        "#articleBodyContents, #newsct_article, .article_body, .news_view"
    )
    node = max(candidates, key=lambda n: len(n.get_text()), default=None) if candidates else None
    target = node or soup.body or soup
    return _clean_text(target.get_text("\n", strip=True))


# ---------------- 일반 웹페이지 ----------------

def fetch_page(url: str, source_type: str = "web") -> CollectedDoc:
    """일반 웹페이지(홈페이지 하위 페이지, 뉴스 기사 등) 본문 추출"""
    r = _fetch(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()

    pub = ""
    for sel in [("meta", {"property": "article:published_time"}),
                ("meta", {"property": "og:regDate"}),
                ("meta", {"name": "date"})]:
        m = soup.find(*sel[:1], attrs=sel[1])
        if m and m.get("content"):
            pub = m["content"].strip()
            break

    content = _extract_main_text(soup)
    return CollectedDoc(
        source_type=source_type, title=title, url=url,
        published_date=pub, content=content,
        metadata={"fetched_from": urlparse(url).netloc},
    )


# ---------------- 네이버 블로그 ----------------

def _naver_blog_id(url_or_id: str) -> str:
    """URL 또는 ID에서 블로그 ID 추출"""
    if "naver.com" in url_or_id:
        path = urlparse(url_or_id).path.strip("/").split("/")
        return path[0] if path else url_or_id
    return url_or_id


def _fetch_naver_post_body(blog_id: str, log_no: str) -> str:
    """모바일 PostView에서 블로그 본문 추출 (실패 시 빈 문자열)"""
    try:
        url = f"https://m.blog.naver.com/{blog_id}/{log_no}"
        r = _fetch(url, mobile=True)
        soup = BeautifulSoup(r.text, "lxml")
        body = soup.select_one(".se-main-container, #viewTypeSelector, .post_ct")
        if body:
            for tag in body(["script", "style"]):
                tag.decompose()
            return _clean_text(body.get_text("\n", strip=True))
    except Exception:
        pass
    return ""


def fetch_naver_blog_posts(url_or_id: str, max_posts: int = 30,
                           fetch_body: bool = True) -> list[CollectedDoc]:
    """네이버 블로그 RSS로 글 목록 + 본문 수집"""
    blog_id = _naver_blog_id(url_or_id)
    rss_url = f"https://rss.blog.naver.com/{blog_id}.xml"
    r = _fetch(rss_url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "xml")

    docs = []
    for item in soup.find_all("item")[:max_posts]:
        title = item.find("title").get_text(strip=True) if item.find("title") else ""
        link = item.find("link").get_text(strip=True) if item.find("link") else ""
        pub = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""
        desc_raw = item.find("description").get_text() if item.find("description") else ""
        desc = _clean_text(BeautifulSoup(desc_raw, "lxml").get_text(" ", strip=True))

        log_no = ""
        m = re.search(r"/(\d+)", urlparse(link).path)
        if m:
            log_no = m.group(1)

        content = ""
        if fetch_body and log_no:
            content = _fetch_naver_post_body(blog_id, log_no)
        if not content:
            content = desc

        docs.append(CollectedDoc(
            source_type="blog", title=title, url=link.split("?")[0],
            published_date=pub, content=content, summary=desc[:300],
            metadata={"blog_id": blog_id, "platform": "naver_blog"},
        ))
    return docs


# ---------------- 유튜브 ----------------

def _youtube_id(url: str) -> str:
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    q = parse_qs(urlparse(url).query)
    if "v" in q:
        return q["v"][0]
    return ""


def fetch_youtube(url: str) -> CollectedDoc:
    """유튜브 영상 페이지에서 제목/설명/채널 메타데이터 추출.

    자막(transcript)은 별도 의존성이 필요하므로 여기서는 메타데이터만 수집한다.
    """
    r = _fetch(url)
    soup = BeautifulSoup(r.text, "lxml")

    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip()

    desc = ""
    ogd = soup.find("meta", property="og:description")
    if ogd and ogd.get("content"):
        desc = ogd["content"].strip()
    # 페이지 JSON에서 더 긴 설명 시도
    m = re.search(r'"shortDescription":"(.*?)","isCrawlable"', r.text)
    if m:
        try:
            desc = json.loads(f'"{m.group(1)}"')
        except Exception:
            pass

    channel = ""
    cm = re.search(r'"ownerChannelName":"(.*?)"', r.text)
    if cm:
        channel = cm.group(1)

    vid = _youtube_id(url)
    content = f"[유튜브 영상] {title}\n채널: {channel}\n\n{desc}".strip()
    return CollectedDoc(
        source_type="youtube", title=title, url=url, content=content,
        summary=desc[:300],
        metadata={"video_id": vid, "channel": channel, "platform": "youtube"},
    )


# ---------------- 디스패처 ----------------

def collect_url(url: str, source_type: str | None = None) -> CollectedDoc:
    """URL 종류를 판별해 적절한 수집기로 라우팅 (단건)"""
    host = urlparse(url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return fetch_youtube(url)
    return fetch_page(url, source_type=source_type or "web")
