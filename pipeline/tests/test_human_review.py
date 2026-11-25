from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import human_gold_review
from aiworks_pipeline.common import dump_json, load_json
from aiworks_pipeline.human_review import INDEPENDENCE_STATEMENT, REVIEW_KIND, build_human_gold_templates


class HumanReviewTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = load_json(ROOT / "scenarios" / "coffee.json")
        cls.candidates = load_json(ROOT / "review" / "gold-v1" / "gold-candidates.json")["candidates"]
        cls.seed = load_json(ROOT / "tests" / "gold" / "coffee-seed-v1.json")["cases"]
        cls.candidate_map = {x["candidate_id"]: x for x in cls.candidates}

    def _annotation_payload(self, slot: str, reviewer: str, cases: list[dict]) -> dict:
        signed_at = "2026-11-25T00:00:00+00:00"
        return {
            "review_kind": REVIEW_KIND,
            "human_review": True,
            "reviewer_slot": slot,
            "reviewer": reviewer,
            "scenario_id": self.scenario["id"],
            "independence_statement": INDEPENDENCE_STATEMENT,
            "attestation": {"independent_completion": True, "source_only": True, "signed_at": signed_at},
            "exported_at": signed_at,
            "cases": copy.deepcopy(cases),
        }

    def test_templates_are_blank_source_only_and_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = build_human_gold_templates(self.candidates, self.scenario, root)
            self.assertEqual(result["candidate_count"], 50)
            self.assertFalse(result["ai_annotations_included"])
            self.assertEqual({x["slot"] for x in result["files"]}, {"A", "B"})
            slots = []
            for slot in ("a", "b"):
                payload = load_json(root / f"reviewer-{slot}" / f"reviewer-{slot}.template.json")
                self.assertEqual(len(payload["cases"]), 50)
                self.assertTrue(payload["human_review"])
                self.assertEqual(payload["reviewer"], "")
                self.assertTrue(all(x["status"] is None and x["claims"] == [] for x in payload["cases"]))
                self.assertTrue(all(set(x) == {"candidate_id", "status", "claims", "source", "content_text"} for x in payload["cases"]))
                html = (root / f"reviewer-{slot}" / f"reviewer-{slot}.html").read_text(encoding="utf-8")
                match = re.search(r'<script id="review-data" type="application/json">(.*?)</script>', html, re.S)
                self.assertIsNotNone(match)
                bundle = json.loads(match.group(1))
                self.assertEqual(bundle["template"]["reviewer_slot"], slot.upper())
                self.assertTrue(all(x["status"] is None and x["claims"] == [] for x in bundle["template"]["cases"]))
                self.assertNotIn('"reviewer_a"', html)
                self.assertNotIn('"reviewer_b"', html)
                self.assertIn("zhihu-gold-human-review-${slot}-v1", html)
                self.assertIn("attestation:{independent_completion:true,source_only:true,signed_at:signedAt}", html)
                self.assertIn(self.candidates[0]["content_text"][:80], bundle["template"]["cases"][0]["content_text"])
                slots.append(bundle["template"]["reviewer_slot"])
            self.assertNotEqual(slots[0], slots[1])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required to syntax-check the offline workbench")
    def test_workbench_javascript_has_valid_syntax(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_human_gold_templates(self.candidates[:2], self.scenario, root)
            for slot in ("a", "b"):
                html = (root / f"reviewer-{slot}" / f"reviewer-{slot}.html").read_text(encoding="utf-8")
                scripts = re.findall(r"<script(?: [^>]*)?>([\s\S]*?)</script>", html)
                script_path = root / f"reviewer-{slot}.js"
                script_path.write_text(scripts[-1], encoding="utf-8")
                checked = subprocess.run(["node", "--check", str(script_path)], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_prepare_requires_distinct_named_human_reviewers(self):
        candidates = [self.candidate_map[x["candidate_id"]] for x in self.seed]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dump_json(root / "candidates.json", {"candidates": candidates})
            dump_json(root / "a.json", self._annotation_payload("A", "复核人甲", self.seed))
            dump_json(root / "b.json", self._annotation_payload("B", "复核人甲", self.seed))
            args = type("Args", (), {
                "candidates": str(root / "candidates.json"),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
                "reviewer_a": str(root / "a.json"),
                "reviewer_b": str(root / "b.json"),
                "output": str(root / "out"),
            })()
            with self.assertRaises(ValueError):
                human_gold_review.command_prepare(args)
            dump_json(root / "b.json", self._annotation_payload("B", "复核人乙", self.seed))
            report = human_gold_review.command_prepare(args)
            self.assertEqual(report["reviewer_types"], {"reviewer_a": "human", "reviewer_b": "human"})
            self.assertEqual(report["agreed_count"], len(self.seed))
            self.assertEqual(report["divergent_count"], 0)
            self.assertFalse(report["human_double_review_completed"])
            self.assertFalse(report["test_set_locked"])
            self.assertFalse(report["quality_reporting_eligible"])

    def test_ai_or_unsigned_payload_cannot_be_submitted_as_human_review(self):
        candidates = [self.candidate_map[x["candidate_id"]] for x in self.seed]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = self._annotation_payload("A", "复核人甲", self.seed)
            payload["human_review"] = False
            dump_json(root / "a.json", payload)
            args = type("Args", (), {
                "annotation": str(root / "a.json"),
                "slot": "a",
                "candidates": str(root / "candidates.json"),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
            })()
            dump_json(args.candidates, {"candidates": candidates})
            with self.assertRaises(ValueError):
                human_gold_review.command_check(args)

    def test_divergence_queue_can_seed_a_blank_human_adjudicator_template(self):
        candidates = [self.candidate_map[x["candidate_id"]] for x in self.seed]
        cases_b = copy.deepcopy(self.seed)
        cases_b[0]["claims"][0]["claim"] += "。"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dump_json(root / "candidates.json", {"candidates": candidates})
            dump_json(root / "a.json", self._annotation_payload("A", "复核人甲", self.seed))
            dump_json(root / "b.json", self._annotation_payload("B", "复核人乙", cases_b))
            prepare_args = type("Args", (), {
                "candidates": str(root / "candidates.json"),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
                "reviewer_a": str(root / "a.json"),
                "reviewer_b": str(root / "b.json"),
                "output": str(root / "out"),
            })()
            report = human_gold_review.command_prepare(prepare_args)
            self.assertEqual(report["divergent_count"], 1)
            adjudication_args = type("Args", (), {
                "queue": str(root / "out" / "human-adjudication-queue.json"),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
                "output": str(root / "adjudicator.template.json"),
            })()
            result = human_gold_review.command_adjudication_template(adjudication_args)
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["adjudicator"], "")
            self.assertEqual(result["signed_at"], "")
            self.assertIsNone(result["cases"][0]["status"])
            self.assertEqual(result["cases"][0]["claims"], [])
            self.assertEqual(result["cases"][0]["adjudication_note"], "")
            self.assertIn("reviewer_a", result["cases"][0])
            self.assertIn("reviewer_b", result["cases"][0])

    def test_signed_human_adjudication_can_lock_the_gold_set(self):
        seed_case = self.seed[0]
        cases_a = []
        cases_b = []
        for candidate in self.candidates:
            if candidate["candidate_id"] == seed_case["candidate_id"]:
                cases_a.append(copy.deepcopy(seed_case))
                cases_b.append({"candidate_id": candidate["candidate_id"], "status": "irrelevant", "claims": []})
            else:
                empty = {"candidate_id": candidate["candidate_id"], "status": "insufficient_evidence", "claims": []}
                cases_a.append(copy.deepcopy(empty))
                cases_b.append(copy.deepcopy(empty))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dump_json(root / "candidates.json", {"candidates": self.candidates})
            dump_json(root / "a.json", self._annotation_payload("A", "复核人甲", cases_a))
            dump_json(root / "b.json", self._annotation_payload("B", "复核人乙", cases_b))
            prepare_args = type("Args", (), {
                "candidates": str(root / "candidates.json"),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
                "reviewer_a": str(root / "a.json"),
                "reviewer_b": str(root / "b.json"),
                "output": str(root / "out"),
            })()
            human_gold_review.command_prepare(prepare_args)
            template_args = type("Args", (), {
                "queue": str(root / "out" / "human-adjudication-queue.json"),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
                "output": str(root / "adjudicator.json"),
            })()
            adjudication = human_gold_review.command_adjudication_template(template_args)
            adjudication["adjudicator"] = "复核人丙"
            adjudication["signed_at"] = "2026-11-25T01:00:00+00:00"
            adjudication["cases"][0]["status"] = seed_case["status"]
            adjudication["cases"][0]["claims"] = copy.deepcopy(seed_case["claims"])
            adjudication["cases"][0]["adjudication_note"] = "对照完整正文后采用复核人乙的表述。"
            dump_json(root / "adjudicator.json", adjudication)
            check_args = type("Args", (), {
                "queue": str(root / "out" / "human-adjudication-queue.json"),
                "adjudication": str(root / "adjudicator.json"),
                "candidates": str(root / "candidates.json"),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
            })()
            checked = human_gold_review.command_check_adjudication(check_args)
            self.assertTrue(checked["valid"])
            finalize_args = type("Args", (), {
                "candidates": str(root / "candidates.json"),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
                "reviewer_a": str(root / "a.json"),
                "reviewer_b": str(root / "b.json"),
                "agreed": str(root / "out" / "human-agreed.json"),
                "adjudications": str(root / "adjudicator.json"),
                "lock_approved_by": "项目负责人",
                "lock_note": "两份真人独立标注与分歧裁决均已签署，锁定测试集。",
                "output": str(root / "final"),
            })()
            report = human_gold_review.command_finalize(finalize_args)
            self.assertEqual(report["candidate_count"], 50)
            self.assertTrue(report["human_double_review_completed"])
            self.assertTrue(report["test_set_locked"])
            self.assertTrue(report["quality_reporting_eligible"])
            gold = load_json(root / "final" / "coffee-gold-human-v1.json")
            self.assertEqual(gold["review_summary"]["reviewer_types"], {"reviewer_a": "human", "reviewer_b": "human", "adjudicator": "human"})
            self.assertEqual(gold["lock_signoff"]["approved_by"], "项目负责人")
            adjudication["signed_at"] = ""
            dump_json(root / "adjudicator.json", adjudication)
            with self.assertRaises(ValueError):
                human_gold_review.command_check_adjudication(check_args)
            adjudication["signed_at"] = "2026-11-25T01:00:00+00:00"
            dump_json(root / "adjudicator.json", adjudication)
            manifest = root / "candidates.json"
            manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                human_gold_review.command_finalize(finalize_args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
