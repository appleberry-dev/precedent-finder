"""판례 파인더 CLI"""

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="precedent-finder",
    help="판례 수집 및 검색 시스템",
    no_args_is_help=True,
)
console = Console()


@app.command()
def crawl(
    source: str = typer.Option(
        "law-site",
        help="데이터 소스: law-site (법제처), court-viewer (지방법원), statutes (법령)",
    ),
    keywords: str = typer.Option(
        "학원,교습소",
        help="검색 키워드 (쉼표 구분)",
    ),
    max_results: int = typer.Option(50, "--max", help="키워드당 최대 수집 건수"),
    max_pages: int = typer.Option(3, "--pages", help="검색 페이지 수 (법제처)"),
    courts: str = typer.Option(
        "서울중앙,인천,수원",
        help="대상 법원 (지방법원 크롤링 시, 쉼표 구분)",
    ),
    laws: str = typer.Option(
        "학원법,형법,교육기본법,아동복지법",
        help="대상 법령 (법령 크롤링 시, 쉼표 구분)",
    ),
    output_dir: str = typer.Option("data", "--output", "-o", help="출력 디렉토리"),
):
    """판례/법령 크롤링"""
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

    if source == "law-site":
        from precedent_finder.crawlers.court_scraper import crawl as do_crawl

        console.print(f"[bold green]법제처 판례 크롤링 시작[/]")
        console.print(f"  키워드: {keyword_list}")
        console.print(f"  키워드당 최대: {max_results}건, 페이지: {max_pages}")

        results = do_crawl(
            keywords=keyword_list,
            max_per_keyword=max_results,
            max_pages=max_pages,
            output_dir=output_dir,
        )
        console.print(f"\n[bold green]완료: {len(results)}건 수집[/]")

    elif source == "court-viewer":
        from precedent_finder.crawlers.court_viewer import crawl_court_viewer

        court_list = [c.strip() for c in courts.split(",") if c.strip()]
        console.print(f"[bold green]지방법원 판결서 크롤링 시작[/]")
        console.print(f"  법원: {court_list}")
        console.print(f"  키워드: {keyword_list}")

        results = crawl_court_viewer(
            courts=court_list,
            keywords=keyword_list,
            max_per_search=max_results,
        )
        console.print(f"\n[bold green]완료: {len(results)}건 수집[/]")

    elif source == "statutes":
        from precedent_finder.crawlers.law_scraper import crawl_statutes

        law_list = [l.strip() for l in laws.split(",") if l.strip()]
        console.print(f"[bold green]법령 조문 크롤링 시작[/]")
        console.print(f"  법령: {law_list}")

        results = crawl_statutes(
            law_names=law_list,
            output_dir=output_dir,
        )
        console.print(f"\n[bold green]완료: {len(results)}개 법령 수집[/]")

    else:
        console.print(f"[red]알 수 없는 소스: {source}[/]")
        console.print("사용 가능: law-site, court-viewer, statutes")
        raise typer.Exit(1)


@app.command()
def status():
    """현재 수집된 데이터 현황"""
    data_dir = Path("data")

    # 판례 현황
    prec_path = data_dir / "precedents.json"
    if prec_path.exists():
        data = json.loads(prec_path.read_text(encoding="utf-8"))
        table = Table(title="판례 수집 현황")
        table.add_column("항목", style="cyan")
        table.add_column("값", style="green")
        table.add_row("총 판례 수", str(len(data)))

        courts = {}
        for d in data:
            court = d.get("court_name", "미상")
            courts[court] = courts.get(court, 0) + 1
        for court, count in sorted(courts.items(), key=lambda x: -x[1]):
            table.add_row(f"  {court}", str(count))

        console.print(table)
    else:
        console.print("[yellow]수집된 판례 없음[/]")

    # 법령 현황
    stat_path = data_dir / "statutes.json"
    if stat_path.exists():
        data = json.loads(stat_path.read_text(encoding="utf-8"))
        console.print(f"\n[bold]법령[/]: {len(data)}개")
        for s in data:
            console.print(f"  - {s['name']}: {len(s.get('articles', []))}개 조문")


@app.command()
def search(
    query: str = typer.Argument(help="검색어"),
    field: str = typer.Option("all", help="검색 필드: all, issues, summary, full_text"),
):
    """수집된 판례에서 키워드 검색"""
    prec_path = Path("data/precedents.json")
    if not prec_path.exists():
        console.print("[red]수집된 판례가 없습니다. 먼저 crawl 명령을 실행하세요.[/]")
        raise typer.Exit(1)

    data = json.loads(prec_path.read_text(encoding="utf-8"))

    search_fields = ["case_name", "issues", "summary", "full_text", "reference_articles"]
    if field != "all":
        search_fields = [field]

    results = []
    for prec in data:
        for f in search_fields:
            if query in prec.get(f, ""):
                results.append(prec)
                break

    if not results:
        console.print(f"[yellow]'{query}' 검색 결과 없음[/]")
        return

    console.print(f"\n[bold green]'{query}' 검색 결과: {len(results)}건[/]\n")

    for i, prec in enumerate(results, 1):
        console.print(f"[bold]{i}. [{prec.get('case_number', '?')}] {prec.get('case_name', '제목 없음')[:80]}[/]")
        console.print(f"   법원: {prec.get('court_name', '?')} | 선고일: {prec.get('judgment_date', '?')} | {prec.get('judgment_type', '?')}")

        # 검색어가 포함된 요지 snippet
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


@app.command(name="run-all")
def run_all(
    output_dir: str = typer.Option("data", "--output", "-o"),
):
    """전체 크롤링 실행 (법제처 판례 + 법령)"""
    console.print("[bold]전체 크롤링 시작[/]\n")

    # 1. 법제처 판례
    console.print("[bold cyan]1/2. 법제처 판례 크롤링[/]")
    from precedent_finder.crawlers.court_scraper import crawl as crawl_precedents

    keywords = ["학원", "교습소", "교육서비스", "학원법위반", "무등록학원", "과외교습", "교육청", "유아", "초등"]
    results = crawl_precedents(
        keywords=keywords,
        max_per_keyword=50,
        max_pages=3,
        output_dir=output_dir,
    )
    console.print(f"  → 판례 {len(results)}건\n")

    # 2. 법령 조문
    console.print("[bold cyan]2/2. 법령 조문 크롤링[/]")
    from precedent_finder.crawlers.law_scraper import crawl_statutes

    statutes = crawl_statutes(output_dir=output_dir)
    console.print(f"  → 법령 {len(statutes)}개\n")

    console.print("[bold green]전체 크롤링 완료![/]")


if __name__ == "__main__":
    app()
