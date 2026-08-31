import importlib.util
import json
import os
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

    def test_single_han_character_query_uses_literal_fallback(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第0001章.md").write_text("沈星在旧港等待守门人。", encoding="utf-8")
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        report = story.search_index_report(self.root, "沈", 3, 1.0, 0.0)
        self.assertTrue(report["hits"])
        self.assertIn("沈星", report["hits"][0]["text"])

    def test_relative_reference_source_is_persisted_stably_and_missing_source_preserves_index(self):
        first_cwd = Path(self.temp.name) / "first-cwd"
        second_cwd = Path(self.temp.name) / "second-cwd"
        corpus = first_cwd / "corpus"
        corpus.mkdir(parents=True)
        second_cwd.mkdir()
        (corpus / "设定.md").write_text("星陨钥匙只在北境旧塔出现。", encoding="utf-8")
        original_cwd = Path.cwd()
        try:
            os.chdir(first_cwd)
            first = story.command_index(Namespace(root=str(self.root), source=["corpus"], embeddings="none", model=None, endpoint=None, ann=None))
            manifest = story.load_json(self.root / ".storywork" / "manifest.json")
            self.assertEqual(manifest["index_sources"], [str(corpus.resolve())])
            self.assertEqual(first["files"], 1)

            os.chdir(second_cwd)
            second = story.command_index(Namespace(root=str(self.root), source=None, embeddings=None, model=None, endpoint=None, ann=None))
            self.assertEqual(second["files"], 1)
            self.assertEqual(second["removed_files"], 0)
            self.assertTrue(story.search_index(self.root, "星陨钥匙", 3, 1.0, 0.0))

            (corpus / "设定.md").unlink()
            corpus.rmdir()
            with self.assertRaisesRegex(story.StoryError, "参考源不存在"):
                story.command_index(Namespace(root=str(self.root), source=None, embeddings=None, model=None, endpoint=None, ann=None))
            self.assertTrue(story.search_index(self.root, "星陨钥匙", 3, 1.0, 0.0))
        finally:
            os.chdir(original_cwd)

    def test_missing_fts5_uses_scan_and_semantic_weight_is_reported_and_transferred(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第0001章.md").write_text("守门人把赤铜钥匙交给沈星。", encoding="utf-8")
        original = story.supports_fts5
        story.supports_fts5 = lambda con: False
        try:
            built = story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
            self.assertEqual(built["lexical_backend"], "scan")
            report = story.search_index_report(self.root, "赤铜钥匙", 3, 0.65, 0.35)
        finally:
            story.supports_fts5 = original
        self.assertEqual(report["mode"], "lexical-scan")
        self.assertEqual(report["effective_weights"], {"lexical": 1.0, "semantic": 0.0})
        self.assertTrue(report["warnings"])
        self.assertTrue(report["hits"])
        self.assertAlmostEqual(report["hits"][0]["score"], 1.0)

    def test_missing_declared_fts_table_is_reported_as_unavailable(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第0001章.md").write_text("守门人把赤铜钥匙交给沈星。", encoding="utf-8")
        built = story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        if built["lexical_backend"] != "fts5":
            self.skipTest("当前 Python 没有 FTS5")
        con = story.connect_db(self.root)
        con.execute("DROP TABLE docs_fts")
        con.commit()
        con.close()
        report = story.search_index_report(self.root, "赤铜钥匙", 3, 0.65, 0.35)
        self.assertEqual(report["mode"], "index-unavailable")
        self.assertEqual(report["lexical_backend"], "unavailable")
        self.assertEqual(report["effective_weights"], {"lexical": 0.0, "semantic": 0.0})
        self.assertEqual(report["hits"], [])
        self.assertTrue(any("词法索引表不存在" in warning and "index" in warning for warning in report["warnings"]))

    def test_ollama_query_failure_falls_back_with_warning(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第0001章.md").write_text("沈星在旧港等待守门人。", encoding="utf-8")
        original = story.ollama_embeddings
        story.ollama_embeddings = lambda endpoint, model, texts: [[1.0, 0.0] for _ in texts]
        try:
            story.build_index(self.root, [], "ollama", "fake", "http://invalid", "exact")
            def unavailable(endpoint, model, texts):
                raise story.StoryError("测试端点离线")
            story.ollama_embeddings = unavailable
            report = story.search_index_report(self.root, "旧港", 3, 0.4, 0.6)
        finally:
            story.ollama_embeddings = original
        self.assertEqual(report["effective_weights"], {"lexical": 1.0, "semantic": 0.0})
        self.assertTrue(any("端点离线" in warning for warning in report["warnings"]))
        self.assertTrue(report["hits"])

    def test_cli_keeps_legacy_aliases_and_exposes_clear_names(self):
        cli = story.parser()
        mechanical = cli.parse_args(["mechanical-review", str(self.root), "--session", "s", "--draft", "d.md"])
        legacy_review = cli.parse_args(["review", str(self.root), "--session", "s", "--draft", "d.md"])
        backup = cli.parse_args(["backup", str(self.root), "--archive", "backup.sfs.zip"])
        verify = cli.parse_args(["verify-backup", "--archive", "backup.sfs.zip"])
        revise = cli.parse_args(["revise-begin", str(self.root), "--chapter", "1", "--goal", "修订"])
        self.assertIs(mechanical.func, story.command_review)
        self.assertIs(legacy_review.func, story.command_review)
        self.assertEqual(backup.archive, "backup.sfs.zip")
        self.assertEqual(verify.archive, "backup.sfs.zip")
        self.assertIs(revise.func, story.command_revise_begin)

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
        (self.chapters / "第1章-起点.md").write_text("# 第1章 起点\n\n被修改的版本。", encoding="utf-8")
        repeated = story.command_adopt(Namespace(root=str(self.root), apply=True, confirm="ADOPT"))
        self.assertEqual(repeated["applied"], 0)
        self.assertIn("已有接受记录", repeated["skipped"][0]["reason"])

    def test_chapter_repair_reconciles_legacy_duplicate_records(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        path = self.chapters / "第0003章.md"
        path.write_text("沈星踏入北塔。", encoding="utf-8")
        digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        first = story.append_event(self.root, {"kind": "chapter", "subject": path.name, "predicate": "adopted", "value": digest, "chapter": 3, "source": "legacy"})
        second = story.append_event(self.root, {"kind": "chapter", "subject": path.name, "predicate": "accepted", "value": digest, "chapter": 3, "source": "legacy"})
        story.rebuild_snapshot(self.root)
        self.assertEqual(len(story.accepted_chapter_records(self.root, 3)), 2)
        result = story.command_chapter_repair(Namespace(root=str(self.root), chapter=3, keep=first["id"], confirm="REPAIR-3"))
        self.assertEqual(len(story.accepted_chapter_records(self.root, 3)), 1)
        self.assertEqual(result["retired"], [second["id"]])
        self.assertEqual(len(story.load_json(self.root / ".storywork" / "snapshot.json")["chapter_history"]), 3)

    def test_old_audit_manifest_returns_compatibility_error(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第0001章.md").write_text("审计章节。", encoding="utf-8")
        audit = story.command_audit_pack(Namespace(root=str(self.root), scope="volume", from_chapter=1, to_chapter=1, batch_size=1))
        manifest_path = self.root / ".storywork" / "audits" / audit["audit"] / "manifest.json"
        manifest = story.load_json(manifest_path)
        manifest.pop("memory", None)
        story.write_json(manifest_path, manifest)
        findings = self.root / "findings.json"
        findings.write_text("[]", encoding="utf-8")
        completed = subprocess.run([sys.executable, str(MODULE_PATH), "audit-submit", str(self.root), "--audit", audit["audit"], "--batch", "1", "--findings", str(findings)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        stderr = completed.stderr.decode("utf-8")
        self.assertEqual(completed.returncode, 2, stderr)
        self.assertIn("旧版审计 manifest", stderr)
        self.assertNotIn("PermissionError", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_begin_and_accept_reject_an_already_occupied_chapter_number(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第3章-旧稿.md").write_text("# 第3章\n\n旧稿。", encoding="utf-8")
        story.command_adopt(Namespace(root=str(self.root), apply=True, confirm="ADOPT"))
        with self.assertRaisesRegex(story.StoryError, "第 3 章已有接受记录"):
            story.command_begin(Namespace(root=str(self.root), chapter=3, goal="重写第三章", query="旧稿", limit=2, out=None))

        session = story.command_begin(Namespace(root=str(self.root), chapter=4, goal="写第四章", query="第四章", limit=2, out=None))
        draft = self.root / "draft-4.md"
        draft.write_text("第四章新稿。" * 100, encoding="utf-8")
        story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        (self.chapters / "第4章-并发收编.md").write_text("# 第4章\n\n另一份正文。", encoding="utf-8")
        story.command_adopt(Namespace(root=str(self.root), apply=True, confirm="ADOPT"))
        with self.assertRaisesRegex(story.StoryError, "第 4 章已有接受记录"):
            story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        self.assertFalse((self.chapters / "第0004章.md").exists())

    def test_revise_begin_reconciles_an_edited_accepted_chapter_and_restores_evidence_flow(self):
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        original = story.command_begin(Namespace(root=str(self.root), chapter=5, goal="写第五章", query="第五章", limit=2, out=None))
        draft = self.root / "chapter-5-draft.md"
        draft.write_text("沈星仍在旧港等待。" * 100, encoding="utf-8")
        story.command_review(Namespace(root=str(self.root), session=original["session"], draft=str(draft)))
        accepted = story.command_accept(Namespace(root=str(self.root), session=original["session"], draft=str(draft), confirm=original["session"]))
        chapter = Path(accepted["chapter"])
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n沈星在修订后去了北塔。", encoding="utf-8")
        before = story.command_audit(Namespace(root=str(self.root), setup_age=30))
        self.assertTrue(any("记录后被修改" in item["message"] for item in before["findings"]))

        revision = story.command_revise_begin(Namespace(root=str(self.root), chapter=5, goal="收编修订", query="北塔", limit=2, out=None))
        revision_session = story.load_json(self.root / ".storywork" / "sessions" / revision["session"] / "session.json")
        self.assertTrue(revision_session["revision"]["external_change_detected"])
        story.command_review(Namespace(root=str(self.root), session=revision["session"], draft=str(chapter)))
        revised = story.command_accept(Namespace(root=str(self.root), session=revision["session"], draft=str(chapter), confirm=revision["session"]))
        self.assertEqual(Path(revised["chapter"]), chapter)
        snapshot = story.load_json(self.root / ".storywork" / "snapshot.json")
        self.assertEqual(len(snapshot["chapters"]), 1)
        self.assertEqual(len(snapshot["chapter_history"]), 2)
        self.assertEqual(snapshot["chapters"][0]["predicate"], "revised")
        backups = list((self.root / ".storywork" / "revisions" / "chapter-000005").glob("*.md"))
        self.assertEqual(len(backups), 1)
        archive = self.root / "revision-backup.sfs.zip"
        story.command_backup(Namespace(root=str(self.root), out=str(archive), include_context=False))
        with story.zipfile.ZipFile(archive, "r") as handle:
            self.assertTrue(any(name.startswith("storywork/revisions/chapter-000005/") for name in handle.namelist()))

        events_path = self.root / "revised-events.json"
        events_path.write_text(json.dumps([{"kind": "fact", "subject": "沈星", "predicate": "location", "value": "北塔", "chapter": 5, "evidence": "沈星在修订后去了北塔。"}], ensure_ascii=False), encoding="utf-8")
        story.command_stage_events(Namespace(root=str(self.root), session=revision["session"], events=str(events_path)))
        story.command_approve_events(Namespace(root=str(self.root), session=revision["session"], confirm=revision["session"]))
        self.assertEqual(story.load_json(self.root / ".storywork" / "snapshot.json")["facts"][0]["value"], "北塔")
        after = story.command_audit(Namespace(root=str(self.root), setup_age=30))
        self.assertFalse(any("记录后被修改" in item["message"] for item in after["findings"]))

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
        for weak_evidence in ("。", "赤铜"):
            events_path.write_text(json.dumps([{"kind": "fact", "subject": "沈星", "predicate": "status", "value": "dead", "evidence": weak_evidence, "confidence": 0.99, "risk": "high"}], ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(story.StoryError, "evidence 有效字符不足"):
                story.command_stage_events(Namespace(root=str(self.root), session=session["session"], events=str(events_path)))
        events_path.write_text(json.dumps([{"kind": "fact", "subject": "沈星", "predicate": "status", "value": "dead", "evidence": "沈星明确说过自己永远不会死。", "confidence": 0.99, "risk": "high"}], ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(story.StoryError, "不是已接受正文"):
            story.command_stage_events(Namespace(root=str(self.root), session=session["session"], events=str(events_path)))
        events_path.write_text(json.dumps([{"kind": "fact", "subject": "沈星", "predicate": "location", "value": "北塔", "evidence": "沈星抵达北塔。", "confidence": 0.95}], ensure_ascii=False), encoding="utf-8")
        staged = story.command_stage_events(Namespace(root=str(self.root), session=session["session"], events=str(events_path)))
        self.assertEqual(staged["events"], 1)
        self.assertEqual(len(story.load_events(self.root)), 1)
        with self.assertRaises(story.StoryError):
            story.command_approve_events(Namespace(root=str(self.root), session=session["session"], confirm="wrong"))
        proposal_path = self.root / ".storywork" / "sessions" / session["session"] / "event-proposal.json"
        proposal = story.load_json(proposal_path)
        proposal["events"][0]["evidence"] = "暂存后被替换的虚假引文。"
        story.write_json(proposal_path, proposal)
        with self.assertRaisesRegex(story.StoryError, "不是已接受正文"):
            story.command_approve_events(Namespace(root=str(self.root), session=session["session"], confirm=session["session"]))
        story.command_stage_events(Namespace(root=str(self.root), session=session["session"], events=str(events_path)))
        approved = story.command_approve_events(Namespace(root=str(self.root), session=session["session"], confirm=session["session"]))
        self.assertEqual(approved["applied"], 1)
        self.assertEqual(len(story.load_events(self.root)), 2)

    def test_user_json_supports_windows_encodings_and_cli_errors_are_clean(self):
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="开始", query="开始", limit=2, out=None))
        draft = self.root / "draft.md"
        draft.write_text("沈星抵达北塔。" * 100, encoding="utf-8")
        story.command_review(Namespace(root=str(self.root), session=session["session"], draft=str(draft)))
        story.command_accept(Namespace(root=str(self.root), session=session["session"], draft=str(draft), confirm=session["session"]))
        event_json = json.dumps([{"kind": "fact", "subject": "沈星", "predicate": "location", "value": "北塔", "evidence": "沈星抵达北塔。", "confidence": 0.95}], ensure_ascii=False)

        for name, payload in (
            ("utf8-bom.json", event_json.encode("utf-8-sig")),
            ("utf16le.json", event_json.encode("utf-16-le")),
            ("gb18030.json", event_json.encode("gb18030")),
        ):
            path = self.root / name
            path.write_bytes(payload)
            completed = subprocess.run(
                [sys.executable, str(MODULE_PATH), "stage-events", str(self.root), "--session", session["session"], "--events", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))

        invalid_json = self.root / "invalid.json"
        invalid_json.write_text("这不是 JSON", encoding="utf-8")
        bad_chapter = self.root / "bad-chapter.json"
        bad_chapter.write_text(json.dumps({"chapter": "第一章"}, ensure_ascii=False), encoding="utf-8")
        audit = story.command_audit_pack(Namespace(root=str(self.root), scope="volume", from_chapter=1, to_chapter=1, batch_size=1))
        commands = [
            ["stage-events", str(self.root), "--session", session["session"], "--events", str(invalid_json)],
            ["plan-set", str(self.root), "--chapter", "1", "--plan", str(bad_chapter), "--confirm", "PLAN-1"],
            ["outcome-set", str(self.root), "--session", session["session"], "--outcome", str(invalid_json), "--confirm", session["session"]],
            ["audit-submit", str(self.root), "--audit", audit["audit"], "--batch", "1", "--findings", str(invalid_json)],
        ]
        for command in commands:
            completed = subprocess.run([sys.executable, str(MODULE_PATH), *command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            stderr = completed.stderr.decode("utf-8")
            self.assertEqual(completed.returncode, 2, stderr)
            self.assertTrue(stderr.startswith("error: "), stderr)
            self.assertNotIn("Traceback", stderr)

    def test_main_does_not_mislabel_internal_programming_errors_as_user_input(self):
        original_parser = story.parser

        class BrokenParser:
            def parse_args(self, argv):
                return Namespace(func=lambda args: {}["internal-bug"])

        story.parser = lambda: BrokenParser()
        try:
            with self.assertRaises(KeyError):
                story.main([])
        finally:
            story.parser = original_parser

    def test_begin_out_is_project_relative_and_never_overwrites(self):
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        elsewhere = Path(self.temp.name) / "elsewhere"
        elsewhere.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(elsewhere)
            session = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="开始", query="开始", limit=2, out="上下文/第一章.md"))
        finally:
            os.chdir(previous)
        expected = (self.root / "上下文" / "第一章.md").resolve()
        self.assertEqual(Path(session["context"]), expected)
        self.assertTrue(expected.exists())
        expected.write_text("重要文件，不得覆盖。", encoding="utf-8")
        sessions_dir = self.root / ".storywork" / "sessions"
        before = {path.name for path in sessions_dir.iterdir()}
        with self.assertRaisesRegex(story.StoryError, "拒绝覆盖"):
            story.command_begin(Namespace(root=str(self.root), chapter=2, goal="继续", query="继续", limit=2, out="上下文/第一章.md"))
        self.assertEqual(expected.read_text(encoding="utf-8"), "重要文件，不得覆盖。")
        self.assertEqual({path.name for path in sessions_dir.iterdir()}, before)

    def test_begin_compacts_large_snapshot_and_reports_omissions(self):
        snapshot = {
            "built_at": "test",
            "facts": [{"subject": f"人物{i}", "predicate": "状态", "value": "很长的确认事实" * 12, "chapter": i} for i in range(2000)],
            "setups": [{"id": f"setup-{i}", "subject": f"伏笔{i}", "predicate": "用途", "value": "尚未回收的线索" * 10, "chapter": i, "status": "open"} for i in range(400)],
            "decisions": [{"predicate": f"决定{i}", "value": "继续遵守创作决定" * 10, "chapter": i} for i in range(50)],
            "chapters": [],
        }
        snapshot["facts"][0].update({"subject": "世界", "predicate": "power_rule", "value": "灵脉每百年断一次", "chapter": 1})
        snapshot["facts"][1].update({"subject": "主角", "predicate": "injury", "value": "左手残疾", "chapter": 1})
        story.write_json(self.root / ".storywork" / "snapshot.json", snapshot)
        story.build_index(self.root, [], "none", "bge-m3", "http://127.0.0.1:11434")
        result = story.command_begin(Namespace(root=str(self.root), chapter=1, goal="开始", query="开始", limit=2, out=None))
        context = Path(result["context"]).read_text(encoding="utf-8")
        self.assertLess(len(context), 26000)
        self.assertIn("上下文压缩说明", context)
        self.assertIn("灵脉每百年断一次", context)
        self.assertIn("左手残疾", context)
        self.assertGreater(result["memory_context"]["sections"]["facts"]["omitted"], 0)
        self.assertGreater(result["memory_context"]["sections"]["setups"]["omitted"], 0)
        self.assertIsNotNone(result["memory_context"]["sections"]["facts"]["omitted_chapter_range"])
        self.assertEqual(len(story.load_json(self.root / ".storywork" / "snapshot.json")["facts"]), 2000)

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

    def test_audit_pack_writes_one_bounded_shared_memory_instead_of_copying_snapshot(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        for chapter in range(1, 41):
            (self.chapters / f"第{chapter:04d}章.md").write_text(f"# 第{chapter}章\n\n这一章的短正文。", encoding="utf-8")
        snapshot = story.load_json(self.root / ".storywork" / "snapshot.json")
        snapshot["facts"] = [{"id": f"fact-{i}", "subject": f"人物{i}", "predicate": "状态", "value": "持续有效的事实" * 12, "chapter": i} for i in range(1, 1203)]
        story.write_json(self.root / ".storywork" / "snapshot.json", snapshot)
        pack = story.command_audit_pack(Namespace(root=str(self.root), scope="volume", from_chapter=1, to_chapter=40, batch_size=4))
        memory_path = Path(pack["memory"])
        self.assertLessEqual(len(memory_path.read_text(encoding="utf-8")), 25000)
        batches = sorted((Path(pack["directory"])).glob("batch-*.md"))
        self.assertEqual(len(batches), 10)
        for path in batches:
            text = path.read_text(encoding="utf-8")
            self.assertIn("memory.md", text)
            self.assertNotIn("## 已确认事实", text)
            self.assertLess(len(text), 3000)
        manifest = story.load_json(Path(pack["directory"]) / "manifest.json")
        self.assertEqual(manifest["memory"]["sha256"], pack["memory_sha256"])

    def test_audit_reports_missing_and_orphan_manuscript_files(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        accepted_path = self.chapters / "第1章-已收编.md"
        accepted_path.write_text("# 第1章\n\n已收编正文。", encoding="utf-8")
        story.command_adopt(Namespace(root=str(self.root), apply=True, confirm="ADOPT"))
        accepted_path.unlink()
        orphan_path = self.chapters / "第0019章.md"
        orphan_path.write_text("# 第19章\n\n未收编正文。", encoding="utf-8")
        report = story.command_audit(Namespace(root=str(self.root), setup_age=30))
        messages = [item["message"] for item in report["findings"]]
        self.assertTrue(any("已接受正文文件已丢失" in message and accepted_path.name in message for message in messages))
        self.assertTrue(any("孤儿章节" in message and orphan_path.name in message for message in messages))

    def test_backup_round_trip_verification(self):
        self.chapters.mkdir(parents=True, exist_ok=True)
        (self.chapters / "第1章.md").write_text("# 第1章\n\n正文。", encoding="utf-8")
        story.write_json(self.root / ".storywork" / "pacing.json", {"generated_at": "test", "chapters": []})
        archive = self.root / "backup.sfs.zip"
        result = story.command_backup(Namespace(root=str(self.root), out=str(archive), include_context=False))
        self.assertGreater(result["files"], 0)
        with story.zipfile.ZipFile(archive, "r") as handle:
            self.assertIn("storywork/pacing.json", handle.namelist())
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
        second_plan_path = self.write_plan(chapter=2)
        story.command_plan_set(Namespace(root=str(self.root), chapter=2, plan=str(second_plan_path), confirm="PLAN-2"))
        second_session = story.command_begin(Namespace(root=str(self.root), chapter=2, goal="下一章", query="北塔", limit=2, out=None))
        second_draft = self.root / "second-draft.md"
        second_draft.write_text("沈星抵达北塔后重新观察城门。" * 80, encoding="utf-8")
        story.command_review(Namespace(root=str(self.root), session=second_session["session"], draft=str(second_draft)))
        second_outcome = dict(outcome)
        second_outcome["chapter"] = 2
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
