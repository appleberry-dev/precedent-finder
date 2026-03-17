"""NotebookLM용 판례 데이터 내보내기"""

import json
import re
from pathlib import Path


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """파일명에 사용할 수 없는 문자 제거"""
    name = re.sub(r'[<>:"/\\|?*\[\]()]', '', name)
    name = name.replace(" ", "_")
    return name[:max_len]


def precedent_to_markdown(prec: dict) -> str:
    """판례 dict를 Markdown 문자열로 변환"""
    case_number = prec.get("case_number", "번호미상")
    case_name = prec.get("case_name", "사건명 없음")

    lines = [f"# [{case_number}] {case_name}"]
    lines.append("")

    # 메타 정보
    meta_fields = [
        ("법원", "court_name"),
        ("선고일", "judgment_date"),
        ("판결유형", "judgment_type"),
        ("사건종류", "case_type"),
    ]
    for label, key in meta_fields:
        value = prec.get(key, "")
        if value:
            lines.append(f"- {label}: {value}")

    source_url = prec.get("source_url", "")
    if source_url:
        lines.append(f"- 출처: {source_url}")

    lines.append("")

    # 본문 섹션
    sections = [
        ("판시사항", "issues"),
        ("판결요지", "summary"),
        ("참조조문", "reference_articles"),
        ("참조판례", "reference_cases"),
        ("판례내용", "full_text"),
    ]
    for title, key in sections:
        content = prec.get(key, "")
        if content:
            lines.append(f"## {title}")
            lines.append("")
            lines.append(content)
            lines.append("")

    return "\n".join(lines)


def export_to_notebook_lm(
    input_path: str = "data/precedents.json",
    output_dir: str = "data/notebook_lm",
) -> list[Path]:
    """판례 JSON을 NotebookLM용 Markdown 파일들로 변환

    Returns:
        생성된 파일 경로 리스트
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not data:
        print("[경고] 데이터가 없습니다.")
        return []

    created_files = []
    all_markdown_parts = []

    for i, prec in enumerate(data, 1):
        md = precedent_to_markdown(prec)
        all_markdown_parts.append(md)

        # 개별 파일
        case_number = prec.get("case_number", f"unknown_{i}")
        filename = sanitize_filename(case_number) + ".md"
        file_path = output_dir / filename
        file_path.write_text(md, encoding="utf-8")
        created_files.append(file_path)
        print(f"  [{i}/{len(data)}] {filename}")

    # 합본 파일
    all_path = output_dir / "all_precedents.md"
    separator = "\n\n---\n\n"
    all_path.write_text(separator.join(all_markdown_parts), encoding="utf-8")
    created_files.append(all_path)
    print(f"\n[완료] {len(data)}건 → {output_dir}/ ({len(created_files)}개 파일)")

    return created_files


if __name__ == "__main__":
    export_to_notebook_lm()
