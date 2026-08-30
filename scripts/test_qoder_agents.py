from __future__ import annotations

import re
import unittest
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parents[1] / "adapters" / "qoder" / "agents"
EXPECTED_NAMES = {
    "fiction-continuity-reviewer",
    "fiction-character-causality-reviewer",
    "fiction-structure-pacing-reviewer",
    "fiction-style-reviewer",
    "fiction-red-team-reviewer",
}


def frontmatter(text: str) -> str:
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise AssertionError("missing YAML frontmatter")
    return parts[1]


def scalar(meta: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*([^\n]+)$", meta)
    if not match:
        raise AssertionError(f"missing {key}")
    return match.group(1).strip()


def inline_list(meta: str, key: str) -> set[str]:
    value = scalar(meta, key)
    if not (value.startswith("[") and value.endswith("]")):
        raise AssertionError(f"{key} must be an inline list")
    return {item.strip() for item in value[1:-1].split(",") if item.strip()}


class QoderAgentDefinitionsTests(unittest.TestCase):
    def test_expected_read_only_reviewers(self) -> None:
        files = sorted(AGENT_DIR.glob("*.md"))
        self.assertEqual(len(files), len(EXPECTED_NAMES))

        names: set[str] = set()
        for path in files:
            meta = frontmatter(path.read_text(encoding="utf-8"))
            name = scalar(meta, "name")
            self.assertNotIn(name, names)
            names.add(name)
            self.assertEqual(inline_list(meta, "tools"), {"Read", "Grep", "Glob"})
            self.assertTrue(
                {"Write", "Edit", "Bash", "Agent"}.issubset(
                    inline_list(meta, "disallowedTools")
                )
            )
            self.assertEqual(scalar(meta, "permissionMode"), "dontAsk")

        self.assertEqual(names, EXPECTED_NAMES)


if __name__ == "__main__":
    unittest.main()
