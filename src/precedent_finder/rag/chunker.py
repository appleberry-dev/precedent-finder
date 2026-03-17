"""텍스트 청킹 — 판례/법령을 RAG에 적합한 크기로 분할"""

from dataclasses import dataclass, field


@dataclass
class Chunk:
    """검색/임베딩 단위 텍스트 조각"""
    id: str = ""                # "precedent_1_0", "statute_3_2"
    source_type: str = ""       # "precedent" | "statute"
    source_id: int = 0          # DB id
    chunk_index: int = 0
    content: str = ""
    metadata: dict = field(default_factory=dict)
    # metadata: case_number, court_name, judgment_date, section, law_name, article_number 등


class Chunker:
    """텍스트 분할기"""

    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def _split_text(self, text: str) -> list[str]:
        """텍스트를 chunk_size 단위로 분할 (문장 경계 우선)"""
        if not text or len(text) <= self.chunk_size:
            return [text] if text else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size

            if end < len(text):
                # 문장 경계에서 분할 시도 (마침표, 개행)
                for sep in ["\n\n", "\n", ". ", "다. ", "다.\n"]:
                    last_sep = text.rfind(sep, start, end)
                    if last_sep > start + self.chunk_size // 2:
                        end = last_sep + len(sep)
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - self.overlap
            if start >= len(text):
                break

        return chunks

    def chunk_precedent(self, prec: dict) -> list[Chunk]:
        """판례 1건을 청크로 분할"""
        chunks = []
        prec_id = prec.get("id", 0)
        base_metadata = {
            "case_number": prec.get("case_number", ""),
            "court_name": prec.get("court_name", ""),
            "judgment_date": prec.get("judgment_date", ""),
            "case_name": prec.get("case_name", ""),
        }

        # 메타 청크 (항상 1개)
        meta_text = (
            f"[{prec.get('case_number', '?')}] {prec.get('case_name', '')}\n"
            f"법원: {prec.get('court_name', '?')} | "
            f"선고일: {prec.get('judgment_date', '?')} | "
            f"{prec.get('judgment_type', '')}"
        )
        chunks.append(Chunk(
            id=f"precedent_{prec_id}_meta",
            source_type="precedent",
            source_id=prec_id,
            chunk_index=0,
            content=meta_text,
            metadata={**base_metadata, "section": "meta"},
        ))

        # 섹션별 청킹
        sections = [
            ("issues", "판시사항"),
            ("summary", "판결요지"),
            ("full_text", "판례내용"),
            ("reference_articles", "참조조문"),
        ]

        chunk_idx = 1
        for field_name, section_label in sections:
            text = prec.get(field_name, "")
            if not text:
                continue

            # 섹션 헤더 포함
            text_with_header = f"[{section_label}]\n{text}"
            parts = self._split_text(text_with_header)

            for part in parts:
                chunks.append(Chunk(
                    id=f"precedent_{prec_id}_{chunk_idx}",
                    source_type="precedent",
                    source_id=prec_id,
                    chunk_index=chunk_idx,
                    content=part,
                    metadata={**base_metadata, "section": section_label},
                ))
                chunk_idx += 1

        return chunks

    def chunk_statute(self, statute: dict) -> list[Chunk]:
        """법령 1건을 청크로 분할 (조문 단위)"""
        chunks = []
        stat_id = statute.get("id", 0)
        law_name = statute.get("law_name", "")

        text = statute.get("content", "")
        article_number = statute.get("article_number", "")
        article_title = statute.get("article_title", "")

        if not text:
            return []

        header = f"{law_name} {article_number}"
        if article_title:
            header += f"({article_title})"

        full_text = f"[법령] {header}\n{text}"
        parts = self._split_text(full_text)

        for i, part in enumerate(parts):
            chunks.append(Chunk(
                id=f"statute_{stat_id}_{i}",
                source_type="statute",
                source_id=stat_id,
                chunk_index=i,
                content=part,
                metadata={
                    "law_name": law_name,
                    "article_number": article_number,
                    "article_title": article_title,
                },
            ))

        return chunks

    def chunk_all(self, store) -> list[Chunk]:
        """DB의 모든 판례+법령을 청킹"""
        all_chunks = []

        # 판례
        for prec in store.list_precedents():
            all_chunks.extend(self.chunk_precedent(prec))

        # 법령
        for statute in store.list_statutes():
            all_chunks.extend(self.chunk_statute(statute))

        return all_chunks
