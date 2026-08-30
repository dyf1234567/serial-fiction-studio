# Retrieval and portability

The index is disposable. The manuscript, manifest, and ledger are the portable source of truth.

SQLite FTS5 is the preferred dependency-free backend and is best for names, places, artifacts, quoted phrases, and direct answers. If the active Python SQLite build lacks FTS5, indexing automatically uses a slower ordinary-table lexical scan and reports `lexical_backend: scan`.

Optional semantic retrieval:

```powershell
python scripts/story_workspace.py index <root> --embeddings ollama --model bge-m3 --endpoint http://127.0.0.1:11434 --ann auto
```

The script supports the Ollama `/api/embed` protocol. The endpoint defaults to local Ollama but may point to a remote Ollama server. It calls the endpoint only when `--embeddings ollama` is explicitly selected. Embeddings are rebuildable, not required for portability. For an RTX 4060 laptop with 8 GB VRAM, `bge-m3` is a practical multilingual default. If unavailable, use `--embeddings none`.

`--ann auto` uses HNSW when the optional `hnswlib` and `numpy` packages are available, otherwise it uses exact cosine search. Use `--ann hnsw` to require HNSW and fail clearly if the dependency is missing. The HNSW file is derived data and should be rebuilt after migration.

Install the optional backend into the Python environment that runs the skill with `pip install -r scripts/requirements-optional.txt`. Do not commit platform-specific installed packages into the skill.

Indexing is incremental: unchanged files retain their chunks and embeddings; changed and removed files are updated transactionally. The ledger is reindexed only when its digest changes.

The first `index` call saves reference source paths and retrieval settings in the project manifest. Later calls may omit them and reuse the saved configuration.

Direct lexical hits receive the larger default share because continuity questions often depend on exact names and objects:

```powershell
python scripts/story_workspace.py query <root> "谁拿走了银戒" --lexical-weight 0.65 --semantic-weight 0.35
```

Raise semantic weight for paraphrases and lexical weight for factual questions. Retrieved passages are evidence, not canon. Keep copyrighted source corpora and generated databases out of a public repository.

`query` reports `mode`, requested and effective weights, lexical backend, warnings, and hits. If vectors are absent or the Ollama query fails, it emits a warning and transfers semantic weight to lexical retrieval instead of silently reducing every score.
