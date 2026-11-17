from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS import_batches (
    batch_id TEXT PRIMARY KEY,
    digest TEXT NOT NULL,
    story_count INTEGER NOT NULL CHECK(story_count > 0)
);
CREATE TABLE IF NOT EXISTS stories (
    story_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    title TEXT NOT NULL,
    tradition TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    document TEXT NOT NULL,
    PRIMARY KEY(story_id, revision)
);
CREATE INDEX IF NOT EXISTS stories_by_tradition ON stories(tradition, story_id, revision);
CREATE TABLE IF NOT EXISTS batch_stories (
    batch_id TEXT NOT NULL REFERENCES import_batches(batch_id) ON DELETE RESTRICT,
    story_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY(batch_id, story_id, revision),
    FOREIGN KEY(story_id, revision) REFERENCES stories(story_id, revision) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS batch_stories_by_story ON batch_stories(story_id, revision, batch_id);
CREATE TABLE IF NOT EXISTS revision_edges (
    story_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    parent_revision INTEGER NOT NULL,
    PRIMARY KEY(story_id, revision, parent_revision),
    FOREIGN KEY(story_id, revision) REFERENCES stories(story_id, revision) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS revision_edges_by_parent ON revision_edges(story_id, parent_revision);
CREATE TABLE IF NOT EXISTS branch_marks (
    mark_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    branch TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    action TEXT NOT NULL CHECK(action IN ('retired', 'merged')),
    target_branch TEXT,
    merge_revision INTEGER,
    note TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    digest TEXT NOT NULL,
    UNIQUE(story_id, branch, sequence)
);
CREATE INDEX IF NOT EXISTS branch_marks_by_story ON branch_marks(story_id, branch, sequence);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    story_revision INTEGER NOT NULL,
    annotator TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    pattern TEXT NOT NULL,
    youngest_outcome TEXT NOT NULL,
    evidence_event_ids TEXT NOT NULL,
    note TEXT NOT NULL,
    digest TEXT NOT NULL,
    UNIQUE(story_id, story_revision, annotator, sequence),
    FOREIGN KEY(story_id, story_revision) REFERENCES stories(story_id, revision)
);
CREATE INDEX IF NOT EXISTS decisions_by_story ON decisions(story_id, story_revision, annotator, sequence);
CREATE TABLE IF NOT EXISTS adjudications (
    adjudication_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    story_revision INTEGER NOT NULL,
    moderator TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    pattern TEXT NOT NULL,
    youngest_outcome TEXT NOT NULL,
    evidence_event_ids TEXT NOT NULL,
    rationale TEXT NOT NULL,
    digest TEXT NOT NULL,
    UNIQUE(story_id, story_revision, sequence),
    FOREIGN KEY(story_id, story_revision) REFERENCES stories(story_id, revision)
);
CREATE INDEX IF NOT EXISTS adjudications_by_story ON adjudications(story_id, story_revision, sequence);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    document TEXT NOT NULL
);
"""


class StoryStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("a file-backed database is required for durable local reports")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            self._backfill_revision_edges(connection)
        finally:
            connection.close()

    @staticmethod
    def _backfill_revision_edges(connection: sqlite3.Connection) -> None:
        """把各修订文档声明（或线性默认）的父修订解析成结构边；只增不改，可安全重放。"""
        from story_patterns.catalog.branches import effective_parents

        rows = connection.execute("SELECT story_id, revision, document FROM stories").fetchall()
        known = {(row["story_id"], row["revision"]) for row in rows}
        for row in rows:
            document = json.loads(row["document"])
            for parent in effective_parents(document):
                if (row["story_id"], parent) not in known:
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO revision_edges(story_id, revision, parent_revision) VALUES(?,?,?)",
                    (row["story_id"], row["revision"], parent),
                )

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read_connection(self):
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def story_document(self, story_id: str, revision: int) -> dict | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT document FROM stories WHERE story_id=? AND revision=?", (story_id, revision)
            ).fetchone()
        return json.loads(row["document"]) if row else None

    def story_versions(self, story_id: str) -> dict[int, dict]:
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT document FROM stories WHERE story_id=? ORDER BY revision", (story_id,)
            ).fetchall()
        return {item["revision"]: item for item in (json.loads(row["document"]) for row in rows)}

    def branch_marks(self, story_id: str | None = None) -> list[dict]:
        with self.read_connection() as connection:
            if story_id is None:
                rows = connection.execute(
                    "SELECT * FROM branch_marks ORDER BY story_id, branch, sequence"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM branch_marks WHERE story_id=? ORDER BY branch, sequence", (story_id,)
                ).fetchall()
        return [dict(row) for row in rows]

    def list_stories(self, tradition: str | None = None) -> list[dict]:
        with self.read_connection() as connection:
            if tradition is None:
                rows = connection.execute(
                    "SELECT document FROM stories ORDER BY tradition, story_id, revision"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT document FROM stories WHERE tradition=? ORDER BY story_id, revision",
                    (tradition,),
                ).fetchall()
        return [json.loads(row["document"]) for row in rows]

    def latest_decisions(self, story_id: str, revision: int) -> list[dict]:
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT d.* FROM decisions d JOIN ("
                "SELECT annotator, MAX(sequence) AS latest FROM decisions "
                "WHERE story_id=? AND story_revision=? GROUP BY annotator"
                ") newest ON d.annotator=newest.annotator AND d.sequence=newest.latest "
                "WHERE d.story_id=? AND d.story_revision=? ORDER BY d.annotator",
                (story_id, revision, story_id, revision),
            ).fetchall()
        return [dict(row) | {"evidence_event_ids": json.loads(row["evidence_event_ids"])} for row in rows]

    def decision_history(self, story_id: str, revision: int) -> tuple[list[dict], list[dict]]:
        with self.read_connection() as connection:
            votes = connection.execute(
                "SELECT * FROM decisions WHERE story_id=? AND story_revision=? ORDER BY annotator, sequence",
                (story_id, revision),
            ).fetchall()
            adjudications = connection.execute(
                "SELECT * FROM adjudications WHERE story_id=? AND story_revision=? ORDER BY sequence",
                (story_id, revision),
            ).fetchall()
        return (
            [dict(row) | {"evidence_event_ids": json.loads(row["evidence_event_ids"])} for row in votes],
            [dict(row) | {"evidence_event_ids": json.loads(row["evidence_event_ids"])} for row in adjudications],
        )

    def latest_decisions_for_stories(self, identities: list[tuple[str, int]]) -> dict[tuple[str, int], list[dict]]:
        result = {}
        for story_id, revision in identities:
            result[(story_id, revision)] = self.latest_decisions(story_id, revision)
        return result

    def analysis_snapshot(self, tradition: str | None) -> tuple[list[dict], dict, dict, dict]:
        with self.read_connection() as connection:
            connection.execute("BEGIN")
            if tradition is None:
                rows = connection.execute(
                    "SELECT document FROM stories ORDER BY tradition, story_id, revision"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT document FROM stories WHERE tradition=? ORDER BY story_id, revision", (tradition,)
                ).fetchall()
            stories = [json.loads(row["document"]) for row in rows]
            identities = [(item["story_id"], item["revision"]) for item in stories]
            decisions = {}
            adjudications = {}
            for story_id, revision in identities:
                latest = connection.execute(
                    "SELECT d.* FROM decisions d JOIN ("
                    "SELECT annotator, MAX(sequence) AS latest FROM decisions "
                    "WHERE story_id=? AND story_revision=? GROUP BY annotator"
                    ") newest ON d.annotator=newest.annotator AND d.sequence=newest.latest "
                    "WHERE d.story_id=? AND d.story_revision=? ORDER BY d.annotator",
                    (story_id, revision, story_id, revision),
                ).fetchall()
                decisions[(story_id, revision)] = [
                    dict(row) | {"evidence_event_ids": json.loads(row["evidence_event_ids"])} for row in latest
                ]
                adjudication = connection.execute(
                    "SELECT * FROM adjudications WHERE story_id=? AND story_revision=? "
                    "ORDER BY sequence DESC LIMIT 1", (story_id, revision)
                ).fetchone()
                adjudications[(story_id, revision)] = (
                    dict(adjudication) | {"evidence_event_ids": json.loads(adjudication["evidence_event_ids"])}
                    if adjudication else None
                )
            origins = {identity: [] for identity in identities}
            if identities:
                rows = connection.execute(
                    "SELECT batch_id, story_id, revision FROM batch_stories ORDER BY batch_id"
                ).fetchall()
                for row in rows:
                    identity = (row["story_id"], row["revision"])
                    if identity in origins:
                        origins[identity].append(row["batch_id"])
        return stories, decisions, origins, adjudications

    def catalog_manifest(self) -> tuple[list[dict], list[dict]]:
        with self.read_connection() as connection:
            batches = connection.execute(
                "SELECT b.batch_id, b.digest, b.story_count, COUNT(bs.story_id) AS linked_story_count "
                "FROM import_batches b LEFT JOIN batch_stories bs ON bs.batch_id=b.batch_id "
                "GROUP BY b.batch_id ORDER BY b.batch_id"
            ).fetchall()
            stories = connection.execute(
                "SELECT document FROM stories ORDER BY story_id, revision"
            ).fetchall()
        return [dict(row) for row in batches], [json.loads(row["document"]) for row in stories]

    def catalog_audit_snapshot(self) -> dict:
        with self.read_connection() as connection:
            return {
                "stories": [dict(row) for row in connection.execute("SELECT * FROM stories ORDER BY story_id, revision")],
                "batches": [dict(row) for row in connection.execute("SELECT * FROM import_batches ORDER BY batch_id")],
                "batch_stories": [dict(row) for row in connection.execute(
                    "SELECT * FROM batch_stories ORDER BY batch_id, story_id, revision")],
                "revision_edges": [dict(row) for row in connection.execute(
                    "SELECT * FROM revision_edges ORDER BY story_id, revision, parent_revision")],
                "branch_marks": [dict(row) for row in connection.execute(
                    "SELECT * FROM branch_marks ORDER BY story_id, branch, sequence")],
                "decisions": [dict(row) for row in connection.execute("SELECT * FROM decisions ORDER BY decision_id")],
                "adjudications": [dict(row) for row in connection.execute(
                    "SELECT * FROM adjudications ORDER BY adjudication_id")],
                "reports": [dict(row) for row in connection.execute("SELECT * FROM reports ORDER BY report_id")],
            }

    def report_document(self, report_id: str) -> dict | None:
        with self.read_connection() as connection:
            row = connection.execute("SELECT document FROM reports WHERE report_id=?", (report_id,)).fetchone()
        return json.loads(row["document"]) if row else None

    def integrity_issues(self) -> list[str]:
        with self.read_connection() as connection:
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        issues = [f"foreign key violation: {tuple(row)}" for row in foreign_keys]
        if quick_check != "ok":
            issues.append(f"SQLite quick_check: {quick_check}")
        return issues
