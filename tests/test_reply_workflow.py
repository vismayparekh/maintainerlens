import csv
import io
import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import app
from app.llm_client import ReplyDraft
from app.reply_benchmark import summarize_trials
from app.reply_reviews import export_reply_trials, save_reply_trial


class ReplyWorkflowTests(unittest.TestCase):
    @patch("app.api.draft_issue_reply")
    def test_draft_links_only_to_available_candidates(self, draft_reply):
        draft_reply.return_value = ReplyDraft(
            reply="Could you share your package version?",
            checklist=["Confirm the installed version."],
            related_issue_numbers=[99, 34, 34],
        )
        result = TestClient(app).post("/api/issues/draft-reply", json={
            "title": "Empty search results", "body": "A saved search no longer returns results.",
            "related_issues": [{
                "issue_number": 34, "issue_title": "Saved search returns no results",
                "issue_url": "https://github.com/acme/example/issues/34",
            }],
        })

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["reply"].count("https://github.com/acme/example/issues/34"), 1)
        self.assertNotIn("#99", result.json()["reply"])
        self.assertEqual(result.json()["checklist"], ["Confirm the installed version."])
        draft_reply.assert_called_once_with(
            "Empty search results", "A saved search no longer returns results.",
            [(34, "Saved search returns no results")],
        )

    def test_exports_manual_and_assisted_trials_and_reports_timing(self):
        issue = {
            "issue_number": 12, "issue_title": "Empty search results",
            "issue_url": "https://github.com/acme/example/issues/12",
        }
        assisted = {
            **issue, "trial_id": str(uuid4()), "mode": "assisted", "duration_ms": 2500,
            "original_reply": "Could you share your package version?",
            "original_checklist": "- [ ] Confirm the installed version.",
            "reviewed_reply": "Could you share your package version?",
            "reviewed_checklist": "- [ ] Confirm the installed version.",
        }
        manual = {
            **issue, "trial_id": str(uuid4()), "mode": "manual", "duration_ms": 6000,
            "reviewed_reply": "Thanks for reporting this.", "reviewed_checklist": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "reviews.sqlite3"
            with patch("app.api.save_reply_trial", partial(save_reply_trial, database_path=database)), patch(
                "app.api.export_reply_trials", partial(export_reply_trials, database_path=database)
            ):
                client = TestClient(app)
                for trial in (assisted, {**assisted, "duration_ms": 3000}, manual):
                    self.assertEqual(client.post("/api/reply-reviews", json=trial).status_code, 200)
                rejected = client.post("/api/reply-reviews", json={**manual, "mode": "assisted"})
                self.assertEqual(rejected.status_code, 422)
                exported = client.get("/api/reply-reviews/export")

            rows = {row["mode"]: row for row in csv.DictReader(io.StringIO(exported.text))}
            self.assertEqual(len(list(csv.DictReader(io.StringIO(exported.text)))), 2)
            self.assertEqual(rows["assisted"]["original_reply"], assisted["original_reply"])
            self.assertEqual(rows["assisted"]["duration_ms"], "2500")
            self.assertEqual(rows["manual"]["original_reply"], "")
            rows["assisted"]["factual_error"] = "no"
            path = root / "trials.csv"
            with path.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=list(rows["assisted"]))
                writer.writeheader()
                writer.writerows(rows.values())
            report = summarize_trials(path)

        self.assertIn("Median time saved (manual minus assisted): 3.50 s", report)
        self.assertIn("Assisted drafts accepted unchanged: 1/1", report)
        self.assertIn("Factual errors: 0/1 checked", report)
