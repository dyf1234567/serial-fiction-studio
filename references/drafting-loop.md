# Drafting loop

## Prepare

For a planned chapter, create the lightweight plan described in [planning.md](planning.md) and obtain approval before `begin`. The session freezes that plan version and digest, so later plan revisions cannot silently change the drafting target.

```powershell
python scripts/story_workspace.py begin <root> --chapter 18 --goal "主角从地牢脱身，但不揭露银戒来历" --query "地牢 银戒 守卫" --out context.md
```

The pack separates current facts, open setups, decisions, recent manuscript, and retrieved evidence. Inspect it before drafting.

## Draft and review

Write to a new draft file; never overwrite an accepted chapter. Preserve causal links, viewpoint knowledge, physical state, relationships, setup timing, and forbidden revelations.

```powershell
python scripts/story_workspace.py mechanical-review <root> --session <session-id> --draft <draft-file>
```

`mechanical-review` checks length, forbidden phrases, frozen-plan integrity, plan phrase constraints, and repeated sentences. It is triage, not semantic review or a quality verdict. The old `review` spelling remains a compatibility alias. After it runs, the host model or requested reviewer agents must still read the draft and report continuity conflicts, unsupported motive or voice shifts, premature payoff, missing consequences, repeated beats, and weak forward pressure.

If a frozen plan exists, register the actual scene results and run `deviation` before acceptance. Hard review errors and hard plan-deviation errors block `accept`; soft pacing differences remain reviewable risks.

## Human checkpoint and acceptance

Only after explicit approval:

```powershell
python scripts/story_workspace.py accept <root> --session <session-id> --draft <draft-file> --confirm <session-id>
```

Acceptance copies the draft into the configured chapter directory, appends a chapter event, and rebuilds the snapshot. Record newly established facts, timeline events, setups, and payoffs separately.

After acceptance, extract proposed events from the accepted chapter and follow [memory-extraction.md](memory-extraction.md). Do not skip the approval checkpoint: the model may confuse metaphor, dialogue, plans, flashbacks, or unreliable narration with current canon.

When a style pack is active, use its abstract tendencies and safe examples. Do not reproduce distinctive passages or substitute style evidence for story evidence.
