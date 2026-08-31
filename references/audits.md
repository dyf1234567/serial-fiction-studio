# Audits

- Chapter review: after every draft and before acceptance.
- Volume audit: at a planned boundary or every 20–40 chapters.
- Whole-book audit: before publication, a major rewrite, or a sequel/postscript.

```powershell
python scripts/story_workspace.py audit <root>
```

This deterministic pass checks hashes, ledger integrity, missing accepted manuscript files, orphan chapter files not recorded in the ledger, old open setups, decreasing ages, conflicting same-moment locations or owners, and events recorded after a character's death.

For a semantic volume or whole-book pass:

```powershell
python scripts/story_workspace.py audit-pack <root> --scope volume --from-chapter 1 --to-chapter 30 --batch-size 4
python scripts/story_workspace.py audit-submit <root> --audit <audit-id> --batch 1 --findings findings.json
python scripts/story_workspace.py audit-finalize <root> --audit <audit-id>
```

Read every generated batch completely. Submit findings in JSON objects with `category`, `severity`, `chapter`, `evidence`, and `message`. Categories are `canon`, `chronology`, `character`, `setup`, `structure`, and `prose`. Cross-batch problems belong in the later batch and should list `related_chapters`.

Classify findings as `error`, `risk`, or `intentional`. Never automatically rewrite an intentional ambiguity. A volume audit should end with locked facts, carried setups, arc positions, and next-volume constraints.
