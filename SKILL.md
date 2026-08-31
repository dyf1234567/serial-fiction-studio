---
name: serial-fiction-studio
description: Plan, continue, revise, retrieve, and audit Chinese long-form fiction while preserving canon, chronology, character state, and unresolved setups. Use for sustained novel projects; use style-writer separately when an author-inspired prose profile is requested.
---

# Serial Fiction Studio

Treat the manuscript as creative work and `.storywork/` as its operational memory. Never infer that an indexed source is canon: canon comes from accepted ledger entries and committed chapters.

## Route the request

- For a new or adopted project, read [references/project-model.md](references/project-model.md).
- For continuing or revising prose, read [references/drafting-loop.md](references/drafting-loop.md).
- For retrieval, embeddings, or portability, read [references/retrieval.md](references/retrieval.md).
- For chapter, volume, or whole-book checks, read [references/audits.md](references/audits.md).
- After accepting a chapter, read [references/memory-extraction.md](references/memory-extraction.md) to propose state updates.
- For backups or interrupted writes, read [references/recovery.md](references/recovery.md).
- For chapter outlines, scene cards, pacing, or plan deviation, read [references/planning.md](references/planning.md).
- When the user explicitly requests multiple agents, read [references/multi-agent-editorial.md](references/multi-agent-editorial.md). Qoder-ready read-only reviewer definitions live under `adapters/qoder/agents/`.

Use `scripts/story_workspace.py` for deterministic project state, indexing, context assembly, and validation. Run it with `--help` before an unfamiliar operation.

## Non-negotiable invariants

1. Read the project manifest, current snapshot, latest committed chapter, and relevant open setups before drafting.
2. Distinguish confirmed canon, plans, hypotheses, and retrieved excerpts in the context supplied to the model.
3. Begin a draft session before writing. Review the resulting draft before proposing acceptance.
4. Do not commit a chapter or alter canon until the user explicitly accepts the draft. `accept` requires the session identifier as confirmation.
5. Record only consequences supported by the accepted chapter; do not silently convert plans into facts.
6. Preserve the user's ending, constraints, and intentional ambiguity. Flag contradictions instead of repairing them invisibly.
7. Keep style optional. When `$style-writer` or a style pack is requested, use it as a prose constraint provider; never let stylistic retrieval override project canon.
8. Keep plans and editorial opinions outside the canon ledger. A plan becomes a frozen session baseline, not an in-world fact.
9. Revise an accepted chapter only through `revise-begin`, review, and `accept`; never edit an accepted file and manually rewrite its digest or chapter event.

For several-thousand-character chapters, prepare a compact context pack rather than loading the whole corpus. Draft from that pack, run `mechanical-review`, then perform a human-facing creative checkpoint covering character motive, causal clarity, payoff timing, prose quality, and intentional deviations. The legacy `review` command is only a compatibility alias and never implies semantic judgment.

At a volume boundary, run an audit before starting the next volume. For high-impact changes—death, identity reveal, timeline jump, power-system change, irreversible relationship change—ask for confirmation even if the draft passes mechanical checks.

If vector embeddings are unavailable, report the downgrade and transfer the requested semantic weight to lexical retrieval. Prefer SQLite FTS5; if the Python SQLite build lacks FTS5, use the built-in lexical scan fallback. Never fail the writing workflow solely because an embedding service or FTS5 is absent.

After every accepted or revised chapter, extract candidate events with sufficiently informative quoted evidence, stage them, and ask the user to approve them before updating canon. At volume boundaries, read the audit's shared `memory.md`, complete every semantic audit batch, and present the consolidated human checkpoint before continuing.

Use multiple agents only when the user requests them and collaboration is available. The root agent remains the sole writer and state mutator; reviewer agents return evidence-backed notes without editing files.
