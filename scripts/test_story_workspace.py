import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("story_workspace.py")
SPEC = importlib.util.spec_from_file_location("story_workspace", MODULE_PATH)
story = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(story)


def hnsw_available():
    try:
        import hnswlib  # noqa: F401
        import numpy  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


class StoryWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "novel"
        self.chapters = self.root / "正文"
        story.command_init(Namespace(root=str(self.root), title="测试小说", chapters=str(self.chapters)))

    def tearDown(self):
        self.temp.cleanup()

    def record(self, kind, subject, predicate, value, chapter=1):
        return story.command_record(
            Namespace(root=str(self.root), kind=kind, subject=subject, predicate=predicate, value=value, chapter=chapter, source="test")
        )

    def write_plan(self, chapter=1, forbidden_phrase=None, tension=3):
        plan = {
            "chapter": chapter,
            "title": "计划章",
            "goal": "让沈星抵达北塔",
            "constraints": ([{"id": "keep-secret", "description": "不得提前泄密", "level": "hard", "forbidden_phrase": forbidden_phrase}] if forbidden_phrase else []),
            "commitments": [{"id": "arrive", "description": "沈星抵达北塔", "priority": "must"}],
            "scenes": [{"id": "s1", "function": "escalation", "purpose": "推进主线", "pov": "沈星", "location": "旧港", "objective": "抵达北塔", "obstacle": "守卫阻拦", "turn": "守卫倒戈", "consequence": "道路打开", "tension": tension, "information_gain": 1, "irreversible": False, "setup_actions": []}],
            "pacing": {"target_characters": 1000, "climax_scene": "s1"},
        }
        path = self.root / f"plan-{chapter}.json"
        path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        return path

    def test_append_only_reducer_supersedes_fact_and_tracks_payoff(self):
        self.record("fact", "沈星", "location", "旧港")
        self.record("fact", "沈星", "location", "北塔", 2)
        setup = self.record("setup", "铜钥匙", "purpose", "来历不明", 1)
        self.record("payoff", setup["id"], "resolved_by", "钥匙打开北塔暗门", 3)
        snapshot = json.loads((self.root / ".storywork" / "snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["facts"][0]["value"], "北塔")
        self.assertEqual(snapshot["setups"][0]["status"], "paid")

    def test_cli_value_file_preserves_chinese_punctuation_and_utf8_output(self):
        value_path = self.root / "event-value.txt"
        expected = "单章闭环，同时保留‘母亲失踪与旧车票’作为长篇入口"
        value_path.write_text(expected + "\n", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "record",
                str(self.root),
                "--kind",
                "decision",
                "--subject",
                "作品",
                "--predicate",
                "ending",
                "--value-file",
                str(value_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
        payload = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(payload["value"], expected)

    def test_fts_index_finds_direct_answer(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第0001章.md").write_text("守门人把赤铜钥匙交给了沈星。\n\n黎明前，沈星去了北塔。", encoding="utf-8")
        result = story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        self.assertGreater(result["chunks"], 0)
        hits = story.search_index(self.root, "赤铜钥匙交给谁", 3, 1.0, 0.0)
        self.assertTrue(hits)
        self.assertIn("沈星", hits[0]["text"])
        unchanged = story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        self.assertEqual(unchanged["changed_files"], 0)
        (self.chapters / "第0001章.md").write_text("守门人把赤铜钥匙交给沈星，沈星随后去了北塔。", encoding="utf-8")
        changed = story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        self.assertEqual(changed["changed_files"], 1)

    def test_adopt_previews_then_records_existing_chapters(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第1章-起点.md").write_text("# 第1章 起点\n\n故事开始。", encoding="utf-8")
        preview = story.command_adopt(Namespace(root=str(self.root), apply=False, confirm=None))
        self.assertEqual(len(preview["planned"]), 1)
        self.assertEqual(story.load_events(self.root), [])
        with self.assertRaises(story.StoryError):
            story.command_adopt(Namespace(root=str(self.root), apply=True, confirm="wrong"))
        applied = story.command_adopt(Namespace(root=str(self.root), apply=True, confirm="ADOPT"))
        self.assertEqual(applied["applied"], 1)
        self.assertEqual(story.load_events(self.root)[0]["kind"], "chapter")

    def test_accept_requires_review_and_exact_confirmation(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第0001章.md").write_text("前情。", encoding="utf-8")
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        session = story.command_begin(Namespace(root=str(self.root), chapter=2, goal="继续", query="前情", limit=3, out=None))
        draft = self.root / "draft.md"
        draft.write_text("沈星继续前行。" * 100, encoding="utf-8")
        with self.assertRaises(story.StoryError):
            story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        review = story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        self.assertTrue(review["requires_human_checkpoint"])
        with self.assertRaises(story.StoryError):
            story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm="wrong"))
        accepted = story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        self.assertTrue(Path(accepted["chapter"]).exists())

    def test_review_detects_forbidden_phrase(self):
        self.record("decision", "全书", "forbid_phrase", "银戒真实来历")
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="保持秘密", query="银戒", limit=3, out=None))
        draft = self.root / "draft.md"
        draft.write_text(("本章提前说出银戒真实来历。" * 80), encoding="utf-8")
        review = story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        self.assertIn("forbidden-phrase", {item["code"] for item in review["findings"]})

    def test_extracted_events_require_separate_approval(self):
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="开始", query="开始", limit=2, out=None))
        draft = self.root / "draft.md"
        draft.write_text("沈星抵达北塔。" * 100, encoding="utf-8")
        story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        events_path = self.root / "events.json"
        events_path.write_text(json.dumps([{"kind": "fact", "subject": "沈星", "predicate": "location", "value": "北塔", "evidence": "沈星抵达北塔。", "confidence": 0.95}], ensure_ascii=False), encoding="utf-8")
        staged = story.command_stage_events(Namespace(root=str(self.root), session=session["session"], events=str(events_path)))
        self.assertEqual(staged["events"], 1)
        self.assertEqual(len(story.load_events(self.root)), 1)
        with self.assertRaises(story.StoryError):
            story.command_approve_events(Namespace(root=str(self.root), session=session["session"], confirm="wrong"))
        approved = story.command_approve_events(Namespace(root=str(self.root), session=session["session"], confirm=session["session"]))
        self.assertEqual(approved["applied"], 1)
        self.assertEqual(len(story.load_events(self.root)), 2)

    def test_structured_audit_and_semantic_audit_batches(self):
        self.record("fact", "沈星", "age", "20", 1)
        self.record("fact", "沈星", "age", "19", 2)
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第1章.md").write_text("# 第1章\n\n沈星出发。", encoding="utf-8")
        (self.chapters / "第2章.md").write_text("# 第2章\n\n沈星抵达。", encoding="utf-8")
        report = story.command_audit(Namespace(root=str(self.root), setup_age=30))
        self.assertTrue(any("年龄" in item["message"] for item in report["findings"]))
        pack = story.command_audit_pack(Namespace(root=str(self.root), scope="volume", from_chapter=1, to_chapter=2, batch_size=1))
        for batch in (1, 2):
            findings_path = self.root / f"findings-{batch}.json"
            findings_path.write_text(json.dumps([{"category": "character", "severity": "risk", "chapter": batch, "evidence": "沈星", "message": "需核对人物动机"}], ensure_ascii=False), encoding="utf-8")
            story.command_audit_submit(Namespace(root=str(self.root), audit=pack["audit"], batch=batch, findings=str(findings_path)))
        finalized = story.command_audit_finalize(Namespace(root=str(self.root), audit=pack["audit"]))
        self.assertEqual(finalized["counts"]["risk"], 2)

    def test_backup_round_trip_verification(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第1章.md").write_text("# 第1章\n\n正文。", encoding="utf-8")
        archive = self.root / "backup.sfs.zip"
        result = story.command_backup(Namespace(root=str(self.root), out=str(archive), include_context=False))
        self.assertGreater(result["files"], 0)
        verified = story.command_verify_backup(Namespace(archive=str(archive)))
        self.assertTrue(verified["valid"])

    def test_plan_is_noncanonical_and_session_freezes_version(self):
        plan_path = self.write_plan()
        first = story.command_plan_set(Namespace(root=str(self.root), chapter=1, plan=str(plan_path), confirm="PLAN-1"))
        self.assertEqual(first["version"], 1)
        retry = story.command_plan_set(Namespace(root=str(self.root), chapter=1, plan=str(plan_path), confirm="PLAN-1"))
        self.assertEqual(retry["status"], "already-active")
        self.assertEqual(retry["version"], 1)
        self.assertEqual(story.load_events(self.root), [])
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="执行计划", query="北塔", limit=2, out=None))
        session_data = story.load_json(self.root / ".storywork" / "sessions" / session["session"] / "session.json")
        self.assertEqual(session_data["plan_version"], 1)
        context = Path(session["context"]).read_text(encoding="utf-8")
        self.assertIn("已批准计划 v1", context)
        self.assertIn("信息增量=1", context)
        self.assertIn("节奏目标", context)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["goal"] = "改为留在旧港"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        second = story.command_plan_set(Namespace(root=str(self.root), chapter=1, plan=str(plan_path), confirm="PLAN-1"))
        self.assertEqual(second["version"], 2)
        session_data = story.load_json(self.root / ".storywork" / "sessions" / session["session"] / "session.json")
        self.assertEqual(session_data["plan_version"], 1)
        draft = self.root / "v1-draft.md"
        draft.write_text("沈星离开旧港并抵达北塔。" * 80, encoding="utf-8")
        review = story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        self.assertFalse(any(item.get("code") == "plan-mutated" for item in review["findings"]))
        self.assertEqual(story.load_events(self.root), [])

    def test_plan_outcome_deviation_and_pacing_use_accepted_actuals(self):
        plan_path = self.write_plan()
        story.command_plan_set(Namespace(root=str(self.root), chapter=1, plan=str(plan_path), confirm="PLAN-1"))
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="执行计划", query="北塔", limit=2, out=None))
        draft = self.root / "draft-plan.md"
        draft.write_text("沈星越过守卫，最终抵达北塔。" * 80, encoding="utf-8")
        story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        outcome = {"chapter": 1, "actual_characters": 1000, "fulfilled_commitments": ["arrive"], "violated_constraints": [], "unplanned_changes": [], "scenes": [{"plan_scene_id": "s1", "function": "escalation", "summary": "沈星抵达北塔", "tension": 3, "information_gain": 1, "irreversible": False, "setup_actions": []}]}
        outcome_path = self.root / "outcome.json"
        outcome_path.write_text(json.dumps(outcome, ensure_ascii=False), encoding="utf-8")
        story.command_outcome_set(Namespace(root=str(self.root), session=session["session"], outcome=str(outcome_path), confirm=session["session"]))
        before = story.command_pacing(Namespace(root=str(self.root), window=10))
        self.assertEqual(before["chapters"], [])
        deviation = story.command_deviation(Namespace(root=str(self.root), chapter=1))
        self.assertFalse(any(item["severity"] == "error" for item in deviation["findings"]))
        story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        after = story.command_pacing(Namespace(root=str(self.root), window=10))
        self.assertEqual([item["chapter"] for item in after["chapters"]], [1])
        self.assertEqual(after["coverage"], 1.0)
        second_session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="备选修订", query="北塔", limit=2, out=None))
        second_draft = self.root / "second-draft.md"
        second_draft.write_text("沈星抵达北塔后重新观察城门。" * 80, encoding="utf-8")
        story.command_review(Namespace(root=str(self.root), session=second_session["session"], draft=str(second_draft)))
        second_outcome = dict(outcome)
        second_outcome["actual_characters"] = 1200
        outcome_path.write_text(json.dumps(second_outcome, ensure_ascii=False), encoding="utf-8")
        story.command_outcome_set(Namespace(root=str(self.root), session=second_session["session"], outcome=str(outcome_path), confirm=second_session["session"]))
        still_accepted = story.command_pacing(Namespace(root=str(self.root), window=10))
        self.assertEqual([item["chapter"] for item in still_accepted["chapters"]], [1])

    def test_planned_chapter_requires_outcome_and_detects_late_plan_mutation(self):
        plan_path = self.write_plan()
        story.command_plan_set(Namespace(root=str(self.root), chapter=1, plan=str(plan_path), confirm="PLAN-1"))
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="执行计划", query="北塔", limit=2, out=None))
        draft = self.root / "planned-no-outcome.md"
        draft.write_text("沈星越过守卫并抵达北塔。" * 80, encoding="utf-8")
        story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        with self.assertRaises(story.StoryError):
            story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        history_path = story.plan_path(self.root, 1)
        history = story.load_json(history_path)
        history["versions"][0]["goal"] = "被原地篡改的目标"
        story.write_json(history_path, history)
        with self.assertRaisesRegex(story.StoryError, "原地修改"):
            story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        self.assertFalse((self.chapters / "第0001章.md").exists())

    def test_hard_plan_constraint_blocks_accept(self):
        plan_path = self.write_plan(forbidden_phrase="王座秘密")
        story.command_plan_set(Namespace(root=str(self.root), chapter=1, plan=str(plan_path), confirm="PLAN-1"))
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="保持秘密", query="秘密", limit=2, out=None))
        draft = self.root / "bad-plan.md"
        draft.write_text("本章泄露王座秘密。" * 100, encoding="utf-8")
        review = story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        self.assertTrue(any(item["severity"] == "error" for item in review["findings"]))
        with self.assertRaises(story.StoryError):
            story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        self.assertFalse((self.chapters / "第0001章.md").exists())
        self.assertFalse(any(item.get("kind") == "chapter" for item in story.load_events(self.root)))

    @unittest.skipUnless(hnsw_available(), "optional hnswlib is not loadable")
    def test_hnsw_backend_builds_and_queries(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第1章.md").write_text("赤铜钥匙由沈星保管。", encoding="utf-8")
        original = story.ollama_embeddings

        def fake_embeddings(endpoint, model, texts):
            return [[1.0, 0.0, 0.0] if "赤铜" in text else [0.0, 1.0, 0.0] for text in texts]

        story.ollama_embeddings = fake_embeddings
        try:
            result = story.build_index(self.root, [], "ollama", "fake", "http://invalid", "hnsw")
            self.assertEqual(result["ann"], "hnsw")
            hits = story.search_index(self.root, "赤铜钥匙", 2, 0.0, 1.0)
            self.assertTrue(hits)
            self.assertIn("沈星", hits[0]["text"])
        finally:
            story.ollama_embeddings = original


if __name__ == "__main__":
    unittest.main()
