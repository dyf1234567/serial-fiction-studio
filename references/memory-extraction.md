# Chapter memory extraction

After a chapter is accepted, read that accepted file and propose only durable information needed in later chapters.

Write a JSON array. Each event requires:

```json
{
  "kind": "fact",
  "subject": "沈星",
  "predicate": "location",
  "value": "北塔",
  "chapter": 18,
  "order": 3,
  "entity_type": "character",
  "confidence": 0.95,
  "risk": "normal",
  "evidence": "沈星踏入北塔的门厅。"
}
```

Use `risk: high` for death, resurrection, identity revelation, power-system changes, irreversible relationship changes, or facts that alter the planned ending. Evidence must be a continuous short excerpt from the accepted chapter, no more than 300 characters. Ordinary events require at least 6 informative letters/numbers; high-risk events require at least 10. Punctuation and whitespace do not count. Quote enough surrounding text when the decisive sentence is shorter. `stage-events` and `approve-events` both verify the excerpt after whitespace normalization and verify that the accepted chapter hash has not changed.

Do not extract similes, hypothetical statements, lies, dreams, plans, negated claims, or facts known only inside a flashback as current state. Use `timeline` when the event matters but does not define current state. Use stable predicates such as `status`, `location`, `age`, `owner`, `allegiance`, `injury`, and `knows` when applicable.

Stage and review:

```powershell
python scripts/story_workspace.py stage-events <root> --session <session-id> --events proposed-events.json
python scripts/story_workspace.py approve-events <root> --session <session-id> --confirm <session-id>
```

Show the proposed changes and high-risk count to the user. Only run `approve-events` after explicit approval. Rejected or edited proposals remain outside the canon ledger.
