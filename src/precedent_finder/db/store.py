"""SQLite 기반 판례/법령 저장소"""

import json
import sqlite3
from pathlib import Path


DB_PATH = Path("data/precedent_finder.db")


class PrecedentStore:
    """판례 및 법령 SQLite 저장소"""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self):
        """테이블 생성"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS precedents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prec_seq TEXT UNIQUE,
                case_name TEXT,
                case_number TEXT,
                judgment_date TEXT,
                court_name TEXT,
                case_type TEXT,
                judgment_type TEXT,
                issues TEXT,
                summary TEXT,
                full_text TEXT,
                reference_articles TEXT,
                reference_cases TEXT,
                source_url TEXT,
                pdf_path TEXT,
                source TEXT DEFAULT 'law_site',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS statutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_name TEXT,
                article_number TEXT,
                article_title TEXT,
                content TEXT,
                source_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(law_name, article_number)
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_prec_case_number ON precedents(case_number);
            CREATE INDEX IF NOT EXISTS idx_prec_court ON precedents(court_name);
            CREATE INDEX IF NOT EXISTS idx_prec_date ON precedents(judgment_date);
            CREATE INDEX IF NOT EXISTS idx_statute_law ON statutes(law_name);
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
        """)
        self.conn.commit()

    # ------ 판례 CRUD ------

    def upsert_precedent(self, prec: dict, source: str = "law_site") -> int:
        """판례 저장 (중복 시 업데이트)"""
        # prec_seq가 없으면 case_number + court_name 조합으로 생성
        prec_seq = prec.get("prec_seq") or f"{prec.get('case_number', '')}_{prec.get('court_name', '')}"

        cur = self.conn.execute("""
            INSERT INTO precedents (
                prec_seq, case_name, case_number, judgment_date, court_name,
                case_type, judgment_type, issues, summary, full_text,
                reference_articles, reference_cases, source_url, pdf_path, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(prec_seq) DO UPDATE SET
                case_name = COALESCE(NULLIF(excluded.case_name, ''), case_name),
                full_text = COALESCE(NULLIF(excluded.full_text, ''), full_text),
                pdf_path = COALESCE(NULLIF(excluded.pdf_path, ''), pdf_path),
                summary = COALESCE(NULLIF(excluded.summary, ''), summary),
                issues = COALESCE(NULLIF(excluded.issues, ''), issues)
        """, (
            prec_seq,
            prec.get("case_name", ""),
            prec.get("case_number", ""),
            prec.get("judgment_date", ""),
            prec.get("court_name", ""),
            prec.get("case_type", ""),
            prec.get("judgment_type", ""),
            prec.get("issues", ""),
            prec.get("summary", ""),
            prec.get("full_text", ""),
            prec.get("reference_articles", ""),
            prec.get("reference_cases", ""),
            prec.get("source_url", ""),
            prec.get("pdf_path", ""),
            source,
        ))
        self.conn.commit()
        return cur.lastrowid

    def get_precedent(self, prec_seq: str) -> dict | None:
        """단건 조회"""
        row = self.conn.execute(
            "SELECT * FROM precedents WHERE prec_seq = ?", (prec_seq,)
        ).fetchone()
        return dict(row) if row else None

    def search_precedents(self, query: str, fields: list[str] | None = None) -> list[dict]:
        """키워드 검색"""
        if fields is None:
            fields = ["case_name", "issues", "summary", "full_text", "reference_articles"]

        conditions = " OR ".join(f"{f} LIKE ?" for f in fields)
        params = [f"%{query}%" for _ in fields]

        rows = self.conn.execute(
            f"SELECT * FROM precedents WHERE {conditions} ORDER BY judgment_date DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def list_precedents(self) -> list[dict]:
        """전체 판례 목록"""
        rows = self.conn.execute(
            "SELECT * FROM precedents ORDER BY judgment_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def count_precedents(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM precedents").fetchone()[0]

    def count_precedents_by_court(self) -> list[tuple[str, int]]:
        """법원별 판례 건수"""
        rows = self.conn.execute(
            "SELECT court_name, COUNT(*) as cnt FROM precedents GROUP BY court_name ORDER BY cnt DESC"
        ).fetchall()
        return [(r["court_name"] or "미상", r["cnt"]) for r in rows]

    def count_precedents_by_source(self) -> list[tuple[str, int]]:
        """출처별 판례 건수"""
        rows = self.conn.execute(
            "SELECT source, COUNT(*) as cnt FROM precedents GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
        return [(r["source"], r["cnt"]) for r in rows]

    # ------ 법령 CRUD ------

    def upsert_statute(self, law_name: str, article_number: str,
                       article_title: str = "", content: str = "",
                       source_url: str = "") -> int:
        """법령 조문 저장"""
        cur = self.conn.execute("""
            INSERT INTO statutes (law_name, article_number, article_title, content, source_url)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(law_name, article_number) DO UPDATE SET
                article_title = excluded.article_title,
                content = excluded.content,
                source_url = COALESCE(NULLIF(excluded.source_url, ''), source_url)
        """, (law_name, article_number, article_title, content, source_url))
        self.conn.commit()
        return cur.lastrowid

    def list_statutes(self, law_name: str | None = None) -> list[dict]:
        if law_name:
            rows = self.conn.execute(
                "SELECT * FROM statutes WHERE law_name = ? ORDER BY id", (law_name,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM statutes ORDER BY law_name, id").fetchall()
        return [dict(r) for r in rows]

    def count_statutes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0]

    def count_statutes_by_law(self) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT law_name, COUNT(*) as cnt FROM statutes GROUP BY law_name ORDER BY cnt DESC"
        ).fetchall()
        return [(r["law_name"], r["cnt"]) for r in rows]

    # ------ 마이그레이션 ------

    def import_from_json(self, json_path: str | Path, source: str = "law_site") -> int:
        """JSON 파일에서 판례 임포트"""
        json_path = Path(json_path)
        if not json_path.exists():
            print(f"[경고] 파일 없음: {json_path}")
            return 0

        data = json.loads(json_path.read_text(encoding="utf-8"))
        if not data:
            return 0

        count = 0
        for prec in data:
            self.upsert_precedent(prec, source=source)
            count += 1

        print(f"[마이그레이션] {json_path} → {count}건 임포트")
        return count

    # ------ 대화 기록 ------

    def create_conversation(self, title: str = "") -> int:
        """새 대화 생성, ID 반환"""
        cur = self.conn.execute(
            "INSERT INTO conversations (title) VALUES (?)", (title,)
        )
        self.conn.commit()
        return cur.lastrowid

    def update_conversation_title(self, conv_id: int, title: str):
        """대화 제목 업데이트"""
        self.conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id)
        )
        self.conn.commit()

    def add_message(self, conversation_id: int, role: str, content: str,
                    sources: list[dict] | None = None) -> int:
        """대화에 메시지 추가"""
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        cur = self.conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, sources_json),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_conversations(self, limit: int = 50) -> list[dict]:
        """대화 목록 조회 (최신순)"""
        rows = self.conn.execute(
            "SELECT * FROM conversations ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_conversation_messages(self, conversation_id: int) -> list[dict]:
        """대화의 메시지 목록 조회"""
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
        result = []
        for r in rows:
            msg = dict(r)
            if msg["sources"]:
                msg["sources"] = json.loads(msg["sources"])
            result.append(msg)
        return result

    def delete_conversation(self, conversation_id: int):
        """대화 삭제"""
        self.conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        self.conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        self.conn.commit()

    # ------ 정리 ------

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
