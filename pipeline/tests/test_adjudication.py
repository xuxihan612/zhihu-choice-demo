from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import adjudicate_gold
import adjudicate_reviews
from aiworks_pipeline.candidates import prepare_candidates
from aiworks_pipeline.common import dump_json, load_json
from aiworks_pipeline.review import build_review_queue
from aiworks_pipeline.schema import schema_for_scenario
from aiworks_pipeline.validation import validate_batch


class AdjudicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = load_json(ROOT / "scenarios" / "coffee.json")
        cls.schema = schema_for_scenario(load_json(ROOT / "schemas" / "extraction-v1.schema.json"), cls.scenario)
        cls.prepared = prepare_candidates(load_json(ROOT.parent / "prototype" / "data" / "raw_candidates.json"), cls.scenario)
        cls.fixture = load_json(ROOT / "tests" / "fixtures" / "coffee-seed-batch.json")
        cls.seed = load_json(ROOT / "tests" / "gold" / "coffee-seed-v1.json")
        cls.accepted = validate_batch(cls.fixture, {x["candidate_id"]: x for x in cls.prepared["kept"]}, cls.scenario, cls.schema, run_metadata={"run_id": "test"})["accepted"]

    def action_for(self, record, decision="accept"):
        action = {"claim_id": record["claim_id"], "candidate_id": record["candidate_id"], "decision": decision, "note": "test"}
        if decision == "modify":
            action["claim"] = {key: copy.deepcopy(record[key]) for key in adjudicate_reviews.CLAIM_FIELDS}
        return action

    def test_review_disagreement_is_queued_and_adjudicated(self):
        run = {"run": {"run_id": "test"}, "accepted": self.accepted, "accepted_claim_count": len(self.accepted), "status_counts": {"extracted": 5}, "item_results": []}
        actions_a = [self.action_for(x) for x in self.accepted]
        actions_b = copy.deepcopy(actions_a)
        actions_b[0]["decision"] = "reject"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "queue"
            build_review_queue(run, self.prepared["kept"], queue)
            dump_json(root / "a.json", {"actions": actions_a})
            dump_json(root / "b.json", {"actions": actions_b})
            args = type("Args", (), {"run": str(root / "run.json"), "queue": str(queue / "review-queue.json"), "reviewer_a": str(root / "a.json"), "reviewer_b": str(root / "b.json"), "output": str(root / "out")})()
            dump_json(args.run, run)
            prepared = adjudicate_reviews.prepare(args)
            self.assertEqual(prepared["agreed_count"], 7)
            self.assertEqual(prepared["divergent_count"], 1)
            run_path = Path(args.run)
            original_run_text = run_path.read_text(encoding="utf-8")
            run_path.write_text(original_run_text + "\n", encoding="utf-8")
            dump_json(root / "adjudication.json", {"adjudicator": "AI test", "actions": [self.action_for(self.accepted[0])]})
            final_args = type("Args", (), {"run": args.run, "agreed": str(root / "out" / "agreed.json"), "adjudications": str(root / "adjudication.json"), "output": str(root / "final")})()
            with self.assertRaises(ValueError):
                adjudicate_reviews.finalize(final_args)
            run_path.write_text(original_run_text, encoding="utf-8")
            report = adjudicate_reviews.finalize(final_args)
            self.assertEqual(report["counts"]["adjudicated"], 1)
            self.assertFalse(report["human_review_completed"])
            self.assertEqual(len(load_json(root / "final" / "final-review-actions.json")["actions"]), 8)

    def test_equivalent_accept_and_modify_are_agreement(self):
        run = {"run": {"run_id": "test"}, "accepted": [self.accepted[0]], "accepted_claim_count": 1, "status_counts": {"extracted": 1}, "item_results": []}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "queue"
            build_review_queue(run, self.prepared["kept"], queue)
            dump_json(root / "a.json", {"actions": [self.action_for(self.accepted[0], "accept")]})
            dump_json(root / "b.json", {"actions": [self.action_for(self.accepted[0], "modify")]})
            dump_json(root / "run.json", run)
            args = type("Args", (), {"run": str(root / "run.json"), "queue": str(queue / "review-queue.json"), "reviewer_a": str(root / "a.json"), "reviewer_b": str(root / "b.json"), "output": str(root / "out")})()
            result = adjudicate_reviews.prepare(args)
            self.assertEqual(result["agreement_rate"], 1.0)

    def test_gold_validator_rejects_nonexact_evidence(self):
        cases = copy.deepcopy(self.seed["cases"])
        cases[0]["claims"][0]["evidence_quote"] = "原文没有这句话。"
        candidates = [next(x for x in self.prepared["kept"] if x["candidate_id"] == case["candidate_id"]) for case in cases]
        with self.assertRaises(ValueError):
            adjudicate_gold.validate_cases(cases, candidates, self.scenario, self.schema, "test")

    def test_gold_manifest_change_blocks_finalize(self):
        seed_cases = copy.deepcopy(self.seed["cases"])
        candidates = [next(x for x in self.prepared["kept"] if x["candidate_id"] == case["candidate_id"]) for case in seed_cases]
        reordered_cases = copy.deepcopy(seed_cases)
        for case in reordered_cases:
            case["claims"].reverse()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "candidates.json"
            dump_json(manifest_path, {"candidates": candidates})
            dump_json(root / "a.json", {"reviewer": "AI-A", "cases": seed_cases})
            dump_json(root / "b.json", {"reviewer": "AI-B", "cases": reordered_cases})
            dump_json(root / "adjudications.json", {"adjudicator": "AI", "cases": []})
            original_manifest_text = manifest_path.read_text(encoding="utf-8")
            prepare_args = type("Args", (), {
                "candidates": str(manifest_path),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
                "seed": str(ROOT / "tests" / "gold" / "coffee-seed-v1.json"),
                "reviewer_a": str(root / "a.json"),
                "reviewer_b": str(root / "b.json"),
                "output": str(root / "out"),
            })()
            prepared = adjudicate_gold.prepare(prepare_args)
            self.assertEqual(prepared["agreed_count"], len(seed_cases))
            self.assertEqual(prepared["divergent_count"], 0)
            manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            finalize_args = type("Args", (), {
                "candidates": str(manifest_path),
                "scenario": str(ROOT / "scenarios" / "coffee.json"),
                "agreed": str(root / "out" / "gold-agreed.json"),
                "adjudications": str(root / "adjudications.json"),
                "output": str(root / "final"),
            })()
            with self.assertRaises(ValueError):
                adjudicate_gold.finalize(finalize_args)
            manifest_path.write_text(original_manifest_text, encoding="utf-8")
            report = adjudicate_gold.finalize(finalize_args)
            self.assertEqual(report["dataset_role"], "ai-assisted-development-set")
            development = load_json(root / "final" / "coffee-ai-development-v1.json")
            self.assertEqual(development["dataset_role"], "ai-assisted-development-set")
            self.assertFalse(development["human_double_review_completed"])
            self.assertFalse(development["test_set_locked"])
            self.assertFalse(development["quality_reporting_eligible"])
            self.assertEqual(development, load_json(root / "final" / "coffee-gold-v1.json"))
            self.assertEqual(report, load_json(root / "final" / "ai-development-review-report.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
