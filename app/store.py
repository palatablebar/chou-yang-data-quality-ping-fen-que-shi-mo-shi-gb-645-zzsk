"""SQLite 存储：数据集原文、运行记录、输入快照与完整结果快照。

约定：
- 数据集按名字唯一：同名文件重新采信即覆盖原文，历史运行仍按 digest 保留；
- 每条运行（含修订）都另存一份采信快照，修订永远能取回基线原文与解析结果；
- 运行记录按 (dataset, digest, rules_version) 幂等：同输入重跑不新增行；
- 修订按 (dataset, 基线, 更正文摘要, rules_version) 幂等：同一更正重试复用同一条记录；
- 运行、输入快照与修订账在同一个事务里写入：中途失败不留半条记录；
- 分数与比率落 TEXT（Decimal 字符串），不落 float；
- 页面永远只展示一条运行记录，导出读的是同一条快照。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    name TEXT PRIMARY KEY,
    digest TEXT NOT NULL,
    encoding TEXT NOT NULL,
    declared_encoding TEXT,
    bytes INTEGER NOT NULL,
    content BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    digest TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    version INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'base',
    base_run_id TEXT,
    score TEXT NOT NULL,
    grade TEXT NOT NULL,
    rows_in INTEGER NOT NULL,
    rows_accepted INTEGER NOT NULL,
    rows_unique INTEGER NOT NULL,
    rows_dup INTEGER NOT NULL,
    rows_quarantine INTEGER NOT NULL,
    rows_blank INTEGER NOT NULL,
    cells_total INTEGER NOT NULL,
    cells_missing INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_seq INTEGER NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_inputs (
    run_id TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_identity ON runs(name, digest, rules_version);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_version_unique ON runs(name, version);
CREATE INDEX IF NOT EXISTS idx_runs_version ON runs(name, version DESC);
CREATE INDEX IF NOT EXISTS idx_runs_seen ON runs(name, seen_seq DESC);
CREATE TABLE IF NOT EXISTS revisions (
    run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    base_run_id TEXT NOT NULL,
    correction_name TEXT NOT NULL,
    correction_digest TEXT NOT NULL,
    corrected INTEGER NOT NULL,
    pending INTEGER NOT NULL,
    kept_original INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    revision_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_revisions_identity
    ON revisions(name, base_run_id, correction_digest, rules_version);
"""

# 旧库补列：runs 早期只有 base 一类，缺 kind / base_run_id 两列
_RUN_COLUMNS = {
    "kind": "TEXT NOT NULL DEFAULT 'base'",
    "base_run_id": "TEXT",
}


def _dec(text):
    return None if text is None else Decimal(str(text))


def pack_input(snapshot: dict) -> str:
    """采信快照落库格式：原文字节已由 M1 转 base64，整体按 JSON 存。

    修订只读这份快照，不碰数据集当前内容；同一字节重算摘要必须逐位相同。
    """
    return json.dumps(snapshot, ensure_ascii=False)


class Store:
    def __init__(self, path: str):
        self.path = str(path)
        Path(self.path).resolve().parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn) -> None:
        existing = {row["name"] for row in
                    conn.execute("PRAGMA table_info(runs)").fetchall()}
        for name, decl in _RUN_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {decl}")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- 数据集 ----------
    def save_dataset(self, *, name: str, digest: str, encoding: str,
                     declared_encoding: str | None, data: bytes, stamp: str) -> None:
        """存原始字节：GB18030 文件重算摘要必须与首次采信逐位相同。"""
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO datasets (name,digest,encoding,declared_encoding,bytes,
                        content,updated_at) VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                     digest=excluded.digest, encoding=excluded.encoding,
                     declared_encoding=excluded.declared_encoding,
                     bytes=excluded.bytes, content=excluded.content,
                     updated_at=excluded.updated_at""",
                (name, digest, encoding, declared_encoding, len(data), data, stamp))

    def get_dataset(self, name: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def get_ingest_snapshot(self, run_id: str) -> dict | None:
        """同一次运行的采信快照：修订复用原解析结果，不重导、不重算基线。"""
        with self.connect() as conn:
            row = conn.execute("SELECT snapshot_json FROM run_inputs WHERE run_id=?",
                               (run_id,)).fetchone()
        return json.loads(row["snapshot_json"]) if row else None

    def list_datasets(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name,digest,encoding,bytes,updated_at FROM datasets ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- 运行记录 ----------
    def latest_version(self, name: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(version) AS v FROM runs WHERE name=?", (name,)).fetchone()
        return int(row["v"] or 0)

    def find_run(self, name: str, digest: str, rules_version: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE name=? AND digest=? AND rules_version=?",
                (name, digest, rules_version)).fetchone()
        return dict(row) if row else None

    def save_run(self, run: dict, summary: dict, *, snapshot: dict | None = None) -> None:
        """写入一条运行；给了采信快照就连快照一起落，同一事务提交。"""
        with self.connect() as conn:
            self._insert_run(conn, run, summary)
            if snapshot is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO run_inputs (run_id,snapshot_json) "
                    "VALUES (?,?)", (run["run_id"], pack_input(snapshot)))

    def _insert_run(self, conn, run: dict, summary: dict) -> None:
        conn.execute(
            """INSERT INTO runs (run_id,name,digest,rules_version,version,kind,
                    base_run_id,score,grade,rows_in,rows_accepted,rows_unique,
                    rows_dup,rows_quarantine,rows_blank,cells_total,cells_missing,
                    created_at,finished_at,last_seen_at,seen_seq,summary_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run["run_id"], run["name"], run["digest"], run["rules_version"],
             int(run["version"]), run.get("kind", "base"), run.get("base_run_id"),
             str(run["score"]), run["grade"],
             int(run["rows_in"]), int(run["rows_accepted"]), int(run["rows_unique"]),
             int(run["rows_dup"]), int(run["rows_quarantine"]),
             int(run["rows_blank"]), int(run["cells_total"]),
             int(run["cells_missing"]), run["created_at"], run["finished_at"],
             run["created_at"], self._next_seq(conn),
             json.dumps(summary, ensure_ascii=False)))

    def save_revision(self, run: dict, summary: dict, *, revision: dict,
                      snapshot: dict) -> int:
        """修订落库：运行行 + 采信快照 + 修订账，一个事务，要么全有要么全无。

        版本号在同一事务里现取，`UNIQUE(name, version)` 兜底并发：后写入的
        那条整条回滚，不会留下半条记录，也不会出现两条同版本。返回实际版本。
        """
        with self.connect() as conn:
            version = self._next_version(conn, run["name"])
            run = {**run, "version": version}
            revision = {**revision, "version": version}
            summary["run"]["version"] = version
            summary["manifest"]["version"] = version
            if summary.get("revision"):
                summary["revision"]["version"] = version
            self._insert_run(conn, run, summary)
            conn.execute("INSERT INTO run_inputs (run_id,snapshot_json) VALUES (?,?)",
                         (run["run_id"], pack_input(snapshot)))
            conn.execute(
                """INSERT INTO revisions (run_id,name,rules_version,base_run_id,
                        correction_name,correction_digest,corrected,pending,
                        kept_original,created_at,revision_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (run["run_id"], run["name"], run["rules_version"],
                 revision["base_run_id"], revision["correction_name"],
                 revision["correction_digest"], int(revision["counts"]["corrected"]),
                 int(revision["counts"]["pending"]),
                 int(revision["counts"]["kept_original"]),
                 run["created_at"], json.dumps(revision, ensure_ascii=False)))
            return version

    def _next_version(self, conn, name: str) -> int:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM runs "
                           "WHERE name=?", (name,)).fetchone()
        return int(row["v"])

    def load_revision(self, run_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT revision_json FROM revisions WHERE run_id=?",
                               (run_id,)).fetchone()
        return json.loads(row["revision_json"]) if row else None

    def find_revision_in_chain(self, name: str, run_id: str,
                               correction_digest: str,
                               rules_version: str) -> dict | None:
        """沿修订祖先链找同一更正：已应用过的更正再提交时复用，不重复扣分。"""
        with self.connect() as conn:
            current = conn.execute(
                "SELECT * FROM runs WHERE run_id=? AND name=?",
                (run_id, name)).fetchone()
            seen: set[str] = set()
            while current is not None and current["run_id"] not in seen:
                seen.add(current["run_id"])
                row = conn.execute(
                    """SELECT * FROM revisions WHERE run_id=? AND correction_digest=?
                       AND rules_version=?""",
                    (current["run_id"], correction_digest, rules_version)).fetchone()
                if row is not None:
                    return dict(row)
                base_id = current["base_run_id"]
                if not base_id:
                    return None
                current = conn.execute("SELECT * FROM runs WHERE run_id=?",
                                       (base_id,)).fetchone()
        return None

    def base_run_for(self, name: str, base_run_id: str | None) -> dict | None:
        """修订基线：显式指定优先，否则取同名最近一次运行（含此前的修订）。

        叠加语义：第二份更正文默认修的是「已经发布的上一版」，不会把
        第一份更正的成果丢掉。
        """
        with self.connect() as conn:
            if base_run_id:
                row = conn.execute(
                    "SELECT * FROM runs WHERE run_id=? AND name=?",
                    (base_run_id, name)).fetchone()
                return dict(row) if row else None
            row = conn.execute(
                "SELECT * FROM runs WHERE name=? ORDER BY version DESC LIMIT 1",
                (name,)).fetchone()
        return dict(row) if row else None

    def touch_run(self, run_id: str, stamp: str) -> None:
        """命中幂等复用时刷新「最近一次查看」，导航回各页仍停在这条记录上。"""
        with self.connect() as conn:
            conn.execute("UPDATE runs SET last_seen_at=?, seen_seq=? WHERE run_id=?",
                         (stamp, self._next_seq(conn), run_id))

    def _next_seq(self, conn) -> int:
        row = conn.execute("SELECT COALESCE(MAX(seen_seq), 0) + 1 AS n FROM runs").fetchone()
        return int(row["n"])

    def latest_run(self, name: str | None = None) -> dict | None:
        with self.connect() as conn:
            if name:
                row = conn.execute(
                    "SELECT * FROM runs WHERE name=? ORDER BY version DESC LIMIT 1",
                    (name,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM runs ORDER BY seen_seq DESC LIMIT 1"
                ).fetchone()
        return dict(row) if row else None

    def get_run(self, run_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY seen_seq DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(row) for row in rows]

    def load_result(self, run_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT summary_json FROM runs WHERE run_id=?",
                               (run_id,)).fetchone()
        return json.loads(row["summary_json"]) if row else None

    def count_runs(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"])
