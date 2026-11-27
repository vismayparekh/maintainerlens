import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from app.api import app
from app.github_client import GitHubIssue
from app.llm_client import IssueAnalysis
from app.processor import SimilarityMatch


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    @patch("app.api.fetch_repository_labels")
    @patch("app.api.fetch_closed_issues", return_value=[])
    @patch("app.api.fetch_issues")
    def test_suggests_actual_labels_once_per_inbox_and_handles_catalog_failure(
        self, fetch_issues: Mock, fetch_closed_issues: Mock, fetch_labels: Mock
    ) -> None:
        fetch_issues.return_value = [
            GitHubIssue(number, "CSV parser crashes", "", labels, f"https://github.com/acme/project/issues/{number}")
            for number, labels in ((7, ()), (8, ("Type: Bug",)))
        ]
        fetch_labels.return_value = ["Type: Bug", "Defect", "IO CSV", "Security", "good first issue"]
        params = {"repository": "acme/project", "include_label_suggestions": True}
        self.client.get("/api/issues", params={"repository": "acme/project"})
        fetch_labels.assert_not_called()
        response = self.client.get("/api/issues", params=params)
        fetch_labels.assert_called_once_with("acme/project")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["label_suggestions_status"], "available")
        first, second = response.json()["issues"]
        self.assertEqual([row["name"] for row in first["suggested_labels"]], ["Type: Bug", "IO CSV"])
        self.assertEqual([row["name"] for row in second["suggested_labels"]], ["IO CSV"])
        self.assertTrue(all(row["reason"] for row in first["suggested_labels"]))

        fetch_labels.side_effect = requests.ConnectionError("unavailable")
        response = self.client.get("/api/issues", params=params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["label_suggestions_status"], "unavailable")
        self.assertEqual(len(response.json()["issues"]), 2)
        self.assertEqual(response.json()["issues"][0]["suggested_labels"], [])

    @patch("app.api.fetch_issue_by_number")
    def test_loads_a_linked_issue_without_loading_inbox_history(self, fetch_issue: Mock) -> None:
        fetch_issue.return_value = GitHubIssue(
            12, "Crash on startup", "The application crashes.", ("bug",),
            "https://github.com/acme/project/issues/12",
        )
        with patch("app.api.fetch_issues") as inbox, patch("app.api.fetch_closed_issues") as history:
            response = self.client.get("/api/issues/12", params={"repository": "acme/project"})
        fetch_issue.assert_called_once_with("acme/project", 12)
        inbox.assert_not_called()
        history.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["number"], 12)
        self.assertEqual(response.json()["similar_issues"], [])
        self.assertEqual(response.json()["severity"]["level"], "high")

    @patch("app.api.fetch_issue_by_number")
    def test_missing_linked_issue_returns_not_found(self, fetch_issue: Mock) -> None:
        missing = requests.Response()
        missing.status_code = 404
        fetch_issue.side_effect = requests.HTTPError(response=missing)
        response = self.client.get("/api/issues/12", params={"repository": "acme/project"})
        self.assertEqual(response.status_code, 404)

    @patch("app.api.find_similar_issues")
    @patch("app.api.fetch_closed_issues")
    @patch("app.api.fetch_issues")
    def test_lists_open_issues_with_closed_similar_matches(
        self,
        fetch_issues: Mock,
        fetch_closed_issues: Mock,
        find_similar_issues: Mock,
    ) -> None:
        open_issue = GitHubIssue(
            12,
            "Crash on startup",
            "The application crashes when launched.",
            ("bug",),
            "https://github.com/acme/project/issues/12",
        )
        closed_issue = GitHubIssue(
            8,
            "Earlier startup crash",
            "The application previously crashed on startup.",
            (),
            "https://github.com/acme/project/issues/8",
        )
        fetch_issues.return_value = [open_issue]
        fetch_closed_issues.return_value = [closed_issue]
        find_similar_issues.return_value = {
            12: [SimilarityMatch(closed_issue, 0.75)],
            8: [SimilarityMatch(open_issue, 0.75)],
        }

        response = self.client.get(
            "/api/issues",
            params={"repository": "acme/project", "limit": 1},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["historical_issue_count"], 1)
        self.assertEqual(payload["issues"][0]["category"], "Bug")
        self.assertEqual(
            payload["issues"][0]["similar_issues"][0]["number"],
            closed_issue.number,
        )
        self.assertTrue(payload["issues"][0]["similar_issues"][0]["is_closed"])
        self.assertEqual(payload["issues"][0]["similar_issues"][0]["method"], "text")

    @patch.dict(os.environ, {"MAINTAINERLENS_SEMANTIC_SEARCH": "1"})
    @patch("app.api.find_semantic_fallbacks")
    @patch("app.api.find_similar_issues")
    @patch("app.api.fetch_closed_issues")
    @patch("app.api.fetch_issues")
    def test_defers_semantic_search_to_same_batch_without_overwriting_text_matches(
        self,
        fetch_issues: Mock,
        fetch_closed_issues: Mock,
        find_text: Mock,
        find_semantic: Mock,
    ) -> None:
        first, second, closed_issue = [
            GitHubIssue(
                number, f"Issue {number}", "Example details", (),
                f"https://github.com/acme/project/issues/{number}",
            )
            for number in (11, 12, 8)
        ]
        fetch_issues.return_value = [first, second]
        fetch_closed_issues.return_value = [closed_issue]
        find_text.return_value = {11: [], 12: [SimilarityMatch(closed_issue, 0.4)], 8: []}
        find_semantic.return_value = {11: [SimilarityMatch(closed_issue, 0.92)]}

        initial = self.client.get("/api/issues", params={"repository": "acme/project"})

        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["issues"][0]["similar_issues"], [])
        self.assertEqual(initial.json()["issues"][1]["similar_issues"][0]["method"], "text")
        find_semantic.assert_not_called()

        related = self.client.get(f"/api/issues/related/{initial.json()['related_lookup_id']}")

        self.assertEqual(related.status_code, 200)
        self.assertEqual(set(related.json()), {"11"})
        match = related.json()["11"][0]
        self.assertEqual(match["method"], "semantic")
        self.assertEqual(match["number"], 8)
        self.assertTrue(match["is_closed"])
        self.assertEqual(find_semantic.call_args.args, ((first, second, closed_issue),))
        self.assertEqual(find_semantic.call_args.kwargs["issue_numbers"], {11})
        fetch_issues.assert_called_once()
        fetch_closed_issues.assert_called_once()

    def test_missing_lookup_requires_refetch(self) -> None:
        related = self.client.get("/api/issues/related/unknown-batch")

        self.assertEqual(related.status_code, 404)

    @patch("app.api.analyze_issue")
    def test_analyzes_issue_without_exposing_provider_details(
        self, analyze_issue: Mock
    ) -> None:
        analyze_issue.return_value = IssueAnalysis(
            summary="The app crashes on startup.",
            category="Bug",
            rationale="The issue reports broken startup behavior.",
            summary_truncated=True,
        )

        response = self.client.post(
            "/api/issues/analyze",
            json={
                "title": "Crash on startup",
                "body": "The application crashes when launched.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["category"], "Bug")
        self.assertTrue(response.json()["summary_truncated"])
        analyze_issue.assert_called_once_with(
            "Crash on startup",
            "The application crashes when launched.",
        )

    @patch("app.api.save_review")
    def test_saves_review_without_sending_issue_body(
        self, save_review: Mock
    ) -> None:
        response = self.client.post(
            "/api/reviews",
            json={
                "issue_number": 12,
                "issue_title": "Crash on startup",
                "issue_url": "https://github.com/acme/project/issues/12",
                "ai_summary": "The app fails.",
                "ai_category": "Question",
                "reviewed_summary": "The app crashes during startup.",
                "reviewed_category": "Bug",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Review saved locally.")
        issue = save_review.call_args.args[0]
        self.assertEqual(issue.body, "")
        self.assertEqual(
            save_review.call_args.args[2:],
            ("Question", "The app crashes during startup.", "Bug"),
        )

    def test_exports_local_reviews_as_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.csv"
            path.write_text(
                "issue_url,reviewed_category\n"
                "https://github.com/acme/project/issues/12,Bug\n",
                encoding="utf-8",
            )
            with patch("app.api.export_reviews_csv", return_value=path):
                response = self.client.get("/api/reviews/export")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("reviewed_category", response.text)


if __name__ == "__main__":
    unittest.main()
