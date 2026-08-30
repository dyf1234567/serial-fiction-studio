# Project model

The project is deliberately small and portable:

```text
novel-root/
|-- chapters/                    accepted manuscript files
`-- .storywork/
    |-- manifest.json            title, paths, and retrieval settings
    |-- ledger.jsonl             append-only canon and decision events
    |-- snapshot.json            current reduced state
    |-- library.sqlite3          rebuildable lexical/vector index
    `-- sessions/                draft transactions and review reports
```

Create metadata inside an existing novel without moving its text:

```powershell
python scripts/story_workspace.py init <novel-root> --title "书名" --chapters <chapter-directory>
```

`--chapters` may be outside the project root. The manifest stores a relative path when practical and an absolute path otherwise.

For existing manuscripts, preview detected chapters before adding acceptance records to the new ledger:

```powershell
python scripts/story_workspace.py adopt <root>
python scripts/story_workspace.py adopt <root> --apply --confirm ADOPT
```

This hashes and records existing chapters without moving or modifying them. It does not import old tool state as canon.

## Ledger events

- `fact`: a current assertion such as location, allegiance, injury, possession, identity, or rule.
- `setup`: an unresolved promise, clue, debt, threat, or question.
- `payoff`: resolves a setup by naming its event id in `subject`.
- `timeline`: a dated or ordered occurrence.
- `decision`: an authorial constraint that should not be mistaken for in-world canon.
- `chapter`: normally written by `accept`, recording the committed file and digest.

For `fact`, stable `subject` and `predicate` values form an identity. A newer event supersedes an earlier value. To remove a fact, record value `__RETRACT__`.

For structured continuity checks, use numeric `order` for events within the same chapter and stable predicates:

- characters: `status`, `location`, `age`, `injury`, `allegiance`, `knows`;
- unique objects: use the object as `subject` and `owner` as the predicate;
- movement or dated occurrences: use `timeline`, with the character as `subject` and a stable event predicate.

The audit flags decreasing ages, incompatible values at the same chapter/order, and later activity after a death record. These are candidates for review, not automatic rewrite instructions; flashbacks and deliberate resurrection may be valid.

```powershell
python scripts/story_workspace.py record <root> --kind fact --subject "林澈" --predicate location --value "北塔地牢" --chapter 17
python scripts/story_workspace.py record <root> --kind setup --subject "银戒" --predicate purpose --value "戒内刻字尚未解释" --chapter 9
python scripts/story_workspace.py rebuild <root>
```

For long Chinese text or punctuation that a shell may reinterpret, write the value to a UTF-8 text file and use `--value-file` instead of `--value`:

```powershell
python scripts/story_workspace.py record <root> --kind decision --subject "全书" --predicate ending --value-file ending-constraint.txt
```

Treat imports from older tools as source material, not canon. Index those files or summarize verified facts into new ledger events. This avoids inheriting another tool's hidden assumptions.
