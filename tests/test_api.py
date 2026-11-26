import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api import app
from app.github_client import GitHubIssue
from app.llm_client import IssueAnalysis
from app.processor import SimilarityMatch


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

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
