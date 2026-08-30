# Multi-agent editorial team

Use this mode only when the user explicitly asks for multiple agents and collaboration tools are available. It improves coverage, not truth. All agents share the workspace, so read-only behavior is a workflow contract rather than operating-system isolation.

## Roles

The root agent is the sole writer, integrator, and state mutator. Spawn two or three bounded reviewer agents as needed:

- continuity: canon, chronology, location, injuries, knowledge boundaries, setups and payoffs;
- character-causality: motive, relationship changes, viewpoint knowledge, emotional turns and causal support;
- structure-pacing: plan-to-draft alignment, scene function, escalation, information gain, repeated beats and forward pressure;
- style: only when a style pack is active; it cannot override canon;
- red team: only for death, resurrection, identity revelation, rule changes, major time jumps, or ending-sensitive chapters.

Reviewer agents must not edit the manuscript, plans, `.storywork/`, or indexes. They must not run any `story_workspace.py` command that changes files or state, including `begin`, `review`, `accept`, `record`, `stage-events`, `approve-events`, `rebuild`, `audit-submit`, or `audit-finalize`. They return the output contract only through their final message; only the root agent may persist results.

## Frozen input

The root agent creates one canonical frozen-input manifest containing the session id, context SHA-256, draft SHA-256, frozen plan version and digest, user-constraint digest, open-setup snapshot digest, and role scopes. Compute `input_digest` from the normalized manifest and give the identical manifest and digest to every reviewer. If a report's session, input digest, or draft digest differs, reject it instead of merging it.

Require this output contract:

```json
{
  "schema": "serial-fiction-editorial-note/v1",
  "session": "session-id",
  "input_digest": "sha256",
  "role": "continuity",
  "verdict": "pass|revise|block",
  "findings": [{
    "id": "continuity-001",
    "category": "canon",
    "severity": "error|risk|note|intentional",
    "location": {"chapter": 18, "scene": "s2", "quote": "short evidence"},
    "claim": "problem statement",
    "canon_basis": ["event-or-chapter-reference"],
    "recommendation": "revision intent, not replacement prose",
    "confidence": 0.9,
    "requires_user_decision": false
  }]
}
```

## Integration

The root agent clusters findings by location and category, merges compatible evidence, and records opposing recommendations as conflicts. Do not vote. Resolve by user constraints and ending first, then accepted manuscript and ledger evidence, then plans and inference. Every `error` or `risk` needs a precise source reference and short quote from the frozen input; continuity categories also require `canon_basis`. Reject out-of-scope categories and downgrade unsupported claims to notes.

Manuscript/ledger conflicts, irreversible changes, high-impact disagreements, and every finding with `requires_user_decision: true` go to the user. Do not accept the chapter or alter canon while any such decision remains unresolved.

Only the root agent revises. Re-run deterministic `review` and plan deviation after revision. Reviewer agents never create canon events; accepted-chapter memory extraction remains a separate user-approved step.

Skip this mode for ordinary low-risk chapters, quick drafts, a single mechanical problem, unfrozen inputs, or decisions that are fundamentally the author's taste.

## Qoder definitions

Ready-to-install Qoder Subagent definitions are stored in `adapters/qoder/agents/`:

- `fiction-continuity-reviewer.md`
- `fiction-character-causality-reviewer.md`
- `fiction-structure-pacing-reviewer.md`
- `fiction-style-reviewer.md`
- `fiction-red-team-reviewer.md`

Copy the required definitions to `<novel-root>/.qoder/agents/` for project scope or `~/.qoder/agents/` for user scope, then run `/agents reload`. Keep the definitions read-only. For an ordinary multi-agent pass, invoke continuity, character-causality, and structure-pacing in parallel with the identical frozen manifest. Add style only when a style pack is active, and add red-team only for a high-impact chapter.

The Qoder coordinator remains the sole writer and state mutator. It must verify every returned `session`, `input_digest`, and role before integrating findings. A Subagent definition is an adapter, not permission to skip the user acceptance and canon-update checkpoints.
