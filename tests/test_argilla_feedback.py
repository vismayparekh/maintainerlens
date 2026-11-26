import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.argilla_feedback import _record_fields, export_reviews


class ArgillaFeedbackTests(unittest.TestCase):
    def test_import_shape_excludes_assistant_grades(self):
        case = {"repository": "acme/example", "number": 12, "focus": "documentation"}
        captured = {
            "case": case,
            "captured_at_utc": "2026-11-26T00:00:00Z",
            "details": {
                "pull_request": {
                    "number": 12, "title": "Document exports", "body": "Add an export example.",
                    "url": "https://github.com/acme/example/pull/12", "status": "open",
                    "author": None, "updated_at": "2026-11-26T00:00:00Z",
                },
                "base_branch": "main", "head_branch": "docs", "changed_files": 1,
                "additions": 4, "deletions": 0,
                "files": [{"path": "README.md", "status": "modified", "additions": 4, "deletions": 0}],
                "issue_references": [],
            },
        }
        generated = {
            "run_id": "run-one", "case": case, "model": "example-model", "elapsed_ms": 20,
            "brief": {"summary": "Documents exports.", "checklist": ["Verify example output."]},
        }
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.json"
            run = Path(directory) / "run.jsonl"
            snapshot.write_text(json.dumps([captured]), encoding="utf-8")
            run.write_text(json.dumps(generated) + "\n", encoding="utf-8")
            records = _record_fields(snapshot, run)

        record = records["run-one:acme/example:12"]
        self.assertEqual(set(record), {"source", "description", "files", "summary", "checklist"})
        self.assertIn("README.md", record["files"])
        self.assertIn("Verify example output.", record["checklist"])

    def test_exports_submitted_scores_and_keeps_zero(self):
        fields = {"change_accuracy": 2, "author_intent": 0, "actionable_checks": 1,
                  "corrected_checklist": "Check both examples."}
        responses = [
            SimpleNamespace(question_name=name, value=value, user_id="reviewer-one", status="submitted")
            for name, value in fields.items()
        ]
        responses.append(SimpleNamespace(
            question_name="author_intent", value=2, user_id="draft-reviewer", status="draft",
        ))
        dataset = SimpleNamespace(records=Mock(return_value=[
            SimpleNamespace(id="run-one:acme/example:12", responses=responses),
        ]))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "grades.csv"
            self.assertEqual(export_reviews(dataset, output), 1)
            with output.open(newline="", encoding="utf-8") as file:
                review = next(csv.DictReader(file))

        self.assertEqual(review["reviewer_id"], "reviewer-one")
        self.assertEqual(review["author_intent"], "0")
        self.assertEqual(review["corrected_checklist"], "Check both examples.")
