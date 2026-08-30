# Recovery and backups

Chapter acceptance uses a journal and an atomic destination replacement. If the process stops mid-acceptance, preview recovery first:

```powershell
python scripts/story_workspace.py recover <root>
python scripts/story_workspace.py recover <root> --apply --confirm RECOVER
```

Do not apply an item marked `manual-review`; inspect the destination and digest first.

Create and verify a portable archive:

```powershell
python scripts/story_workspace.py backup <root> --out <backup.sfs.zip>
python scripts/story_workspace.py verify-backup <backup.sfs.zip>
```

Backups contain operational metadata, semantic audit results, transaction journals, and manuscript chapters. Rebuildable SQLite and HNSW indexes are excluded. Context packs are excluded unless `--include-context` is supplied because they may duplicate large or copyrighted reference excerpts.

Versioned plans, accepted outcome histories, pacing data, and deviation reports are included because they are not rebuildable from the ledger alone.

Keep at least one verified backup outside the novel directory before a volume-wide rewrite. Verification checks every archived member against its recorded SHA-256 digest.
