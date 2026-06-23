"""벡터 검색 엔진 — ChromaDB + Ollama/OpenAI 임베딩"""

import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from .chunker import Chunk


CHROMA_DB_PATH = "data/chroma_db"
COLLECTION_NAME = "precedent_finder"


class Retriever:
    """벡터 기반 문서 검색"""

    def __init__(
        self,
        embed_model: str = "bge-m3",
        db_path: str = CHROMA_DB_PATH,
    ):
        self.embed_model = embed_model
        self.db_path = db_path
        self._client = None
        self._collection = None
        self._embed_fn = None

    def _get_embed_fn(self):
        """임베딩 함수 반환 (OpenAI 고정)"""
        if self._embed_fn:
            return self._embed_fn

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 환경변수를 설정하세요.")

        from openai import OpenAI
        self._openai_client = OpenAI(api_key=api_key)
        self._embed_fn = self._openai_embed
        print("[임베딩] OpenAI (text-embedding-3-small)")
        return self._embed_fn

    def _ollama_embed(self, texts: list[str]) -> list[list[float]]:
        import ollama
        results = []
        for text in texts:
            resp = ollama.embeddings(model=self.embed_model, prompt=text[:8000])
            results.append(resp["embedding"])
        return results

    def _openai_embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=[t[:8000] for t in texts],
        )
        return [d.embedding for d in resp.data]

    def _get_collection(self):
        """ChromaDB 컬렉션 반환"""
        if self._collection:
            return self._collection

        import chromadb

        Path(self.db_path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=self.db_path)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        return self._collection

    def index_chunks(self, chunks: list[Chunk], batch_size: int = 50):
        """청크를 임베딩하여 벡터 DB에 저장"""
        if not chunks:
            return

        collection = self._get_collection()
        embed_fn = self._get_embed_fn()

        # 배치 처리
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [c.content for c in batch]
            ids = [c.id for c in batch]
            metadatas = [c.metadata for c in batch]

            embeddings = embed_fn(texts)

            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
            print(f"  인덱싱: {min(i + batch_size, len(chunks))}/{len(chunks)}")

    def compact(self):
        """벡터 DB(chroma.sqlite3) 압축.

        반복 인덱싱 시 ChromaDB가 FTS 세그먼트를 병합 없이 누적하고
        쓰기 큐(embeddings_queue)도 남겨 파일이 비대해진다. 인덱싱 직후
        FTS 병합 + 큐 비우기 + VACUUM으로 죽은 공간을 회수한다.
        (예: 55MB → 36MB). 내부 테이블명은 chroma 버전에 따라 다를 수
        있으므로 각 단계를 방어적으로 처리한다.
        """
        import sqlite3

        db_file = Path(self.db_path) / "chroma.sqlite3"
        if not db_file.exists():
            return

        # VACUUM은 단독 연결을 요구하므로 chroma 클라이언트 참조를 해제
        self._client = None
        self._collection = None

        conn = sqlite3.connect(str(db_file), timeout=30.0)
        try:
            for stmt in (
                "INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('optimize')",
                "DELETE FROM embeddings_queue",
            ):
                try:
                    conn.execute(stmt)
                    conn.commit()
                except sqlite3.OperationalError as e:
                    print(f"  [압축] 건너뜀: {e}")
            conn.execute("VACUUM")
        finally:
            conn.close()

    def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        """유사도 검색"""
        collection = self._get_collection()
        embed_fn = self._get_embed_fn()

        query_embedding = embed_fn([query])[0]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                chunks.append(Chunk(
                    id=chunk_id,
                    content=results["documents"][0][i],
                    metadata=results["metadatas"][0][i] if results["metadatas"] else {},
                ))
        return chunks

    def hybrid_search(self, query: str, top_k: int = 5) -> list[Chunk]:
        """하이브리드 검색 — 벡터 유사도 + 키워드 매칭"""
        # 벡터 검색 (더 많이 가져와서 리랭킹)
        vector_results = self.search(query, top_k=top_k * 2)

        # 키워드 점수 부여
        scored = []
        for chunk in vector_results:
            keyword_score = 0
            content_lower = chunk.content.lower()
            query_terms = query.split()
            for term in query_terms:
                if term.lower() in content_lower:
                    keyword_score += 1
            keyword_score = keyword_score / max(len(query_terms), 1)

            # 가중 결합 (벡터 0.7 + 키워드 0.3)
            # vector_results는 이미 관련도순이므로 순위 기반 점수
            rank_score = 1.0 - (vector_results.index(chunk) / len(vector_results))
            final_score = 0.7 * rank_score + 0.3 * keyword_score
            scored.append((chunk, final_score))

        scored.sort(key=lambda x: -x[1])
        return [c for c, _ in scored[:top_k]]
