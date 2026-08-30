# Lightweight planning and pacing

Plans are non-canonical authorial intent. They live under `.storywork/plans/`, retain every approved version, and never enter the ledger.

## Chapter plan

Prepare a JSON object with:

- `chapter`, `title`, `goal`, optional `pov` and `arc_ids`;
- `constraints`: `{id, description, level: hard|soft, forbidden_phrase?}`;
- `commitments`: `{id, description, priority: must|should}`;
- `scenes`: scene cards;
- `pacing`: `target_characters`, optional shape, and `climax_scene`.

Each scene requires `id`, `function`, `purpose`, `pov`, `location`, `objective`, `obstacle`, `turn`, `consequence`, `tension` from 1–5, and `information_gain` from 0–3. Optional fields include `irreversible` and `setup_actions`.

Allowed scene functions are `setup`, `escalation`, `reversal`, `payoff`, `aftermath`, `transition`, and `character`.

Present the plan to the user, then save an approved version:

```powershell
python scripts/story_workspace.py plan-set <root> --chapter 18 --plan chapter-18-plan.json --confirm PLAN-18
```

Re-running `plan-set` with identical content is idempotent. Changed content creates a new version and supersedes the previous active version. Existing sessions remain bound to their original plan version and digest.

## Actual outcome and deviation

After `review`, describe what the draft actually contains:

```json
{
  "chapter": 18,
  "actual_characters": 4200,
  "fulfilled_commitments": ["c1"],
  "violated_constraints": [],
  "unplanned_changes": [],
  "scenes": [{
    "plan_scene_ids": ["s1"],
    "function": "reversal",
    "summary": "守卫倒向主角",
    "tension": 4,
    "information_gain": 1,
    "irreversible": true,
    "setup_actions": [],
    "evidence": "沈星越过守卫，踏进北塔。"
  }]
}
```

Register and compare:

```powershell
python scripts/story_workspace.py outcome-set <root> --session <id> --outcome actual.json --confirm <id>
python scripts/story_workspace.py deviation <root> --chapter 18
```

Use multiple `plan_scene_ids` when an actual scene merges planned scenes; repeat a plan id across actual scenes when a planned scene is split. Reordering does not itself constitute failure.

Missing `must` commitments and violated hard constraints are blocking errors. Missing scenes, soft commitments, large tension differences, skipped setup operations, and length drift are risks requiring interpretation. A planned or unplanned irreversible change that was not declared in the plan is a risk requiring an explicit user decision, not an automatic ban on creative deviation. Record deliberate changes under `intentional_deviations`.

`actual_characters` is verified against the reviewed draft; the tool uses the review's measured value rather than trusting a manually supplied count.

Only accepted outcomes contribute to pacing:

```powershell
python scripts/story_workspace.py pacing <root> --window 10
```

The report includes accepted/assessed coverage and only treats a consecutive assessed tail as a trend. It warns about sustained low pressure, prolonged high pressure, or several consecutive chapters without a recorded irreversible change. Low coverage is marked `insufficient_data`. These are prompts for editorial judgment, not genre-independent quality rules.
