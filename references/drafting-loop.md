# Drafting loop

## Prepare

For a planned chapter, create the lightweight plan described in [planning.md](planning.md) and obtain approval before `begin`. The session freezes that plan version and digest, so later plan revisions cannot silently change the drafting target.

```powershell
python scripts/story_workspace.py begin <root> --chapter 18 --goal "主角从地牢脱身，但不揭露银戒来历" --query "地牢 银戒 守卫"
```

The pack separates current facts, open setups, decisions, recent manuscript, and retrieved evidence. Its memory section is a bounded working set; if facts, setups, or decisions are omitted, the pack reports counts and points back to the complete `.storywork/snapshot.json`. Inspect it before drafting and use targeted retrieval or a full audit when an omitted area matters.

Without `--out`, every session receives its own `.storywork/sessions/<session-id>/context.md`; this is the recommended repeated workflow. If a stable visible copy is needed, use a unique name such as `--out contexts/chapter-0018.md`. A relative path is resolved from the novel root. `begin` refuses to overwrite an existing output file and does not create a session when that check fails.

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

## Revise an accepted chapter

Do not edit an accepted chapter and then try to reuse its old session. Start a guarded revision transaction instead:

```powershell
python scripts/story_workspace.py revise-begin <root> --chapter 18 --goal "修正时间错误并保留既有结局"
python scripts/story_workspace.py mechanical-review <root> --session <revision-session> --draft <revised-draft>
python scripts/story_workspace.py accept <root> --session <revision-session> --draft <revised-draft> --confirm <revision-session>
```

`revise-begin` also reconciles a chapter that was edited outside the workflow: it records both the canon digest and the observed file digest. Acceptance fails if the file changes again after the revision session starts. The previous file is preserved under `.storywork/revisions/`, and the new chapter event explicitly supersedes the former version. Re-extract and approve affected canon facts after acceptance; the tool does not guess which earlier facts should be retracted.

如果旧项目的 `audit` 报告同一章存在多个当前接受记录，先按 [audits.md](audits.md) 使用 `chapter-repair` 明确收敛，再开始 `revise-begin`；工具不会替你猜测应保留哪一版。

When a style pack is active, use its abstract tendencies and safe examples. Do not reproduce distinctive passages or substitute style evidence for story evidence.
