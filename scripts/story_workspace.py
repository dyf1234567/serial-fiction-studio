#!/usr/bin/env python3
"""Portable state, retrieval, and draft transactions for serial fiction."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Iterable, Sequence

STATE_DIR = ".storywork"
EVENT_KINDS = {"fact", "setup", "payoff", "timeline", "decision", "chapter"}
TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
SCENE_FUNCTIONS = {"setup", "escalation", "reversal", "payoff", "aftermath", "transition", "character"}


class StoryError(RuntimeError):
    pass


def configure_stdio() -> None:
    """Emit predictable UTF-8 JSON and diagnostics on Windows and Unix."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if len(data) >= 4:
        pairs = max(1, len(data) // 2)
        odd_nuls = data[1::2].count(0)
        even_nuls = data[0::2].count(0)
        if odd_nuls > pairs // 2:
            return data.decode("utf-16-le")
        if even_nuls > pairs // 2:
            return data.decode("utf-16-be")
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def read_json_value(path: Path) -> object:
    try:
        return json.loads(read_text(path))
    except FileNotFoundError as exc:
        raise StoryError(f"缺少文件：{path}") from exc
    except OSError as exc:
        raise StoryError(f"无法读取文件：{path}: {exc}") from exc
    except UnicodeError as exc:
        raise StoryError(f"文本编码无效：{path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise StoryError(f"JSON 无效：{path}: {exc}") from exc


def load_json(path: Path) -> dict:
    value = read_json_value(path)
    if not isinstance(value, dict):
        raise StoryError(f"JSON 顶层必须是 object：{path}")
    return value


def parse_int(value: object, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise StoryError(f"{label} 必须是整数") from exc


def parse_float(value: object, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise StoryError(f"{label} 必须是数字") from exc


def state_path(root: Path) -> Path:
    return root.resolve() / STATE_DIR


def require_project(root: Path) -> tuple[Path, dict]:
    root = root.resolve()
    manifest = load_json(state_path(root) / "manifest.json")
    if manifest.get("format") != "serial-fiction-studio/v1":
        raise StoryError("不支持的项目格式")
    return root, manifest


def portable_path(root: Path, target: Path) -> str:
    target = target.resolve()
    try:
        return target.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(target)


def resolve_manifest_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else root / candidate


def load_events(root: Path) -> list[dict]:
    ledger = state_path(root) / "ledger.jsonl"
    if not ledger.exists():
        return []
    events: list[dict] = []
    for line_no, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StoryError(f"账本第 {line_no} 行无效：{exc}") from exc
        events.append(item)
    return events


def append_event(root: Path, event: dict) -> dict:
    event = dict(event)
    event.setdefault("id", uuid.uuid4().hex[:12])
    event.setdefault("at", now_iso())
    event.setdefault("source", "manual")
    ledger = state_path(root) / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event


def reduce_events(events: Sequence[dict]) -> dict:
    facts: dict[str, dict] = {}
    setups: dict[str, dict] = {}
    timeline: list[dict] = []
    decisions: list[dict] = []
    chapters: list[dict] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    for event in events:
        event_id = str(event.get("id", ""))
        kind = event.get("kind")
        if not event_id or event_id in seen_ids:
            warnings.append(f"重复或缺失事件 id：{event_id or '<empty>'}")
        seen_ids.add(event_id)
        if kind == "fact":
            key = f"{event.get('subject', '')}\u241f{event.get('predicate', '')}"
            if event.get("value") == "__RETRACT__":
                facts.pop(key, None)
            else:
                facts[key] = event
        elif kind == "setup":
            setups[event_id] = {**event, "status": "open"}
        elif kind == "payoff":
            target = str(event.get("subject", ""))
            if target in setups:
                setups[target]["status"] = "paid"
                setups[target]["payoff"] = event
            else:
                warnings.append(f"回收事件 {event_id} 指向不存在的伏笔 {target}")
        elif kind == "timeline":
            timeline.append(event)
        elif kind == "decision":
            decisions.append(event)
        elif kind == "chapter":
            chapters.append(event)
        else:
            warnings.append(f"未知事件类型：{kind}")

    chapters.sort(key=lambda item: (int(item.get("chapter") or 0), item.get("at", "")))
    return {
        "format": "serial-fiction-snapshot/v1",
        "built_at": now_iso(),
        "event_count": len(events),
        "facts": list(facts.values()),
        "setups": list(setups.values()),
        "timeline": timeline,
        "decisions": decisions,
        "chapters": chapters,
        "warnings": warnings,
    }


def rebuild_snapshot(root: Path) -> dict:
    snapshot = reduce_events(load_events(root))
    write_json(state_path(root) / "snapshot.json", snapshot)
    return snapshot


def chunk_text(text: str, target: int = 900, overlap: int = 120) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target * 2:
            if current:
                chunks.append(current)
                current = ""
            step = max(1, target - overlap)
            chunks.extend(paragraph[i : i + target] for i in range(0, len(paragraph), step))
        elif current and len(current) + len(paragraph) + 2 > target:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (tail + "\n\n" + paragraph).strip()
        else:
            current = (current + "\n\n" + paragraph).strip()
    if current:
        chunks.append(current)
    return chunks


def search_terms(text: str) -> str:
    latin = re.findall(r"[A-Za-z0-9_]+", text.lower())
    han_runs = re.findall(r"[\u3400-\u9fff]+", text)
    han: list[str] = []
    for run in han_runs:
        if len(run) == 1:
            han.append(run)
        else:
            han.extend(run[i : i + 2] for i in range(len(run) - 1))
    return " ".join(latin + han)


def query_expression(text: str) -> str:
    tokens = list(dict.fromkeys(search_terms(text).split()))
    if not tokens:
        return '"__no_match__"'
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens[:48])


def iter_source_files(paths: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for item in paths:
        item = item.resolve()
        candidates = [item] if item.is_file() else item.rglob("*") if item.exists() else []
        for path in candidates:
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and STATE_DIR not in path.parts:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield resolved


def ollama_embeddings(endpoint: str, model: str, texts: Sequence[str]) -> list[list[float]]:
    url = endpoint.rstrip("/") + "/api/embed"
    payload = json.dumps({"model": model, "input": list(texts)}).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise StoryError(f"Ollama embedding 请求失败：{exc}") from exc
    vectors = body.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise StoryError("Ollama 返回的 embeddings 数量不正确")
    return vectors


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    left = math.sqrt(sum(x * x for x in a))
    right = math.sqrt(sum(y * y for y in b))
    return dot / (left * right) if left and right else 0.0


def db_path(root: Path) -> Path:
    return state_path(root) / "library.sqlite3"


def connect_db(root: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path(root))
    connection.row_factory = sqlite3.Row
    return connection


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)).fetchone() is not None


def supports_fts5(con: sqlite3.Connection) -> bool:
    try:
        con.execute("CREATE VIRTUAL TABLE temp.__storywork_fts5_probe USING fts5(value)")
        con.execute("DROP TABLE temp.__storywork_fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def initialize_index_schema(con: sqlite3.Connection, force_lexical_scan: bool = False) -> str:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS docs(
            id INTEGER PRIMARY KEY,
            file_key TEXT NOT NULL,
            source TEXT NOT NULL,
            path TEXT NOT NULL,
            title TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            vector TEXT
        );
        CREATE TABLE IF NOT EXISTS source_files(
            file_key TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            sha256 TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    lexical_backend = "scan"
    if not force_lexical_scan and supports_fts5(con):
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(doc_id UNINDEXED, title, terms, tokenize='unicode61')")
        lexical_backend = "fts5"
    else:
        con.execute("CREATE TABLE IF NOT EXISTS docs_lexical(doc_id INTEGER PRIMARY KEY, title TEXT NOT NULL, terms TEXT NOT NULL)")
    lexical_table = "docs_fts" if lexical_backend == "fts5" else "docs_lexical"
    indexed_ids = {int(row[0]) for row in con.execute(f"SELECT doc_id FROM {lexical_table}")}
    for row in con.execute("SELECT id,title,text FROM docs"):
        doc_id = int(row["id"])
        if doc_id in indexed_ids:
            continue
        if lexical_backend == "fts5":
            con.execute("INSERT INTO docs_fts(rowid,doc_id,title,terms) VALUES(?,?,?,?)", (doc_id, doc_id, row["title"], search_terms(row["text"])))
        else:
            con.execute("INSERT INTO docs_lexical(doc_id,title,terms) VALUES(?,?,?)", (doc_id, row["title"], search_terms(row["text"])))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema','2')")
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('lexical_backend',?)", (lexical_backend,))
    return lexical_backend


def insert_lexical_row(con: sqlite3.Connection, lexical_backend: str, doc_id: int, title: str, text: str) -> None:
    terms = search_terms(text)
    if lexical_backend == "fts5":
        con.execute("INSERT INTO docs_fts(rowid,doc_id,title,terms) VALUES(?,?,?,?)", (doc_id, doc_id, title, terms))
    else:
        con.execute("INSERT INTO docs_lexical(doc_id,title,terms) VALUES(?,?,?)", (doc_id, title, terms))


def delete_index_file(con: sqlite3.Connection, file_key: str) -> None:
    ids = [int(row[0]) for row in con.execute("SELECT id FROM docs WHERE file_key=?", (file_key,))]
    if ids:
        if table_exists(con, "docs_fts"):
            try:
                con.executemany("DELETE FROM docs_fts WHERE rowid=?", [(doc_id,) for doc_id in ids])
            except sqlite3.OperationalError:
                # A database created with FTS5 may later be opened by a Python
                # build without the module. The scan table remains usable.
                pass
        if table_exists(con, "docs_lexical"):
            con.executemany("DELETE FROM docs_lexical WHERE doc_id=?", [(doc_id,) for doc_id in ids])
    con.execute("DELETE FROM docs WHERE file_key=?", (file_key,))
    con.execute("DELETE FROM source_files WHERE file_key=?", (file_key,))


def build_hnsw(root: Path, con: sqlite3.Connection, requested: str) -> str:
    index_path = state_path(root) / "library.hnsw.bin"
    if requested == "exact":
        return "exact"
    try:
        import hnswlib  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        if requested == "hnsw":
            raise StoryError("HNSW 后端需要可选依赖 hnswlib 与 numpy") from exc
        return "exact"
    rows = con.execute("SELECT id,vector FROM docs WHERE vector IS NOT NULL ORDER BY id").fetchall()
    if not rows:
        return "exact"
    vectors = np.asarray([json.loads(row["vector"]) for row in rows], dtype=np.float32)
    labels = np.asarray([int(row["id"]) for row in rows], dtype=np.int64)
    index = hnswlib.Index(space="cosine", dim=int(vectors.shape[1]))
    index.init_index(max_elements=len(rows), ef_construction=200, M=16)
    index.add_items(vectors, labels)
    index.set_ef(min(max(50, len(rows) // 20), 300))
    temporary = index_path.with_suffix(".tmp")
    index.save_index(str(temporary))
    os.replace(temporary, index_path)
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('vector_dim',?)", (str(vectors.shape[1]),))
    return "hnsw"


def build_index(root: Path, source_args: Sequence[str], embeddings: str, model: str, endpoint: str, ann: str = "auto") -> dict:
    root, manifest = require_project(root)
    chapters = resolve_manifest_path(root, manifest["chapters"])
    reference_sources = [resolve_manifest_path(root, value).resolve() for value in source_args]
    missing_sources = [str(path) for path in reference_sources if not path.exists()]
    if missing_sources:
        raise StoryError(f"索引参考源不存在；保留现有索引不变：{missing_sources}")
    sources = [chapters] + reference_sources
    database = db_path(root)
    database.parent.mkdir(parents=True, exist_ok=True)
    con = connect_db(root)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables and "source_files" not in tables:
        con.close()
        database.unlink()
        con = connect_db(root)
    lexical_backend = initialize_index_schema(con)
    previous_meta = {row["key"]: row["value"] for row in con.execute("SELECT key,value FROM meta")}
    con.commit()
    pending: list[tuple[int, str]] = []
    discovered: dict[str, tuple[Path, str, str, str]] = {}
    for file_path in iter_source_files(sources):
        display_path = portable_path(root, file_path)
        source_type = "manuscript" if chapters in file_path.parents else "reference"
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        discovered[display_path] = (file_path, source_type, file_path.stem, digest)

    ledger_path = state_path(root) / "ledger.jsonl"
    ledger_digest = hashlib.sha256(ledger_path.read_bytes()).hexdigest() if ledger_path.exists() else hashlib.sha256(b"").hexdigest()
    current = {row["file_key"]: row["sha256"] for row in con.execute("SELECT file_key,sha256 FROM source_files")}
    desired_keys = set(discovered) | {"@ledger"}
    changed_keys = {key for key, value in discovered.items() if current.get(key) != value[3]}
    if current.get("@ledger") != ledger_digest:
        changed_keys.add("@ledger")
    removed_keys = set(current) - desired_keys
    con.execute("BEGIN IMMEDIATE")
    for file_key in removed_keys | changed_keys:
        delete_index_file(con, file_key)
    for file_key in sorted(changed_keys - {"@ledger"}):
        file_path, source_type, title, digest = discovered[file_key]
        for ordinal, chunk in enumerate(chunk_text(read_text(file_path))):
            cursor = con.execute("INSERT INTO docs(file_key,source,path,title,ordinal,text,vector) VALUES(?,?,?,?,?,?,NULL)", (file_key, source_type, file_key, title, ordinal, chunk))
            doc_id = int(cursor.lastrowid)
            insert_lexical_row(con, lexical_backend, doc_id, title, chunk)
            if embeddings == "ollama":
                pending.append((doc_id, chunk))
        con.execute("INSERT INTO source_files(file_key,path,source,title,sha256) VALUES(?,?,?,?,?)", (file_key, file_key, source_type, title, digest))

    if "@ledger" in changed_keys:
        ordinal = 0
        for event in load_events(root):
            if event.get("kind") not in {"fact", "setup", "timeline", "decision"}:
                continue
            text = " | ".join(str(event.get(key, "")) for key in ("kind", "subject", "predicate", "value", "evidence"))
            cursor = con.execute("INSERT INTO docs(file_key,source,path,title,ordinal,text,vector) VALUES(?,?,?,?,?,?,NULL)", ("@ledger", "ledger", "ledger.jsonl", str(event.get("kind")), ordinal, text))
            doc_id = int(cursor.lastrowid)
            insert_lexical_row(con, lexical_backend, doc_id, str(event.get("kind")), text)
            if embeddings == "ollama":
                pending.append((doc_id, text))
            ordinal += 1
        con.execute("INSERT INTO source_files(file_key,path,source,title,sha256) VALUES(?,?,?,?,?)", ("@ledger", "ledger.jsonl", "ledger", "ledger", ledger_digest))

    embedding_changed = previous_meta.get("embeddings") != embeddings or previous_meta.get("model") != (model if embeddings == "ollama" else "") or previous_meta.get("endpoint") != (endpoint if embeddings == "ollama" else "")
    if embeddings == "none":
        con.execute("UPDATE docs SET vector=NULL WHERE vector IS NOT NULL")
        pending = []
    elif embedding_changed:
        con.execute("UPDATE docs SET vector=NULL")
        pending = [(int(row["id"]), str(row["text"])) for row in con.execute("SELECT id,text FROM docs")]

    if embeddings == "ollama":
        for start in range(0, len(pending), 16):
            batch = pending[start : start + 16]
            vectors = ollama_embeddings(endpoint, model, [text for _, text in batch])
            con.executemany("UPDATE docs SET vector=? WHERE id=?", [(json.dumps(vector), doc_id) for (doc_id, _), vector in zip(batch, vectors)])

    meta = {"built_at": now_iso(), "embeddings": embeddings, "model": model if embeddings == "ollama" else "", "endpoint": endpoint if embeddings == "ollama" else ""}
    con.executemany("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", meta.items())
    con.commit()
    try:
        ann_backend = build_hnsw(root, con, ann) if embeddings == "ollama" else "exact"
    except BaseException:
        con.close()
        raise
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('ann',?)", (ann_backend,))
    con.commit()
    doc_count = int(con.execute("SELECT COUNT(*) FROM docs").fetchone()[0])
    con.close()
    return {"files": len(discovered), "chunks": doc_count, "changed_files": len(changed_keys), "removed_files": len(removed_keys), "embedded_chunks": len(pending), "lexical_backend": lexical_backend, "ann": ann_backend, **meta}


def command_index(args: argparse.Namespace) -> dict:
    root, manifest = require_project(Path(args.root))
    previous = manifest.get("retrieval", {})
    if args.source is not None:
        sources = [portable_path(root, Path(value).resolve()) for value in args.source]
    else:
        sources = list(manifest.get("index_sources", []))
    embeddings = args.embeddings or previous.get("embeddings", "none")
    model = args.model or previous.get("model", "bge-m3")
    endpoint = args.endpoint or previous.get("endpoint", "http://127.0.0.1:11434")
    ann = args.ann or previous.get("ann", "auto")
    result = build_index(root, sources, embeddings, model, endpoint, ann)
    manifest["index_sources"] = list(sources)
    manifest["retrieval"] = {"embeddings": embeddings, "model": model, "endpoint": endpoint, "ann": ann}
    write_json(state_path(root) / "manifest.json", manifest)
    return result


def search_index_report(root: Path, query: str, limit: int, lexical_weight: float, semantic_weight: float) -> dict:
    root, _ = require_project(root)
    if lexical_weight < 0 or semantic_weight < 0 or lexical_weight + semantic_weight <= 0:
        raise StoryError("检索权重必须为非负数，且总和必须大于 0")
    requested_weights = {"lexical": lexical_weight, "semantic": semantic_weight}
    if not db_path(root).exists():
        return {
            "mode": "unindexed",
            "lexical_backend": None,
            "requested_weights": requested_weights,
            "effective_weights": {"lexical": 0.0, "semantic": 0.0},
            "warnings": ["检索索引尚未建立；请先运行 index"],
            "hits": [],
        }
    con = connect_db(root)
    meta = {row["key"]: row["value"] for row in con.execute("SELECT key,value FROM meta")}
    warnings: list[str] = []
    claimed_backend = meta.get("lexical_backend") or ("fts5" if table_exists(con, "docs_fts") else "scan")
    has_fts = table_exists(con, "docs_fts")
    has_scan = table_exists(con, "docs_lexical")
    if claimed_backend == "fts5" and has_fts:
        lexical_backend = "fts5"
    elif claimed_backend == "scan" and has_scan:
        lexical_backend = "scan"
    elif has_scan:
        lexical_backend = "scan"
        warnings.append(f"索引元数据声明 {claimed_backend}，但对应词法表不存在；已降级到扫描检索，请运行 index 重建索引")
    elif has_fts:
        lexical_backend = "fts5"
        warnings.append(f"索引元数据声明 {claimed_backend}，但对应词法表不存在；已改用现存 FTS5 表，请运行 index 修复元数据")
    else:
        lexical_backend = "unavailable"
        warnings.append(f"索引元数据声明 {claimed_backend}，但词法索引表不存在；词法检索不可用，请运行 index 重建索引")
    lexical_available = lexical_backend in {"fts5", "scan"}
    candidates: dict[int, dict] = {}
    candidate_limit = max(limit * 6, 30)
    if lexical_backend == "fts5":
        rows = con.execute(
            "SELECT d.*, bm25(docs_fts) AS rank FROM docs_fts JOIN docs d ON d.id=docs_fts.doc_id WHERE docs_fts MATCH ? ORDER BY rank LIMIT ?",
            (query_expression(query), candidate_limit),
        ).fetchall()
    else:
        query_tokens = set(search_terms(query).split())
        scored_rows: list[tuple[float, sqlite3.Row]] = []
        lexical_table = "docs_lexical" if lexical_backend == "scan" else None
        if lexical_table:
            for row in con.execute("SELECT d.*,l.terms FROM docs_lexical l JOIN docs d ON d.id=l.doc_id"):
                terms = set(str(row["terms"]).split())
                overlap = len(query_tokens & terms)
                if overlap:
                    scored_rows.append((overlap / max(len(query_tokens), 1), row))
        rows = [row for _, row in sorted(scored_rows, key=lambda pair: pair[0], reverse=True)[:candidate_limit]]
    for position, row in enumerate(rows):
        item = dict(row)
        item.pop("terms", None)
        item["lexical"] = 1.0 / (position + 1)
        item["semantic"] = 0.0
        candidates[int(row["id"])] = item

    effective_lexical = lexical_weight if lexical_available else 0.0
    effective_semantic = semantic_weight
    semantic_active = False
    vector_count = int(con.execute("SELECT COUNT(*) FROM docs WHERE vector IS NOT NULL").fetchone()[0])
    if semantic_weight > 0 and meta.get("embeddings") == "ollama" and vector_count > 0:
        try:
            vector = ollama_embeddings(meta["endpoint"], meta["model"], [query])[0]
            semantic_active = True
        except StoryError as exc:
            warnings.append(f"语义查询不可用，已将语义权重转交词法检索：{exc}")
    elif semantic_weight > 0:
        transfer = "已将语义权重转交词法检索" if lexical_available else "且当前词法索引也不可用"
        warnings.append(f"索引没有可用 embedding，{transfer}；如需语义召回，请使用 index --embeddings ollama 重建索引")

    if semantic_weight > 0 and not semantic_active:
        if lexical_available:
            effective_lexical += effective_semantic
        else:
            warnings.append("语义与词法检索均不可用；本次查询无法返回索引命中")
        effective_semantic = 0.0

    if not lexical_available and semantic_active and effective_lexical > 0:
        effective_semantic += effective_lexical
        effective_lexical = 0.0
        warnings.append("词法索引不可用，已将词法权重转交语义检索")

    if semantic_active:
        semantic_rows: list[tuple[sqlite3.Row, float]] = []
        if meta.get("ann") == "hnsw" and (state_path(root) / "library.hnsw.bin").exists():
            try:
                import hnswlib  # type: ignore
                import numpy as np  # type: ignore
                count = int(con.execute("SELECT COUNT(*) FROM docs WHERE vector IS NOT NULL").fetchone()[0])
                index = hnswlib.Index(space="cosine", dim=int(meta["vector_dim"]))
                index.load_index(str(state_path(root) / "library.hnsw.bin"), max_elements=count)
                index.set_ef(min(max(limit * 8, 50), max(count, 1)))
                labels, distances = index.knn_query(np.asarray([vector], dtype=np.float32), k=min(max(limit * 6, 30), count))
                scores = {int(label): max(0.0, 1.0 - float(distance)) for label, distance in zip(labels[0], distances[0])}
                placeholders = ",".join("?" for _ in scores)
                if placeholders:
                    semantic_rows = [(row, scores[int(row["id"])]) for row in con.execute(f"SELECT * FROM docs WHERE id IN ({placeholders})", tuple(scores))]
            except (ImportError, RuntimeError, ValueError):
                semantic_rows = []
        if not semantic_rows:
            semantic_rows = [(row, max(0.0, cosine(vector, json.loads(row["vector"])))) for row in con.execute("SELECT * FROM docs WHERE vector IS NOT NULL")]
        for row, score in semantic_rows:
            item = candidates.setdefault(int(row["id"]), {**dict(row), "lexical": 0.0, "semantic": 0.0})
            item["semantic"] = score

    for item in candidates.values():
        item["score"] = effective_lexical * item["lexical"] + effective_semantic * item["semantic"]
        item.pop("vector", None)
        item.pop("rank", None)
    con.close()
    if semantic_active and effective_lexical > 0:
        mode = "hybrid"
    elif semantic_active:
        mode = "vector"
    else:
        mode = {"fts5": "fts5", "scan": "lexical-scan", "unavailable": "index-unavailable"}[lexical_backend]
    return {
        "mode": mode,
        "lexical_backend": lexical_backend,
        "requested_weights": requested_weights,
        "effective_weights": {"lexical": effective_lexical, "semantic": effective_semantic},
        "warnings": warnings,
        "hits": sorted(candidates.values(), key=lambda item: item["score"], reverse=True)[:limit],
    }


def search_index(root: Path, query: str, limit: int, lexical_weight: float, semantic_weight: float) -> list[dict]:
    """Compatibility API for callers that only need passages."""
    return search_index_report(root, query, limit, lexical_weight, semantic_weight)["hits"]


def command_query(args: argparse.Namespace) -> dict:
    return search_index_report(Path(args.root), args.query, args.limit, args.lexical_weight, args.semantic_weight)


def natural_key(path: Path) -> tuple:
    parts = re.split(r"(\d+)", path.name)
    return tuple(int(part) if part.isdigit() else part.lower() for part in parts)


def recent_chapters(root: Path, manifest: dict, count: int = 2, chars: int = 5000) -> list[tuple[str, str]]:
    chapter_dir = resolve_manifest_path(root, manifest["chapters"])
    files = sorted(iter_source_files([chapter_dir]), key=natural_key)
    return [(path.name, read_text(path)[-chars:]) for path in files[-count:]]


def snapshot_markdown(snapshot: dict) -> str:
    lines = ["## 已确认事实"]
    for item in snapshot.get("facts", []):
        lines.append(f"- {item.get('subject')} / {item.get('predicate')}: {item.get('value')}（第{item.get('chapter', '?')}章）")
    lines.append("\n## 未回收伏笔")
    for item in snapshot.get("setups", []):
        if item.get("status") == "open":
            lines.append(f"- [{item.get('id')}] {item.get('subject')} / {item.get('predicate')}: {item.get('value')}")
    lines.append("\n## 创作决定")
    for item in snapshot.get("decisions", []):
        lines.append(f"- {item.get('predicate')}: {item.get('value')}")
    return "\n".join(lines)


def compact_snapshot_markdown(snapshot: dict, max_chars: int = 24000) -> tuple[str, dict]:
    """Render a bounded working-memory view without changing the full snapshot on disk."""
    facts = sorted(snapshot.get("facts", []), key=lambda item: (int(item.get("chapter") or 0), float(item.get("order") or 0)), reverse=True)
    setups = sorted((item for item in snapshot.get("setups", []) if item.get("status") == "open"), key=lambda item: (int(item.get("chapter") or 0), float(item.get("order") or 0)), reverse=True)
    decisions = sorted(snapshot.get("decisions", []), key=lambda item: (int(item.get("chapter") or 0), float(item.get("order") or 0)), reverse=True)
    specs = [
        ("facts", "## 已确认事实", facts, 240, 0.48, lambda item: f"- {item.get('subject')} / {item.get('predicate')}: {item.get('value')}（第{item.get('chapter', '?')}章）"),
        ("setups", "## 未回收伏笔", setups, 160, 0.28, lambda item: f"- [{item.get('id')}] {item.get('subject')} / {item.get('predicate')}: {item.get('value')}"),
        ("decisions", "## 创作决定", decisions, 80, 0.16, lambda item: f"- {item.get('predicate')}: {item.get('value')}"),
    ]
    sections: list[str] = []
    report = {"max_characters": max_chars, "generated_characters": 0, "values_truncated": 0, "sections": {}}
    for key, heading, items, item_limit, ratio, formatter in specs:
        budget = max(200, int(max_chars * ratio))
        lines = [heading]
        included = 0
        for item in items[:item_limit]:
            raw_line = formatter(item)
            line = raw_line if len(raw_line) <= 500 else raw_line[:497] + "…"
            if line != raw_line:
                report["values_truncated"] += 1
            if len("\n".join(lines + [line])) > budget:
                break
            lines.append(line)
            included += 1
        report["sections"][key] = {"total": len(items), "included": included, "omitted": len(items) - included}
        sections.append("\n".join(lines))
    omitted = sum(item["omitted"] for item in report["sections"].values())
    if omitted or report["values_truncated"]:
        details = "；".join(f"{key} 省略 {item['omitted']} 条" for key, item in report["sections"].items() if item["omitted"])
        sections.append("## 上下文压缩说明\n- 本上下文只载入工作集，完整数据仍在 `.storywork/snapshot.json`。"
                        + (f"\n- {details}。需要时请定向查询或执行全量审计。" if details else "")
                        + (f"\n- {report['values_truncated']} 条超长值仅在本上下文中截短显示。" if report["values_truncated"] else ""))
    rendered = "\n\n".join(sections)
    report["generated_characters"] = len(rendered)
    return rendered, report


def command_init(args: argparse.Namespace) -> dict:
    root = Path(args.root).resolve()
    meta = state_path(root)
    if (meta / "manifest.json").exists():
        raise StoryError("项目已经初始化")
    chapters = Path(args.chapters)
    if not chapters.is_absolute():
        chapters = root / chapters
    chapters.mkdir(parents=True, exist_ok=True)
    (meta / "sessions").mkdir(parents=True, exist_ok=True)
    manifest = {"format": "serial-fiction-studio/v1", "title": args.title, "created_at": now_iso(), "chapters": portable_path(root, chapters), "chapter_filename": "第{chapter:04d}章.md"}
    write_json(meta / "manifest.json", manifest)
    (meta / "ledger.jsonl").write_text("", encoding="utf-8")
    rebuild_snapshot(root)
    return {"project": str(root), "manifest": manifest}


def command_record(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    if args.kind not in EVENT_KINDS - {"chapter"}:
        raise StoryError("record 不接受该事件类型")
    value_file = getattr(args, "value_file", None)
    value = read_text(Path(value_file)).rstrip("\r\n") if value_file else args.value
    event = append_event(root, {"kind": args.kind, "subject": args.subject, "predicate": args.predicate, "value": value, "chapter": args.chapter, "order": getattr(args, "order", None), "entity_type": getattr(args, "entity_type", None), "source": args.source})
    rebuild_snapshot(root)
    return event


def chapter_number(path: Path, text: str) -> int | None:
    for candidate in (path.stem, text[:200]):
        match = re.search(r"第\s*(\d+)\s*章", candidate)
        if match:
            return int(match.group(1))
    return None


def accepted_chapter_records(root: Path, chapter: int) -> list[dict]:
    return [
        event
        for event in load_events(root)
        if event.get("kind") == "chapter" and int(event.get("chapter") or 0) == chapter
    ]


def require_chapter_number_available(root: Path, chapter: int) -> None:
    existing = accepted_chapter_records(root, chapter)
    if existing:
        names = [str(event.get("subject", "")) for event in existing]
        raise StoryError(f"第 {chapter} 章已有接受记录：{names}；请先使用明确的修订/迁移流程，不能创建第二份 canon")


def command_adopt(args: argparse.Namespace) -> dict:
    root, manifest = require_project(Path(args.root))
    chapter_dir = resolve_manifest_path(root, manifest["chapters"])
    existing_by_number = {
        int(event.get("chapter") or 0): str(event.get("subject", ""))
        for event in load_events(root)
        if event.get("kind") == "chapter" and int(event.get("chapter") or 0) > 0
    }
    planned: list[dict] = []
    skipped: list[dict] = []
    seen_numbers: dict[int, str] = {}
    for path in sorted(iter_source_files([chapter_dir]), key=natural_key):
        text = read_text(path)
        number = chapter_number(path, text)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if number is None:
            skipped.append({"path": str(path), "reason": "无法识别章节号"})
            continue
        if number in seen_numbers:
            skipped.append({"path": str(path), "reason": f"章节号与 {seen_numbers[number]} 重复"})
            continue
        seen_numbers[number] = path.name
        if number in existing_by_number:
            skipped.append({"path": str(path), "reason": f"第 {number} 章已有接受记录：{existing_by_number[number]}"})
            continue
        planned.append({"chapter": number, "path": str(path), "name": path.name, "sha256": digest})

    applied = 0
    if args.apply:
        if args.confirm != "ADOPT":
            raise StoryError("写入收编记录需要 --confirm ADOPT")
        for item in planned:
            append_event(root, {"kind": "chapter", "subject": item["name"], "predicate": "adopted", "value": item["sha256"], "chapter": item["chapter"], "source": "existing-manuscript"})
            applied += 1
        rebuild_snapshot(root)
    return {"mode": "apply" if args.apply else "preview", "planned": planned, "skipped": skipped, "applied": applied}


def validate_proposed_event(item: dict, chapter: int) -> dict:
    if not isinstance(item, dict):
        raise StoryError("每条提取结果必须是 JSON object")
    kind = item.get("kind")
    if kind not in EVENT_KINDS - {"chapter"}:
        raise StoryError(f"提取结果包含不支持的 kind：{kind}")
    for field in ("subject", "predicate", "value", "evidence"):
        if not str(item.get(field, "")).strip():
            raise StoryError(f"提取结果缺少 {field}")
    evidence = str(item["evidence"]).strip()
    if len(evidence) > 300:
        raise StoryError("单条 evidence 不得超过 300 字符")
    normalized = {
        "id": str(item.get("id") or uuid.uuid4().hex[:12]),
        "kind": kind,
        "subject": str(item["subject"]).strip(),
        "predicate": str(item["predicate"]).strip(),
        "value": item["value"],
        "chapter": parse_int(item.get("chapter") or chapter, "事件 chapter"),
        "order": item.get("order"),
        "entity_type": item.get("entity_type"),
        "confidence": parse_float(item.get("confidence", 0.8), "事件 confidence"),
        "risk": str(item.get("risk", "normal")),
        "evidence": evidence,
        "source": str(item.get("source", "chapter-extraction")),
    }
    if normalized["chapter"] != chapter:
        raise StoryError("提取事件的 chapter 必须与会话章节一致")
    if not 0 <= normalized["confidence"] <= 1:
        raise StoryError("confidence 必须介于 0 与 1")
    return normalized


def normalize_evidence_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def accepted_session_manuscript(root: Path, session: dict) -> tuple[Path, str, str]:
    destination_value = str(session.get("destination", "")).strip()
    if not destination_value:
        raise StoryError("已接受会话缺少正文路径，不能校验证据")
    destination = resolve_manifest_path(root, destination_value).resolve()
    if not destination.exists():
        raise StoryError(f"已接受正文不存在，不能校验证据：{destination}")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    expected = str(session.get("review", {}).get("sha256", ""))
    if expected and digest != expected:
        raise StoryError("已接受正文在审稿后发生变化，不能暂存或批准事实")
    return destination, read_text(destination), digest


def require_evidence_in_chapter(event: dict, chapter_text: str) -> None:
    evidence = normalize_evidence_text(str(event.get("evidence", "")))
    if not evidence or evidence not in normalize_evidence_text(chapter_text):
        raise StoryError(f"事件 {event.get('id')} 的 evidence 不是已接受正文中的连续短引文")


def command_stage_events(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    session_dir = state_path(root) / "sessions" / args.session
    session = load_json(session_dir / "session.json")
    if session.get("status") != "accepted":
        raise StoryError("只有已接受章节才能暂存事实提取结果")
    _, chapter_text, chapter_digest = accepted_session_manuscript(root, session)
    raw = read_json_value(Path(args.events))
    if not isinstance(raw, list):
        raise StoryError("事件文件顶层必须是数组")
    events = [validate_proposed_event(item, int(session["chapter"])) for item in raw]
    for event in events:
        require_evidence_in_chapter(event, chapter_text)
    proposal = {
        "format": "serial-fiction-event-proposal/v1",
        "session": args.session,
        "status": "pending",
        "created_at": now_iso(),
        "chapter": int(session["chapter"]),
        "chapter_sha256": chapter_digest,
        "events": events,
    }
    write_json(session_dir / "event-proposal.json", proposal)
    return {"session": args.session, "status": "pending", "events": len(events), "high_risk": sum(item["risk"] == "high" for item in events)}


def command_approve_events(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    proposal_path = state_path(root) / "sessions" / args.session / "event-proposal.json"
    proposal = load_json(proposal_path)
    if args.confirm != args.session:
        raise StoryError("确认值必须与 session id 完全一致")
    if proposal.get("status") == "approved":
        return {"session": args.session, "status": "already-approved", "applied": 0}
    if proposal.get("session") != args.session:
        raise StoryError("事实提案绑定的 session 不一致")
    session = load_json(state_path(root) / "sessions" / args.session / "session.json")
    if session.get("status") != "accepted":
        raise StoryError("只有已接受章节的事实提案可以批准")
    _, chapter_text, chapter_digest = accepted_session_manuscript(root, session)
    if proposal.get("chapter_sha256") != chapter_digest:
        raise StoryError("事实提案绑定的正文摘要已过期，请重新 stage-events")
    validated_events = [validate_proposed_event(item, int(session["chapter"])) for item in proposal.get("events", [])]
    for event in validated_events:
        require_evidence_in_chapter(event, chapter_text)
    existing_ids = {str(event.get("id")) for event in load_events(root)}
    applied = 0
    for event in validated_events:
        if str(event.get("id")) not in existing_ids:
            append_event(root, event)
            existing_ids.add(str(event.get("id")))
            applied += 1
    proposal["status"] = "approved"
    proposal["approved_at"] = now_iso()
    write_json(proposal_path, proposal)
    rebuild_snapshot(root)
    return {"session": args.session, "status": "approved", "applied": applied}


def plan_path(root: Path, chapter: int) -> Path:
    return state_path(root) / "plans" / f"chapter-{chapter:06d}.json"


def outcome_path(root: Path, chapter: int) -> Path:
    return state_path(root) / "outcomes" / f"chapter-{chapter:06d}.json"


def validate_plan(raw: dict, chapter: int) -> dict:
    if not isinstance(raw, dict):
        raise StoryError("计划必须是 object，且 chapter 与命令参数一致")
    if parse_int(raw.get("chapter") or 0, "计划 chapter") != chapter:
        raise StoryError("计划必须是 object，且 chapter 与命令参数一致")
    if not str(raw.get("goal", "")).strip():
        raise StoryError("计划缺少 goal")
    scenes = raw.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise StoryError("计划至少需要一个场景")
    scene_ids: set[str] = set()
    normalized_scenes: list[dict] = []
    for item in scenes:
        if not isinstance(item, dict):
            raise StoryError("每个计划场景必须是 object")
        scene_id = str(item.get("id", "")).strip()
        function = str(item.get("function", "")).strip()
        if not scene_id or scene_id in scene_ids:
            raise StoryError(f"场景 id 缺失或重复：{scene_id}")
        if function not in SCENE_FUNCTIONS:
            raise StoryError(f"未知场景功能：{function}")
        for field in ("purpose", "pov", "location", "objective", "obstacle", "turn", "consequence"):
            if not str(item.get(field, "")).strip():
                raise StoryError(f"场景 {scene_id} 缺少 {field}")
        tension = parse_int(item.get("tension") or 0, f"场景 {scene_id} tension")
        information = parse_int(item.get("information_gain") or 0, f"场景 {scene_id} information_gain")
        if tension not in range(1, 6) or information not in range(0, 4):
            raise StoryError(f"场景 {scene_id} 的 tension 或 information_gain 超出范围")
        scene_ids.add(scene_id)
        normalized_scenes.append({**item, "id": scene_id, "function": function, "tension": tension, "information_gain": information, "irreversible": bool(item.get("irreversible", False)), "setup_actions": item.get("setup_actions", [])})
    commitments = raw.get("commitments", [])
    commitment_ids: set[str] = set()
    normalized_commitments: list[dict] = []
    for item in commitments:
        if not isinstance(item, dict):
            raise StoryError("每个 commitment 必须是 object")
        commitment_id = str(item.get("id", "")).strip()
        priority = str(item.get("priority", "should"))
        if not commitment_id or commitment_id in commitment_ids or priority not in {"must", "should"} or not str(item.get("description", "")).strip():
            raise StoryError("commitment 必须有唯一 id、description 和 must/should priority")
        commitment_ids.add(commitment_id)
        normalized_commitments.append({"id": commitment_id, "description": str(item["description"]), "priority": priority})
    normalized_constraints: list[dict] = []
    constraint_ids: set[str] = set()
    for index, item in enumerate(raw.get("constraints", []), 1):
        if isinstance(item, str):
            item = {"id": f"constraint-{index}", "description": item, "level": "hard"}
        if not isinstance(item, dict):
            raise StoryError("每个 constraint 必须是字符串或 object")
        constraint_id = str(item.get("id", "")).strip()
        level = str(item.get("level", "hard"))
        if not constraint_id or constraint_id in constraint_ids or level not in {"hard", "soft"} or not str(item.get("description", "")).strip():
            raise StoryError("constraint 必须有唯一 id、description 和 hard/soft level")
        constraint_ids.add(constraint_id)
        normalized_constraints.append({"id": constraint_id, "description": str(item["description"]), "level": level, "forbidden_phrase": item.get("forbidden_phrase")})
    pacing = raw.get("pacing", {})
    target = parse_int(pacing.get("target_characters") or 0, "target_characters")
    if target < 0:
        raise StoryError("target_characters 不能为负数")
    climax = pacing.get("climax_scene")
    if climax and str(climax) not in scene_ids:
        raise StoryError("climax_scene 必须引用已有场景")
    return {"chapter": chapter, "title": str(raw.get("title", "")), "goal": str(raw["goal"]).strip(), "pov": raw.get("pov"), "arc_ids": raw.get("arc_ids", []), "constraints": normalized_constraints, "commitments": normalized_commitments, "scenes": normalized_scenes, "pacing": {**pacing, "target_characters": target}}


def command_plan_set(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    if args.confirm != f"PLAN-{args.chapter}":
        raise StoryError(f"确认值必须是 PLAN-{args.chapter}")
    raw = read_json_value(Path(args.plan))
    normalized = validate_plan(raw, args.chapter)
    path = plan_path(root, args.chapter)
    history = load_json(path) if path.exists() else {"format": "serial-fiction-plan-history/v1", "chapter": args.chapter, "versions": []}
    current = next((item for item in reversed(history["versions"]) if item.get("status") == "active"), None)
    if current and plan_content_digest(current) == plan_content_digest(normalized):
        return {"chapter": args.chapter, "version": current["version"], "status": "already-active", "scenes": len(current["scenes"]), "commitments": len(current["commitments"])}
    version = len(history["versions"]) + 1
    entry = {**normalized, "version": version, "status": "active", "approved_at": now_iso()}
    for item in history["versions"]:
        if item.get("status") == "active":
            item["status"] = "superseded"
    history["versions"].append(entry)
    write_json(path, history)
    return {"chapter": args.chapter, "version": version, "scenes": len(entry["scenes"]), "commitments": len(entry["commitments"])}


def active_plan(root: Path, chapter: int) -> dict | None:
    path = plan_path(root, chapter)
    if not path.exists():
        return None
    history = load_json(path)
    return next((item for item in reversed(history.get("versions", [])) if item.get("status") == "active"), None)


def plan_version(root: Path, chapter: int, version: int | None) -> dict | None:
    if version is None:
        return active_plan(root, chapter)
    path = plan_path(root, chapter)
    if not path.exists():
        return None
    return next((item for item in load_json(path).get("versions", []) if int(item.get("version") or 0) == version), None)


def plan_markdown(plan: dict) -> str:
    lines = [f"## 已批准计划 v{plan['version']}", f"\n目标：{plan['goal']}"]
    if plan.get("constraints"):
        lines.append("\n### 约束")
        for item in plan["constraints"]:
            lines.append(f"- [{item['level']}] {item['id']}: {item['description']}")
    if plan.get("commitments"):
        lines.append("\n### 本章承诺")
        for item in plan["commitments"]:
            lines.append(f"- [{item['priority']}] {item['id']}: {item['description']}")
    lines.append("\n### 场景卡")
    for item in plan["scenes"]:
        setup_actions = ", ".join(f"{action.get('setup_id')}:{action.get('action')}" for action in item.get("setup_actions", [])) or "无"
        lines.append(f"- {item['id']} · {item['function']} · 用途={item['purpose']} · POV={item['pov']} · {item['location']} · 目标={item['objective']} · 阻力={item['obstacle']} · 转折={item['turn']} · 后果={item['consequence']} · 紧张度={item['tension']} · 信息增量={item['information_gain']} · 不可逆={item['irreversible']} · 伏笔={setup_actions}")
    pacing = plan.get("pacing", {})
    lines.append(f"\n### 节奏目标\n\n目标字符={pacing.get('target_characters', 0)} · 形状={pacing.get('shape', '未指定')} · 高点场景={pacing.get('climax_scene', '未指定')}")
    return "\n".join(lines)


def plan_payload_digest(plan: dict) -> str:
    payload = {key: value for key, value in plan.items() if key not in {"status", "approved_at"}}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def plan_content_digest(plan: dict) -> str:
    payload = {key: value for key, value in plan.items() if key not in {"version", "status", "approved_at"}}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def validate_outcome(raw: dict, chapter: int, plan: dict | None) -> dict:
    if not isinstance(raw, dict):
        raise StoryError("结果必须是 object，且 chapter 与会话一致")
    if parse_int(raw.get("chapter") or 0, "结果 chapter") != chapter:
        raise StoryError("结果必须是 object，且 chapter 与会话一致")
    scenes = raw.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise StoryError("结果至少需要一个实际场景")
    plan_ids = {item["id"] for item in plan.get("scenes", [])} if plan else set()
    commitment_ids = {item["id"] for item in plan.get("commitments", [])} if plan else set()
    constraint_ids = {item["id"] for item in plan.get("constraints", [])} if plan else set()
    fulfilled = list(map(str, raw.get("fulfilled_commitments", [])))
    violated = list(map(str, raw.get("violated_constraints", [])))
    if set(fulfilled) - commitment_ids:
        raise StoryError(f"fulfilled_commitments 引用未知 id：{sorted(set(fulfilled) - commitment_ids)}")
    if set(violated) - constraint_ids:
        raise StoryError(f"violated_constraints 引用未知 id：{sorted(set(violated) - constraint_ids)}")
    normalized: list[dict] = []
    for index, item in enumerate(scenes, 1):
        if not isinstance(item, dict):
            raise StoryError(f"实际场景 {index} 必须是 object")
        references = item.get("plan_scene_ids")
        if references is None:
            references = [item["plan_scene_id"]] if item.get("plan_scene_id") is not None else []
        references = list(map(str, references))
        unknown = set(references) - plan_ids
        if unknown:
            raise StoryError(f"实际场景引用未知计划场景：{sorted(unknown)}")
        function = str(item.get("function", ""))
        if function not in SCENE_FUNCTIONS:
            raise StoryError(f"未知实际场景功能：{function}")
        tension = parse_int(item.get("tension") or 0, f"实际场景 {index} tension")
        information = parse_int(item.get("information_gain") or 0, f"实际场景 {index} information_gain")
        if tension not in range(1, 6) or information not in range(0, 4):
            raise StoryError(f"实际场景 {index} 的节奏指标超出范围")
        if not str(item.get("summary", "")).strip():
            raise StoryError(f"实际场景 {index} 缺少 summary")
        evidence = str(item.get("evidence", ""))
        if len(evidence) > 300:
            raise StoryError("场景 evidence 不得超过 300 字符")
        normalized.append({**item, "plan_scene_ids": references, "plan_scene_id": references[0] if len(references) == 1 else None, "function": function, "tension": tension, "information_gain": information, "irreversible": bool(item.get("irreversible", False)), "setup_actions": item.get("setup_actions", []), "evidence": evidence})
    return {"chapter": chapter, "actual_characters": parse_int(raw.get("actual_characters") or 0, "actual_characters"), "fulfilled_commitments": fulfilled, "violated_constraints": violated, "unplanned_changes": list(raw.get("unplanned_changes", [])), "intentional_deviations": list(raw.get("intentional_deviations", [])), "scenes": normalized, "notes": str(raw.get("notes", ""))}


def command_outcome_set(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    session = load_json(state_path(root) / "sessions" / args.session / "session.json")
    if session.get("status") not in {"reviewed", "accepted"}:
        raise StoryError("章节必须先完成 review 才能登记实际结果")
    if args.confirm != args.session:
        raise StoryError("确认值必须与 session id 完全一致")
    chapter = int(session["chapter"])
    raw = read_json_value(Path(args.outcome))
    frozen_plan = plan_version(root, chapter, session.get("plan_version"))
    normalized = validate_outcome(raw, chapter, frozen_plan)
    normalized["actual_characters"] = int(session.get("review", {}).get("characters") or normalized["actual_characters"])
    path = outcome_path(root, chapter)
    history = load_json(path) if path.exists() else {"format": "serial-fiction-outcome-history/v1", "chapter": chapter, "versions": []}
    version = len(history["versions"]) + 1
    entry = {**normalized, "version": version, "session": args.session, "plan_version": session.get("plan_version"), "draft_sha256": session.get("review", {}).get("sha256"), "status": "accepted" if session.get("status") == "accepted" else "submitted", "approved_at": now_iso()}
    history["versions"].append(entry)
    write_json(path, history)
    return {"chapter": chapter, "version": version, "scenes": len(entry["scenes"])}


def latest_outcome(root: Path, chapter: int, status: str | None = None, session: str | None = None) -> dict | None:
    path = outcome_path(root, chapter)
    if not path.exists():
        return None
    versions = [item for item in load_json(path).get("versions", []) if (status is None or item.get("status") == status) and (session is None or item.get("session") == session)]
    return versions[-1] if versions else None


def promote_outcome(root: Path, chapter: int, session_id: str) -> bool:
    path = outcome_path(root, chapter)
    if not path.exists():
        return False
    history = load_json(path)
    candidates = [item for item in history.get("versions", []) if item.get("session") == session_id]
    if not candidates:
        return False
    target = candidates[-1]
    target["status"] = "accepted"
    target["accepted_at"] = target.get("accepted_at") or now_iso()
    write_json(path, history)
    return True


def compare_plan_outcome(plan: dict, outcome: dict) -> dict:
    findings: list[dict] = []
    actual_by_plan: dict[str, list[dict]] = {}
    for item in outcome["scenes"]:
        for reference in item.get("plan_scene_ids", [item.get("plan_scene_id")]):
            if reference:
                actual_by_plan.setdefault(str(reference), []).append(item)
    fulfilled = set(map(str, outcome.get("fulfilled_commitments", [])))
    for commitment in plan.get("commitments", []):
        if commitment["id"] not in fulfilled:
            findings.append({"severity": "error" if commitment["priority"] == "must" else "risk", "category": "commitment", "message": f"未完成计划承诺：{commitment['description']}"})
    for scene in plan["scenes"]:
        actuals = actual_by_plan.get(scene["id"], [])
        if not actuals:
            findings.append({"severity": "risk", "category": "scene", "message": f"计划场景未出现：{scene['id']} · {scene['purpose']}"})
            continue
        actual_tension = max(int(item["tension"]) for item in actuals)
        if abs(int(scene["tension"]) - actual_tension) >= 2:
            findings.append({"severity": "risk", "category": "pacing", "message": f"场景 {scene['id']} 紧张度由 {scene['tension']} 偏移为 {actual_tension}"})
        if any(item.get("irreversible") for item in actuals) and not scene.get("irreversible"):
            findings.append({"severity": "risk", "category": "scope", "message": f"场景 {scene['id']} 出现计划外不可逆变化", "requires_user_decision": True})
        planned_actions = {(str(item.get("setup_id")), str(item.get("action"))) for item in scene.get("setup_actions", [])}
        actual_actions = {(str(action.get("setup_id")), str(action.get("action"))) for item in actuals for action in item.get("setup_actions", [])}
        for action in planned_actions - actual_actions:
            findings.append({"severity": "risk", "category": "setup", "message": f"场景 {scene['id']} 未执行伏笔操作 {action[0]}:{action[1]}"})
    for scene in outcome["scenes"]:
        if not scene.get("plan_scene_ids"):
            severity = "risk" if scene.get("irreversible") else "info"
            finding = {"severity": severity, "category": "scene", "message": f"出现计划外场景：{scene['summary']}"}
            if scene.get("irreversible"):
                finding["requires_user_decision"] = True
            findings.append(finding)
    target = int(plan.get("pacing", {}).get("target_characters") or 0)
    actual_chars = int(outcome.get("actual_characters") or 0)
    if target and actual_chars and abs(actual_chars - target) / target > 0.35:
        findings.append({"severity": "risk", "category": "length", "message": f"篇幅由目标 {target} 偏移为 {actual_chars}"})
    constraint_map = {item["id"]: item for item in plan.get("constraints", [])}
    for constraint_id in outcome.get("violated_constraints", []):
        constraint = constraint_map[constraint_id]
        findings.append({"severity": "error" if constraint["level"] == "hard" else "risk", "category": "constraint", "message": f"违反约束 {constraint_id}：{constraint['description']}"})
    for change in outcome.get("unplanned_changes", []):
        findings.append({"severity": "risk", "category": "scope", "message": f"计划外变化：{change}"})
    for deviation in outcome.get("intentional_deviations", []):
        findings.append({"severity": "intentional", "category": "authorial", "message": f"用户保留的有意偏离：{deviation}"})
    return {"chapter": int(plan["chapter"]), "plan_version": plan["version"], "outcome_version": outcome["version"], "findings": findings, "requires_human_checkpoint": any(item["severity"] in {"error", "risk"} for item in findings)}


def command_deviation(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    outcome = latest_outcome(root, args.chapter, session=getattr(args, "session", None)) if getattr(args, "session", None) else (latest_outcome(root, args.chapter, status="accepted") or latest_outcome(root, args.chapter))
    plan = plan_version(root, args.chapter, outcome.get("plan_version") if outcome else None)
    if plan is None or outcome is None:
        raise StoryError("偏差检查需要已批准的计划和已登记的实际结果")
    report = compare_plan_outcome(plan, outcome)
    report["session"] = outcome.get("session")
    report["status"] = outcome.get("status")
    write_json(state_path(root) / "deviations" / f"chapter-{args.chapter:06d}-{outcome.get('session', 'unknown')}.json", report)
    return report


def command_pacing(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    if args.window < 1:
        raise StoryError("window 必须大于 0")
    paths = sorted((state_path(root) / "outcomes").glob("chapter-*.json")) if (state_path(root) / "outcomes").exists() else []
    chapters: list[dict] = []
    for path in paths:
        versions = load_json(path).get("versions", [])
        if not versions:
            continue
        accepted = [item for item in versions if item.get("status") == "accepted"]
        if not accepted:
            continue
        item = accepted[-1]
        tensions = [int(scene["tension"]) for scene in item["scenes"]]
        chapters.append({"chapter": int(item["chapter"]), "average_tension": sum(tensions) / len(tensions), "peak_tension": max(tensions), "information_gain": sum(int(scene["information_gain"]) for scene in item["scenes"]), "irreversible_changes": sum(bool(scene.get("irreversible")) for scene in item["scenes"]), "functions": [scene["function"] for scene in item["scenes"]]})
    chapters.sort(key=lambda item: item["chapter"])
    findings: list[dict] = []
    window = chapters[-args.window :]
    consecutive: list[dict] = []
    for item in reversed(window):
        if not consecutive or item["chapter"] == consecutive[-1]["chapter"] - 1:
            consecutive.append(item)
        else:
            break
    consecutive.reverse()
    if len(consecutive) >= 3 and all(item["average_tension"] <= 2 for item in consecutive[-3:]):
        findings.append({"severity": "risk", "message": "最近三章平均紧张度持续不高于 2"})
    if len(consecutive) >= 4 and all(item["average_tension"] >= 4 for item in consecutive[-4:]):
        findings.append({"severity": "risk", "message": "最近四章持续高压，可能产生高潮疲劳"})
    if len(consecutive) >= 5 and sum(item["irreversible_changes"] for item in consecutive[-5:]) == 0:
        findings.append({"severity": "risk", "message": "最近五章没有记录不可逆变化，请确认主线是否停滞"})
    snapshot = load_json(state_path(root) / "snapshot.json")
    accepted_numbers = {int(item.get("chapter") or 0) for item in snapshot.get("chapters", []) if int(item.get("chapter") or 0) > 0}
    assessed_numbers = {item["chapter"] for item in chapters}
    coverage = len(assessed_numbers & accepted_numbers) / len(accepted_numbers) if accepted_numbers else 0.0
    report = {"generated_at": now_iso(), "window": args.window, "chapters": window, "consecutive_tail": len(consecutive), "accepted_chapters": len(accepted_numbers), "assessed_chapters": len(assessed_numbers & accepted_numbers), "coverage": coverage, "insufficient_data": len(consecutive) < 3 or coverage < 0.6, "findings": findings, "editorial_interpretation_required": True}
    write_json(state_path(root) / "pacing.json", report)
    return report


def command_begin(args: argparse.Namespace) -> dict:
    root, manifest = require_project(Path(args.root))
    require_chapter_number_available(root, int(args.chapter))
    snapshot_file = state_path(root) / "snapshot.json"
    snapshot = load_json(snapshot_file) if snapshot_file.exists() else rebuild_snapshot(root)
    session_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    plan = active_plan(root, args.chapter)
    effective_goal = plan["goal"] if plan else args.goal
    retrieval = search_index_report(root, args.query or effective_goal, args.limit, 0.65, 0.35)
    results = retrieval["hits"]
    session_dir = state_path(root) / "sessions" / session_id
    if args.out:
        requested_context = Path(args.out)
        context_path = (requested_context if requested_context.is_absolute() else root / requested_context).resolve()
    else:
        context_path = session_dir / "context.md"
    if context_path.exists():
        raise StoryError(f"上下文输出文件已存在，拒绝覆盖：{context_path}")
    memory_markdown, memory_report = compact_snapshot_markdown(snapshot)
    plan_digest = plan_payload_digest(plan) if plan else None
    session = {"format": "serial-fiction-session/v1", "id": session_id, "status": "prepared", "created_at": now_iso(), "chapter": args.chapter, "goal": effective_goal, "requested_goal": args.goal if plan and args.goal != effective_goal else None, "query": args.query or effective_goal, "snapshot_built_at": snapshot.get("built_at"), "memory_context": memory_report, "plan_version": plan.get("version") if plan else None, "plan_digest": plan_digest, "retrieval": {key: retrieval[key] for key in ("mode", "lexical_backend", "requested_weights", "effective_weights", "warnings")}, "review": None}
    write_json(session_dir / "session.json", session)
    sections = [f"# 第 {args.chapter} 章创作上下文", f"\n## 本章目标\n\n{effective_goal}", "\n" + memory_markdown]
    if plan:
        sections.append("\n" + plan_markdown(plan))
    sections.append("\n## 最近正文")
    for name, text in recent_chapters(root, manifest):
        sections.append(f"\n### {name}\n\n{text}")
    sections.append("\n## 检索证据（须核验）")
    if retrieval["warnings"]:
        sections.append("\n### 检索降级说明\n\n" + "\n".join(f"- {warning}" for warning in retrieval["warnings"]))
    for item in results:
        sections.append(f"\n### {item['title']} · {item['path']} · score={item['score']:.3f}\n\n{item['text']}")
    context = "\n".join(sections).strip() + "\n"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(context, encoding="utf-8")
    return {"session": session_id, "context": str(context_path), "retrieved": len(results), "memory_context": memory_report, "retrieval": session["retrieval"]}


def repeated_lines(text: str) -> list[str]:
    counts: dict[str, int] = {}
    for line in re.split(r"[。！？!?\n]+", text):
        normalized = re.sub(r"\s+", "", line)
        if len(normalized) >= 12:
            counts[normalized] = counts.get(normalized, 0) + 1
    return [line for line, count in counts.items() if count > 1]


def command_review(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    session_path = state_path(root) / "sessions" / args.session / "session.json"
    session = load_json(session_path)
    if session.get("status") == "accepted":
        raise StoryError("已接受的会话不能重新审稿")
    draft_path = Path(args.draft).resolve()
    text = read_text(draft_path)
    snapshot = load_json(state_path(root) / "snapshot.json")
    findings: list[dict] = []
    if len(text.strip()) < 800:
        findings.append({"severity": "risk", "code": "short-draft", "message": f"草稿仅 {len(text.strip())} 字符"})
    for item in snapshot.get("decisions", []):
        if item.get("predicate") == "forbid_phrase" and str(item.get("value", "")) in text:
            findings.append({"severity": "error", "code": "forbidden-phrase", "message": f"出现禁用内容：{item.get('value')}"})
    frozen_plan = plan_version(root, int(session["chapter"]), session.get("plan_version"))
    if frozen_plan:
        digest = plan_payload_digest(frozen_plan)
        if digest != session.get("plan_digest"):
            findings.append({"severity": "error", "code": "plan-mutated", "message": "会话绑定的计划版本被原地修改"})
        for constraint in frozen_plan.get("constraints", []):
            phrase = constraint.get("forbidden_phrase")
            if phrase and str(phrase) in text:
                findings.append({"severity": "error" if constraint["level"] == "hard" else "risk", "code": "plan-constraint", "message": f"触发计划约束 {constraint['id']}：{constraint['description']}"})
    for line in repeated_lines(text):
        findings.append({"severity": "risk", "code": "repeated-sentence", "message": f"疑似重复句：{line[:80]}"})
    review = {"reviewed_at": now_iso(), "draft": str(draft_path), "sha256": hashlib.sha256(draft_path.read_bytes()).hexdigest(), "characters": len(text.strip()), "findings": findings, "requires_human_checkpoint": True}
    session["status"] = "reviewed"
    session["review"] = review
    write_json(session_path, session)
    write_json(session_path.parent / "review.json", review)
    return review


def command_accept(args: argparse.Namespace) -> dict:
    root, manifest = require_project(Path(args.root))
    session_path = state_path(root) / "sessions" / args.session / "session.json"
    session = load_json(session_path)
    if args.confirm != args.session:
        raise StoryError("确认值必须与 session id 完全一致")
    if session.get("status") != "reviewed" or not session.get("review"):
        raise StoryError("草稿必须先通过 review 流程")
    require_chapter_number_available(root, int(session["chapter"]))
    blocking = [item for item in session["review"].get("findings", []) if item.get("severity") == "error"]
    if blocking:
        raise StoryError(f"审稿仍有 {len(blocking)} 个 error，不能接受章节")
    draft = Path(args.draft).resolve()
    digest = hashlib.sha256(draft.read_bytes()).hexdigest()
    if digest != session["review"].get("sha256"):
        raise StoryError("草稿在审稿后发生变化，请重新 review")
    frozen_plan = plan_version(root, int(session["chapter"]), session.get("plan_version"))
    if frozen_plan and plan_payload_digest(frozen_plan) != session.get("plan_digest"):
        raise StoryError("会话绑定的计划版本被原地修改")
    outcome = latest_outcome(root, int(session["chapter"]), session=args.session)
    if frozen_plan and outcome is None:
        raise StoryError("有冻结计划的章节必须先登记实际结果并完成偏差检查")
    if outcome:
        if outcome.get("draft_sha256") != digest:
            raise StoryError("实际结果绑定的草稿摘要已过期，请重新登记")
        if frozen_plan:
            deviation = compare_plan_outcome(frozen_plan, outcome)
            blocking_deviations = [item for item in deviation["findings"] if item.get("severity") == "error"]
            deviation["status"] = "blocked" if blocking_deviations else "reviewed"
            deviation["session"] = args.session
            deviation["draft_sha256"] = digest
            write_json(state_path(root) / "deviations" / f"chapter-{int(session['chapter']):06d}-{args.session}.json", deviation)
            if blocking_deviations:
                raise StoryError(f"计划偏差仍有 {len(blocking_deviations)} 个 error，不能接受章节")
    chapter_dir = resolve_manifest_path(root, manifest["chapters"])
    chapter_dir.mkdir(parents=True, exist_ok=True)
    destination = chapter_dir / manifest.get("chapter_filename", "第{chapter:04d}章.md").format(chapter=int(session["chapter"]))
    if destination.exists():
        raise StoryError(f"目标章节已存在：{destination}")
    transaction_path = state_path(root) / "transactions" / f"{args.session}.json"
    pending_path = destination.with_name(f".{destination.name}.{args.session}.pending")
    journal = {"format": "serial-fiction-transaction/v1", "session": args.session, "status": "prepared", "draft": str(draft), "pending": str(pending_path), "destination": str(destination), "digest": digest, "chapter": int(session["chapter"]), "created_at": now_iso()}
    write_json(transaction_path, journal)
    shutil.copy2(draft, pending_path)
    if hashlib.sha256(pending_path.read_bytes()).hexdigest() != digest:
        raise StoryError("章节临时副本校验失败")
    os.replace(pending_path, destination)
    journal["status"] = "manuscript-written"
    write_json(transaction_path, journal)
    event = append_event(root, {"id": f"chapter-{args.session}", "kind": "chapter", "subject": destination.name, "predicate": "accepted", "value": digest, "chapter": int(session["chapter"]), "source": f"session:{args.session}"})
    journal["status"] = "ledger-written"
    write_json(transaction_path, journal)
    session["status"] = "accepted"
    session["accepted_at"] = now_iso()
    session["destination"] = str(destination)
    write_json(session_path, session)
    if outcome:
        promote_outcome(root, int(session["chapter"]), args.session)
    rebuild_snapshot(root)
    journal["status"] = "complete"
    journal["completed_at"] = now_iso()
    write_json(transaction_path, journal)
    return {"chapter": str(destination), "event": event}


def recovery_actions(root: Path) -> list[dict]:
    actions: list[dict] = []
    existing_ids = {str(event.get("id")) for event in load_events(root)}
    transactions = state_path(root) / "transactions"
    if not transactions.exists():
        return actions
    for path in sorted(transactions.glob("*.json")):
        journal = load_json(path)
        if journal.get("status") == "complete":
            continue
        destination = Path(journal["destination"])
        pending = Path(journal["pending"])
        expected = str(journal["digest"])
        event_id = f"chapter-{journal['session']}"
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected and event_id not in existing_ids:
            actions.append({"transaction": str(path), "action": "append-chapter-event"})
        elif not destination.exists() and pending.exists() and hashlib.sha256(pending.read_bytes()).hexdigest() == expected:
            actions.append({"transaction": str(path), "action": "finish-pending-copy"})
        elif event_id in existing_ids:
            actions.append({"transaction": str(path), "action": "finalize-metadata"})
        else:
            actions.append({"transaction": str(path), "action": "manual-review", "reason": "文件缺失或摘要不匹配"})
    return actions


def command_recover(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    actions = recovery_actions(root)
    if not args.apply:
        return {"mode": "preview", "actions": actions}
    if args.confirm != "RECOVER":
        raise StoryError("执行恢复需要 --confirm RECOVER")
    applied = 0
    for action in actions:
        if action["action"] == "manual-review":
            continue
        journal_path = Path(action["transaction"])
        journal = load_json(journal_path)
        destination = Path(journal["destination"])
        pending = Path(journal["pending"])
        if action["action"] == "finish-pending-copy":
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(pending, destination)
        existing_ids = {str(event.get("id")) for event in load_events(root)}
        event_id = f"chapter-{journal['session']}"
        if event_id not in existing_ids:
            append_event(root, {"id": event_id, "kind": "chapter", "subject": destination.name, "predicate": "accepted", "value": journal["digest"], "chapter": int(journal["chapter"]), "source": f"session:{journal['session']}"})
        session_path = state_path(root) / "sessions" / journal["session"] / "session.json"
        session = load_json(session_path)
        session["status"] = "accepted"
        session["accepted_at"] = session.get("accepted_at") or now_iso()
        session["destination"] = str(destination)
        write_json(session_path, session)
        promote_outcome(root, int(journal["chapter"]), str(journal["session"]))
        journal["status"] = "complete"
        journal["recovered_at"] = now_iso()
        write_json(journal_path, journal)
        applied += 1
    rebuild_snapshot(root)
    return {"mode": "apply", "applied": applied, "manual_review": sum(item["action"] == "manual-review" for item in actions)}


def event_position(event: dict, fallback: int) -> tuple[int, float, int]:
    chapter = int(event.get("chapter") or 0)
    try:
        order = float(event.get("order")) if event.get("order") is not None else float(fallback)
    except (TypeError, ValueError):
        order = float(fallback)
    return chapter, order, fallback


def structured_findings(events: Sequence[dict]) -> list[dict]:
    findings: list[dict] = []
    facts_by_key: dict[tuple[str, str], list[tuple[tuple[int, float, int], dict]]] = {}
    for index, event in enumerate(events):
        if event.get("kind") in {"fact", "timeline"}:
            key = (str(event.get("subject", "")), str(event.get("predicate", "")))
            facts_by_key.setdefault(key, []).append((event_position(event, index), event))

    for (subject, predicate), positioned in facts_by_key.items():
        positioned.sort(key=lambda pair: pair[0])
        if predicate == "age":
            previous: float | None = None
            for _, event in positioned:
                try:
                    current = float(event.get("value"))
                except (TypeError, ValueError):
                    continue
                if previous is not None and current < previous:
                    findings.append({"severity": "error", "category": "character", "message": f"{subject} 的年龄从 {previous:g} 降为 {current:g}"})
                previous = current
        if predicate in {"location", "owner"}:
            by_moment: dict[tuple[int, float], set[str]] = {}
            for position, event in positioned:
                by_moment.setdefault(position[:2], set()).add(str(event.get("value")))
            for moment, values in by_moment.items():
                if len(values) > 1:
                    findings.append({"severity": "error", "category": "continuity", "message": f"{subject} 在 {moment} 同时存在多个 {predicate}：{sorted(values)}"})

    death_at: dict[str, tuple[int, float, int]] = {}
    for index, event in enumerate(events):
        subject = str(event.get("subject", ""))
        position = event_position(event, index)
        if event.get("kind") == "fact" and event.get("predicate") == "status" and str(event.get("value")).lower() in {"dead", "deceased", "死亡", "已死"}:
            death_at[subject] = position
            continue
        if subject in death_at and position > death_at[subject] and event.get("kind") in {"fact", "timeline"}:
            if event.get("predicate") == "status" and str(event.get("value")).lower() in {"dead", "deceased", "死亡", "已死"}:
                continue
            findings.append({"severity": "risk", "category": "character", "message": f"{subject} 在死亡记录后仍有事件 {event.get('id')}；若为复活或回忆需明确标注"})
    return findings


def command_audit(args: argparse.Namespace) -> dict:
    root, manifest = require_project(Path(args.root))
    events = load_events(root)
    snapshot = reduce_events(events)
    findings = [{"severity": "error", "message": message} for message in snapshot.get("warnings", [])]
    chapter_numbers: dict[int, list[str]] = {}
    for item in snapshot.get("chapters", []):
        number = int(item.get("chapter") or 0)
        chapter_numbers.setdefault(number, []).append(str(item.get("subject")))
    for number, names in chapter_numbers.items():
        if number and len(names) > 1:
            findings.append({"severity": "error", "message": f"第 {number} 章有多个接受记录：{names}"})
    open_setups = [item for item in snapshot.get("setups", []) if item.get("status") == "open"]
    latest = max(chapter_numbers, default=0)
    for item in open_setups:
        created = int(item.get("chapter") or 0)
        if latest and created and latest - created >= args.setup_age:
            findings.append({"severity": "risk", "message": f"伏笔 {item.get('id')} 已悬置 {latest - created} 章：{item.get('value')}"})
    chapter_dir = resolve_manifest_path(root, manifest["chapters"])
    disk_files = list(iter_source_files([chapter_dir]))
    disk_by_name = {path.name: path for path in disk_files}
    accepted_names = {str(item.get("subject", "")) for item in snapshot.get("chapters", [])}
    for item in snapshot.get("chapters", []):
        name = str(item.get("subject", ""))
        path = disk_by_name.get(name)
        if path is None:
            findings.append({"severity": "error", "category": "manuscript", "message": f"账本中的已接受正文文件已丢失：{name}"})
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item.get("value"):
            findings.append({"severity": "error", "category": "manuscript", "message": f"已接受章节在记录后被修改：{name}"})
    for path in disk_files:
        if path.name not in accepted_names and chapter_number(path, read_text(path)) is not None:
            findings.append({"severity": "error", "category": "manuscript", "message": f"正文目录存在未写入账本的孤儿章节：{path.name}"})
    findings.extend(structured_findings(events))
    report = {"audited_at": now_iso(), "events": len(events), "accepted_chapters": len(snapshot.get("chapters", [])), "manuscript_files": len(disk_files), "open_setups": len(open_setups), "findings": findings, "editorial_review_required": True}
    write_json(state_path(root) / "audit.json", report)
    return report


def numbered_chapters(root: Path, manifest: dict, first: int | None = None, last: int | None = None) -> list[tuple[int, Path]]:
    result: list[tuple[int, Path]] = []
    chapter_dir = resolve_manifest_path(root, manifest["chapters"])
    for path in iter_source_files([chapter_dir]):
        number = chapter_number(path, read_text(path))
        if number is not None and (first is None or number >= first) and (last is None or number <= last):
            result.append((number, path))
    return sorted(result, key=lambda pair: pair[0])


def command_audit_pack(args: argparse.Namespace) -> dict:
    root, manifest = require_project(Path(args.root))
    if args.batch_size < 1:
        raise StoryError("batch-size 必须大于 0")
    chapters = numbered_chapters(root, manifest, args.from_chapter, args.to_chapter)
    if not chapters:
        raise StoryError("指定范围内没有可审计章节")
    audit_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    audit_dir = state_path(root) / "audits" / audit_id
    snapshot = load_json(state_path(root) / "snapshot.json")
    batches: list[dict] = []
    for start in range(0, len(chapters), args.batch_size):
        group = chapters[start : start + args.batch_size]
        batch_no = len(batches) + 1
        path = audit_dir / f"batch-{batch_no:03d}.md"
        sections = [f"# 语义审计批次 {batch_no}", "\n" + snapshot_markdown(snapshot), "\n## 正文"]
        hashes: list[dict] = []
        for number, chapter_path in group:
            text = read_text(chapter_path)
            sections.append(f"\n### 第 {number} 章 · {chapter_path.name}\n\n{text}")
            hashes.append({"chapter": number, "name": chapter_path.name, "sha256": hashlib.sha256(chapter_path.read_bytes()).hexdigest()})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(sections).strip() + "\n", encoding="utf-8")
        batches.append({"batch": batch_no, "path": str(path), "chapters": hashes, "status": "pending"})
    audit = {"format": "serial-fiction-semantic-audit/v1", "id": audit_id, "scope": args.scope, "created_at": now_iso(), "status": "pending", "batches": batches}
    write_json(audit_dir / "manifest.json", audit)
    return {"audit": audit_id, "scope": args.scope, "chapters": len(chapters), "batches": len(batches), "directory": str(audit_dir)}


def validate_audit_finding(item: dict, allowed_chapters: set[int]) -> dict:
    if not isinstance(item, dict):
        raise StoryError("审计 finding 必须是 object")
    category = str(item.get("category", ""))
    severity = str(item.get("severity", ""))
    chapter = parse_int(item.get("chapter") or 0, "finding chapter")
    evidence = str(item.get("evidence", "")).strip()
    message = str(item.get("message", "")).strip()
    if category not in {"canon", "chronology", "character", "setup", "structure", "prose"}:
        raise StoryError(f"未知审计类别：{category}")
    if severity not in {"error", "risk", "intentional"}:
        raise StoryError(f"未知严重度：{severity}")
    if chapter not in allowed_chapters:
        raise StoryError(f"finding 章节不在批次中：{chapter}")
    if not evidence or not message:
        raise StoryError("finding 必须包含 evidence 与 message")
    return {"category": category, "severity": severity, "chapter": chapter, "evidence": evidence[:500], "message": message, "related_chapters": item.get("related_chapters", [])}


def command_audit_submit(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    audit_dir = state_path(root) / "audits" / args.audit
    manifest_path = audit_dir / "manifest.json"
    audit = load_json(manifest_path)
    batch = next((item for item in audit.get("batches", []) if int(item["batch"]) == args.batch), None)
    if batch is None:
        raise StoryError("审计批次不存在")
    allowed = {int(item["chapter"]) for item in batch["chapters"]}
    raw = read_json_value(Path(args.findings))
    if not isinstance(raw, list):
        raise StoryError("审计结果顶层必须是数组")
    findings = [validate_audit_finding(item, allowed) for item in raw]
    result = {"format": "serial-fiction-audit-findings/v1", "audit": args.audit, "batch": args.batch, "reviewed_at": now_iso(), "findings": findings}
    write_json(audit_dir / f"batch-{args.batch:03d}-findings.json", result)
    batch["status"] = "reviewed"
    write_json(manifest_path, audit)
    return {"audit": args.audit, "batch": args.batch, "findings": len(findings)}


def command_audit_finalize(args: argparse.Namespace) -> dict:
    root, _ = require_project(Path(args.root))
    audit_dir = state_path(root) / "audits" / args.audit
    manifest_path = audit_dir / "manifest.json"
    audit = load_json(manifest_path)
    missing = [int(item["batch"]) for item in audit.get("batches", []) if not (audit_dir / f"batch-{int(item['batch']):03d}-findings.json").exists()]
    if missing:
        raise StoryError(f"仍有未提交批次：{missing}")
    findings: list[dict] = []
    for item in audit["batches"]:
        findings.extend(load_json(audit_dir / f"batch-{int(item['batch']):03d}-findings.json")["findings"])
    counts = {severity: sum(item["severity"] == severity for item in findings) for severity in ("error", "risk", "intentional")}
    report = {"format": "serial-fiction-semantic-report/v1", "audit": args.audit, "scope": audit["scope"], "completed_at": now_iso(), "counts": counts, "findings": findings, "human_checkpoint_required": True}
    write_json(audit_dir / "report.json", report)
    lines = [f"# 语义审计报告 · {args.audit}", f"\n错误 {counts['error']}，风险 {counts['risk']}，有意保留 {counts['intentional']}。"]
    for item in findings:
        lines.append(f"\n- [{item['severity']}/{item['category']}] 第{item['chapter']}章：{item['message']}（证据：{item['evidence']}）")
    (audit_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    audit["status"] = "complete"
    audit["completed_at"] = now_iso()
    write_json(manifest_path, audit)
    return {"audit": args.audit, "counts": counts, "report": str(audit_dir / "report.md")}


def backup_members(root: Path, manifest: dict, include_context: bool) -> list[tuple[Path, str]]:
    members: list[tuple[Path, str]] = []
    meta = state_path(root)
    for name in ("manifest.json", "ledger.jsonl", "snapshot.json", "audit.json", "pacing.json"):
        path = meta / name
        if path.exists():
            members.append((path, f"storywork/{name}"))
    for folder in ("sessions", "audits", "transactions", "plans", "outcomes", "deviations"):
        base = meta / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and (include_context or path.name != "context.md"):
                members.append((path, "storywork/" + path.relative_to(meta).as_posix()))
    for number, path in numbered_chapters(root, manifest):
        members.append((path, f"manuscript/{number:06d}-{path.name}"))
    return members


def command_backup(args: argparse.Namespace) -> dict:
    root, manifest = require_project(Path(args.root))
    destination_value = getattr(args, "archive", None) or getattr(args, "out", None) or getattr(args, "archive_positional", None)
    if not destination_value:
        raise StoryError("backup 需要 --archive <文件路径>")
    destination = Path(destination_value).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    members = backup_members(root, manifest, args.include_context)
    hashes = []
    temporary = destination.with_name(destination.name + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, arcname in members:
            data = path.read_bytes()
            archive.writestr(arcname, data)
            hashes.append({"path": arcname, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
        archive.writestr("backup-manifest.json", json.dumps({"format": "serial-fiction-backup/v1", "created_at": now_iso(), "project_title": manifest["title"], "files": hashes}, ensure_ascii=False, indent=2).encode("utf-8"))
    os.replace(temporary, destination)
    return {"backup": str(destination), "files": len(hashes), "bytes": destination.stat().st_size}


def command_verify_backup(args: argparse.Namespace) -> dict:
    archive_value = getattr(args, "archive", None) or getattr(args, "archive_positional", None)
    if not archive_value:
        raise StoryError("verify-backup 需要 --archive <文件路径>")
    archive_path = Path(archive_value).resolve()
    failures: list[str] = []
    with zipfile.ZipFile(archive_path, "r") as archive:
        manifest = json.loads(archive.read("backup-manifest.json").decode("utf-8"))
        for item in manifest.get("files", []):
            data = archive.read(item["path"])
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                failures.append(item["path"])
    return {"archive": str(archive_path), "valid": not failures, "files": len(manifest.get("files", [])), "failures": failures}


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="initialize metadata for a novel")
    init.add_argument("root"); init.add_argument("--title", required=True); init.add_argument("--chapters", default="chapters"); init.set_defaults(func=command_init)
    record = sub.add_parser("record", help="append a canon or decision event")
    record.add_argument("root"); record.add_argument("--kind", required=True, choices=sorted(EVENT_KINDS - {"chapter"})); record.add_argument("--subject", required=True); record.add_argument("--predicate", required=True)
    record_value = record.add_mutually_exclusive_group(required=True)
    record_value.add_argument("--value")
    record_value.add_argument("--value-file", help="read a UTF-8/GB18030 value from a file; safer for long text and shell-sensitive punctuation")
    record.add_argument("--chapter", type=int); record.add_argument("--order", type=float); record.add_argument("--entity-type"); record.add_argument("--source", default="manual"); record.set_defaults(func=command_record)
    adopt = sub.add_parser("adopt", help="preview or record existing manuscript chapters")
    adopt.add_argument("root"); adopt.add_argument("--apply", action="store_true"); adopt.add_argument("--confirm"); adopt.set_defaults(func=command_adopt)
    rebuild = sub.add_parser("rebuild", help="reduce the ledger into a snapshot")
    rebuild.add_argument("root"); rebuild.set_defaults(func=lambda args: rebuild_snapshot(require_project(Path(args.root))[0]))
    index = sub.add_parser("index", help="rebuild lexical and optional semantic retrieval")
    index.add_argument("root"); index.add_argument("--source", action="append"); index.add_argument("--embeddings", choices=["none", "ollama"]); index.add_argument("--model"); index.add_argument("--endpoint"); index.add_argument("--ann", choices=["auto", "exact", "hnsw"]); index.set_defaults(func=command_index)
    query = sub.add_parser("query", help="retrieve relevant passages")
    query.add_argument("root"); query.add_argument("query"); query.add_argument("--limit", type=int, default=8); query.add_argument("--lexical-weight", type=float, default=0.65); query.add_argument("--semantic-weight", type=float, default=0.35); query.set_defaults(func=command_query)
    begin = sub.add_parser("begin", help="create a draft session and context pack")
    begin.add_argument("root"); begin.add_argument("--chapter", type=int, required=True); begin.add_argument("--goal", required=True); begin.add_argument("--query"); begin.add_argument("--limit", type=int, default=8); begin.add_argument("--out"); begin.set_defaults(func=command_begin)
    mechanical_review = sub.add_parser("mechanical-review", help="run deterministic mechanical checks on a draft")
    mechanical_review.add_argument("root"); mechanical_review.add_argument("--session", required=True); mechanical_review.add_argument("--draft", required=True); mechanical_review.set_defaults(func=command_review)
    review = sub.add_parser("review", help="compatibility alias for mechanical-review")
    review.add_argument("root"); review.add_argument("--session", required=True); review.add_argument("--draft", required=True); review.set_defaults(func=command_review)
    accept = sub.add_parser("accept", help="commit an approved, reviewed draft")
    accept.add_argument("root"); accept.add_argument("--session", required=True); accept.add_argument("--draft", required=True); accept.add_argument("--confirm", required=True); accept.set_defaults(func=command_accept)
    stage = sub.add_parser("stage-events", help="stage model-extracted chapter events for human approval")
    stage.add_argument("root"); stage.add_argument("--session", required=True); stage.add_argument("--events", required=True); stage.set_defaults(func=command_stage_events)
    approve = sub.add_parser("approve-events", help="append approved extracted events to the canon ledger")
    approve.add_argument("root"); approve.add_argument("--session", required=True); approve.add_argument("--confirm", required=True); approve.set_defaults(func=command_approve_events)
    plan_set = sub.add_parser("plan-set", help="approve a versioned lightweight chapter plan")
    plan_set.add_argument("root"); plan_set.add_argument("--chapter", type=int, required=True); plan_set.add_argument("--plan", required=True); plan_set.add_argument("--confirm", required=True); plan_set.set_defaults(func=command_plan_set)
    outcome_set = sub.add_parser("outcome-set", help="record reviewed actual scene and pacing results")
    outcome_set.add_argument("root"); outcome_set.add_argument("--session", required=True); outcome_set.add_argument("--outcome", required=True); outcome_set.add_argument("--confirm", required=True); outcome_set.set_defaults(func=command_outcome_set)
    deviation = sub.add_parser("deviation", help="compare an approved plan with actual chapter results")
    deviation.add_argument("root"); deviation.add_argument("--chapter", type=int, required=True); deviation.add_argument("--session"); deviation.set_defaults(func=command_deviation)
    pacing = sub.add_parser("pacing", help="summarize pacing from accepted actual chapter results")
    pacing.add_argument("root"); pacing.add_argument("--window", type=int, default=10); pacing.set_defaults(func=command_pacing)
    recover = sub.add_parser("recover", help="preview or repair interrupted chapter transactions")
    recover.add_argument("root"); recover.add_argument("--apply", action="store_true"); recover.add_argument("--confirm"); recover.set_defaults(func=command_recover)
    audit = sub.add_parser("audit", help="audit ledger and manuscript invariants")
    audit.add_argument("root"); audit.add_argument("--setup-age", type=int, default=30); audit.set_defaults(func=command_audit)
    audit_pack = sub.add_parser("audit-pack", help="split a volume into semantic review batches")
    audit_pack.add_argument("root"); audit_pack.add_argument("--scope", choices=["volume", "whole-book"], default="volume"); audit_pack.add_argument("--from-chapter", type=int); audit_pack.add_argument("--to-chapter", type=int); audit_pack.add_argument("--batch-size", type=int, default=4); audit_pack.set_defaults(func=command_audit_pack)
    audit_submit = sub.add_parser("audit-submit", help="submit one semantic audit batch")
    audit_submit.add_argument("root"); audit_submit.add_argument("--audit", required=True); audit_submit.add_argument("--batch", type=int, required=True); audit_submit.add_argument("--findings", required=True); audit_submit.set_defaults(func=command_audit_submit)
    audit_finalize = sub.add_parser("audit-finalize", help="finalize a fully reviewed semantic audit")
    audit_finalize.add_argument("root"); audit_finalize.add_argument("--audit", required=True); audit_finalize.set_defaults(func=command_audit_finalize)
    backup = sub.add_parser("backup", help="create a verified portable project archive")
    backup.add_argument("root"); backup.add_argument("archive_positional", nargs="?", help="legacy positional archive path"); backup.add_argument("--archive", "--out", dest="archive", help="destination archive path (--out remains an alias)"); backup.add_argument("--include-context", action="store_true"); backup.set_defaults(func=command_backup)
    verify = sub.add_parser("verify-backup", help="verify every member digest in a backup")
    verify.add_argument("archive_positional", nargs="?", help="legacy positional archive path"); verify.add_argument("--archive", help="archive path"); verify.set_defaults(func=command_verify_backup)
    return cli


def main(argv: Sequence[str] | None = None) -> int:
    configure_stdio()
    try:
        args = parser().parse_args(argv)
        result = args.func(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except StoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (TypeError, ValueError, KeyError) as exc:
        print(f"error: 输入数据无效：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
