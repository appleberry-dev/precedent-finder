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
