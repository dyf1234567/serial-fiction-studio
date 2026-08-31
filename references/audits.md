# Audits

- Chapter review: after every draft and before acceptance.
- Volume audit: at a planned boundary or every 20–40 chapters.
- Whole-book audit: before publication, a major rewrite, or a sequel/postscript.

```powershell
python scripts/story_workspace.py audit <root>
```

This deterministic pass checks hashes, ledger integrity, missing accepted manuscript files, orphan chapter files not recorded in the ledger, old open setups, decreasing ages, conflicting same-moment locations or owners, and events recorded after a character's death.

如果迁移旧项目后发现同一章有多个当前接受记录，先运行 `audit` 获取事件 id，再明确选择已核验的正文记录进行收敛：

```powershell
python scripts/story_workspace.py chapter-repair <root> --chapter 3 --keep <event-id> --confirm REPAIR-3
```

该命令只追加一条可追溯的 reconciled 事件，不删除其他正文文件；若不同文件名仍留在正文目录，随后 `audit` 会把它报告为孤儿文件，交由人工归档或删除。

For a semantic volume or whole-book pass:

```powershell
python scripts/story_workspace.py audit-pack <root> --scope volume --from-chapter 1 --to-chapter 30 --batch-size 4
python scripts/story_workspace.py audit-submit <root> --audit <audit-id> --batch 1 --findings findings.json
python scripts/story_workspace.py audit-finalize <root> --audit <audit-id>
```

Read every generated batch completely. Submit findings in JSON objects with `category`, `severity`, `chapter`, `evidence`, and `message`. Categories are `canon`, `chronology`, `character`, `setup`, `structure`, and `prose`. Cross-batch problems belong in the later batch and should list `related_chapters`.

`audit-pack` writes one bounded `memory.md` beside the batches instead of copying the full snapshot into every batch. Every reviewer must read that shared file once and verify the SHA-256 printed in each batch before reviewing. The memory report identifies omitted counts, chapter ranges, and omitted critical items; use targeted retrieval or the full snapshot when an omitted area matters.

Classify findings as `error`, `risk`, or `intentional`. Never automatically rewrite an intentional ambiguity. A volume audit should end with locked facts, carried setups, arc positions, and next-volume constraints.
