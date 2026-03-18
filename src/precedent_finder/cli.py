"""판례 파인더 CLI"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="precedent-finder",
    help="판례 수집 및 검색 시스템",
    no_args_is_help=True,
)
console = Console()


def _get_store():
    from precedent_finder.db.store import PrecedentStore
    return PrecedentStore()


@app.command()
def crawl(
    source: str = typer.Option(
        "law-site",
        help="데이터 소스: law-site, law-api, court-viewer, statutes",
    ),
    keywords: str = typer.Option("학원,교습소", help="검색 키워드 (쉼표 구분)"),
    max_results: int = typer.Option(50, "--max", help="키워드당 최대 수집 건수"),
    max_pages: int = typer.Option(3, "--pages", help="검색 페이지 수 (법제처)"),
    courts: str = typer.Option("서울중앙,인천,수원", help="대상 법원 (쉼표 구분)"),
    laws: str = typer.Option("학원법,형법,교육기본법,아동복지법", help="대상 법령 (쉼표 구분)"),
    output_dir: str = typer.Option("data", "--output", "-o", help="출력 디렉토리"),
):
    """판례/법령 크롤링"""
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    store = _get_store()

    try:
        if source == "law-site":
            from precedent_finder.crawlers.court_scraper import crawl as do_crawl
            from dataclasses import asdict

            console.print(f"[bold green]법제처 판례 크롤링 시작[/]")
            console.print(f"  키워드: {keyword_list}")

            results = do_crawl(
                keywords=keyword_list,
                max_per_keyword=max_results,
                max_pages=max_pages,
                output_dir=output_dir,
            )

            # DB 저장
            for prec in results:
                store.upsert_precedent(asdict(prec), source="law_site")
            console.print(f"\n[bold green]완료: {len(results)}건 수집 → DB 저장[/]")

        elif source == "law-api":
            from precedent_finder.crawlers.law_api import LawAPIClient
            from dataclasses import asdict

            console.print(f"[bold green]법제처 Open API 판례 수집 시작[/]")
            console.print(f"  키워드: {keyword_list}")

            with LawAPIClient() as client:
                all_details = []
                for kw in keyword_list:
                    details = client.search_and_fetch(kw, max_results=max_results, delay=0.3)
                    all_details.extend(details)

                # DB 저장
                saved = 0
                for d in all_details:
                    store.upsert_precedent({
                        "prec_seq": d.serial_number,
                        "case_name": d.case_name,
                        "case_number": d.case_number,
                        "judgment_date": d.judgment_date,
                        "court_name": d.court_name,
                        "case_type": d.case_type,
                        "judgment_type": d.judgment_type,
                        "issues": d.issues,
                        "summary": d.summary,
                        "full_text": d.full_text,
                        "reference_articles": d.reference_articles,
                        "reference_cases": d.reference_cases,
                    }, source="law_api")
                    saved += 1

            console.print(f"\n[bold green]완료: {saved}건 수집 → DB 저장[/]")

        elif source == "court-viewer":
            from precedent_finder.crawlers.court_viewer import crawl_court_viewer
            from dataclasses import asdict

            court_list = [c.strip() for c in courts.split(",") if c.strip()]
            console.print(f"[bold green]판결서 크롤링 시작[/]")
            console.print(f"  법원: {court_list}")
            console.print(f"  키워드: {keyword_list}")

            results = crawl_court_viewer(
                courts=court_list,
                keywords=keyword_list,
                max_per_search=max_results,
                output_dir=output_dir,
            )

            for prec in results:
                store.upsert_precedent(asdict(prec), source="court_viewer")
            console.print(f"\n[bold green]완료: {len(results)}건 수집 → DB 저장[/]")

        elif source == "statutes":
            from precedent_finder.crawlers.law_api import LawAPIClient

            law_list = [l.strip() for l in laws.split(",") if l.strip()]
            console.print(f"[bold green]법제처 API 법령 조문 수집 시작[/]")
            console.print(f"  대상: {law_list}")

            with LawAPIClient() as client:
                all_statutes = client.fetch_statutes(law_list)

            total = 0
            for law_name, articles in all_statutes.items():
                for art in articles:
                    store.upsert_statute(
                        law_name=art["law_name"],
                        article_number=art["article_number"],
                        article_title=art["article_title"],
                        content=art["content"],
                    )
                    total += 1

            console.print(f"\n[bold green]완료: {len(all_statutes)}개 법령, {total}개 조문 → DB 저장[/]")

        else:
            console.print(f"[red]알 수 없는 소스: {source}[/]")
            console.print("사용 가능: law-site, law-api, court-viewer, statutes")
            raise typer.Exit(1)
    finally:
        store.close()


@app.command()
def status():
    """현재 수집된 데이터 현황"""
    store = _get_store()

    try:
        # 판례
        prec_count = store.count_precedents()
        table = Table(title="데이터 현황")
        table.add_column("항목", style="cyan")
        table.add_column("값", style="green")
        table.add_row("판례 수", str(prec_count))

        for court, cnt in store.count_precedents_by_court():
            table.add_row(f"  {court}", str(cnt))

        # 출처별
        for src, cnt in store.count_precedents_by_source():
            table.add_row(f"  [{src}]", str(cnt))

        # 법령
        stat_count = store.count_statutes()
        table.add_row("법령 조문 수", str(stat_count))
        for law, cnt in store.count_statutes_by_law():
            table.add_row(f"  {law}", str(cnt))

        # PDF
        pdf_dir = Path("data/pdfs")
        pdf_count = len(list(pdf_dir.glob("*.pdf"))) if pdf_dir.exists() else 0
        table.add_row("PDF 파일", str(pdf_count))

        # 벡터 DB
        chroma_dir = Path("data/chroma_db")
        table.add_row("벡터 DB", "있음" if chroma_dir.exists() else "없음")

        console.print(table)
    finally:
        store.close()


@app.command()
def search(
    query: str = typer.Argument(help="검색어"),
    field: str = typer.Option("all", help="검색 필드: all, issues, summary, full_text"),
):
    """수집된 판례에서 키워드 검색"""
    store = _get_store()

    try:
        fields = None if field == "all" else [field]
        results = store.search_precedents(query, fields=fields)

        if not results:
            console.print(f"[yellow]'{query}' 검색 결과 없음[/]")
            return

        console.print(f"\n[bold green]'{query}' 검색 결과: {len(results)}건[/]\n")

        for i, prec in enumerate(results, 1):
            console.print(f"[bold]{i}. [{prec.get('case_number', '?')}] {prec.get('case_name', '제목 없음')[:80]}[/]")
            console.print(f"   법원: {prec.get('court_name', '?')} | 선고일: {prec.get('judgment_date', '?')} | {prec.get('judgment_type', '?')}")

            summary = prec.get("summary", "")
            if query in summary:
                idx = summary.index(query)
                start = max(0, idx - 50)
                end = min(len(summary), idx + len(query) + 100)
                snippet = summary[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(summary):
                    snippet = snippet + "..."
                console.print(f"   [dim]{snippet}[/]")
            console.print()
    finally:
        store.close()


@app.command()
def index():
    """데이터 인덱싱 (JSON→DB 마이그레이션 + 벡터 DB 구축)"""
    store = _get_store()

    try:
        # 1) JSON → DB 마이그레이션
        json_path = Path("data/precedents.json")
        if json_path.exists():
            count = store.import_from_json(json_path, source="law_site")
            console.print(f"[green]판례 JSON → DB: {count}건[/]")

        viewer_json = Path("data/court_viewer_results.json")
        if viewer_json.exists():
            count = store.import_from_json(viewer_json, source="court_viewer")
            console.print(f"[green]판결서 JSON → DB: {count}건[/]")

        console.print(f"[bold]DB 총 판례: {store.count_precedents()}건[/]")

        # 2) 벡터 DB 구축
        try:
            from precedent_finder.rag.chunker import Chunker
            from precedent_finder.rag.retriever import Retriever

            console.print("\n[bold cyan]벡터 DB 인덱싱 시작...[/]")

            chunker = Chunker()
            chunks = chunker.chunk_all(store)
            console.print(f"  청크 생성: {len(chunks)}개")

            retriever = Retriever()
            retriever.index_chunks(chunks)
            console.print(f"  벡터 DB 저장 완료")

            console.print(f"\n[bold green]인덱싱 완료: 판례 {store.count_precedents()}건, 법령 {store.count_statutes()}건, 청크 {len(chunks)}개[/]")
        except ImportError as e:
            console.print(f"\n[yellow]벡터 DB 구축 건너뜀 (의존성 부족): {e}[/]")
            console.print("[dim]chromadb, ollama 설치 후 다시 실행하세요[/]")
    finally:
        store.close()


@app.command(name="run-all")
def run_all(
    output_dir: str = typer.Option("data", "--output", "-o"),
):
    """전체 크롤링 실행 (법제처 판례 + 법령)"""
    console.print("[bold]전체 크롤링 시작[/]\n")

    # 1. 법제처 판례
    console.print("[bold cyan]1/2. 법제처 판례 크롤링[/]")
    from precedent_finder.crawlers.court_scraper import crawl as crawl_precedents
    from dataclasses import asdict

    store = _get_store()
    try:
        keywords = ["학원", "교습소", "교육서비스", "학원법위반", "무등록학원", "과외교습", "교육청", "유아", "초등"]
        results = crawl_precedents(
            keywords=keywords, max_per_keyword=50, max_pages=3, output_dir=output_dir,
        )
        for prec in results:
            store.upsert_precedent(asdict(prec), source="law_site")
        console.print(f"  -> 판례 {len(results)}건 → DB\n")

        # 2. 법령 조문
        console.print("[bold cyan]2/2. 법령 조문 크롤링[/]")
        from precedent_finder.crawlers.law_scraper import crawl_statutes

        statutes = crawl_statutes(output_dir=output_dir)
        for statute in statutes:
            for art in statute.articles:
                store.upsert_statute(
                    law_name=statute.name,
                    article_number=art.article_number,
                    article_title=art.article_title,
                    content=art.content,
                    source_url=statute.source_url,
                )
        console.print(f"  -> 법령 {len(statutes)}개 → DB\n")

        console.print(f"[bold green]전체 크롤링 완료! (판례 {store.count_precedents()}건, 법령 {store.count_statutes()}건)[/]")
    finally:
        store.close()


if __name__ == "__main__":
    app()
