import unittest
from unittest.mock import Mock, patch

from app.app import (
    download_local_reviews,
    generate_ai_analysis,
    load_issues,
    render_selected_issue,
    save_issue_review,
)
from app.github_client import GitHubIssue
from app.llm_client import (
    IssueAnalysis,
    IssueAnalysisNotConfiguredError,
)


class LoadIssuesTests(unittest.TestCase):
    @patch("app.app.fetch_closed_issues")
    @patch("app.app.fetch_issues")
    def test_handles_repository_without_open_issues(
        self, fetch_issues: Mock, fetch_closed_issues: Mock
    ) -> None:
        fetch_issues.return_value = []

        (
            issue_table,
            status,
            details_state,
            selected_title,
            selected_body,
            selected_issue,
            ai_analysis,
            analyze_button,
            review_summary,
            review_category,
            ai_suggestion,
            save_review_button,
            review_status,
        ) = load_issues("acme/project", 10)

        self.assertEqual(issue_table["samples"], [])
        self.assertEqual(status, "No open issues found for this repository.")
        self.assertEqual(details_state, [])
        self.assertEqual(selected_title, "")
        self.assertEqual(selected_body, "No open issues found for this repository.")
        self.assertIsNone(selected_issue)
        self.assertIn("Fetch issues", ai_analysis)
        self.assertFalse(analyze_button["interactive"])
        self.assertEqual(review_summary, "")
        self.assertIsNone(review_category)
        self.assertIsNone(ai_suggestion)
        self.assertFalse(save_review_button["interactive"])
        self.assertEqual(review_status, "")
        fetch_closed_issues.assert_not_called()

    @patch("app.app.fetch_closed_issues")
    @patch("app.app.fetch_issues")
    def test_includes_category_summary_and_similarity_matches(
        self, fetch_issues: Mock, fetch_closed_issues: Mock
    ) -> None:
        fetch_issues.return_value = [
            GitHubIssue(
                number=12,
                title="First issue",
                body="The app crashes. It happens on startup.",
                labels=("bug",),
                url="https://github.com/acme/project/issues/12",
            ),
            GitHubIssue(
                number=13,
                title="Related issue",
                body="The app crashes. It happens on startup.",
                labels=(),
                url="https://github.com/acme/project/issues/13",
            ),
        ]
        fetch_closed_issues.return_value = []

        (
            issue_table,
            status,
            issue_details,
            selected_title,
            selected_body,
            selected_issue,
            ai_analysis,
            analyze_button,
            review_summary,
            review_category,
            ai_suggestion,
            save_review_button,
            review_status,
        ) = load_issues("acme/project", 10)

        self.assertEqual(
            issue_table["samples"][0],
            [
                12,
                "Bug",
                "First issue",
            ],
        )
        self.assertEqual(
            status,
            "Loaded 2 open issue(s); compared against 0 historical issue(s).",
        )
        self.assertIn(
            "The app crashes. It happens on startup.",
            issue_details[0][1],
        )
        self.assertIn(
            "[#13 Related issue](https://github.com/acme/project/issues/13)",
            issue_details[0][1],
        )
        self.assertIn("30% text similarity (Open)", issue_details[0][1])
        self.assertIn("[#12 First issue]", selected_title)
        self.assertIn("The app crashes. It happens on startup.", selected_body)
        self.assertEqual(selected_issue.number, 12)
        self.assertIn("only when you click", ai_analysis)
        self.assertTrue(analyze_button["interactive"])
        self.assertEqual(review_summary, "")
        self.assertIsNone(review_category)
        self.assertIsNone(ai_suggestion)
        self.assertFalse(save_review_button["interactive"])
        self.assertEqual(review_status, "")

    @patch("app.app.fetch_closed_issues")
    @patch("app.app.fetch_issues")
    def test_compares_open_issues_with_closed_history(
        self,
        fetch_issues: Mock,
        fetch_closed_issues: Mock,
    ) -> None:
        fetch_issues.return_value = [
            GitHubIssue(
                number=12,
                title="Database connection fails",
                body="Connections fail when the database restarts.",
                labels=(),
                url="https://github.com/acme/project/issues/12",
            )
        ]
        fetch_closed_issues.return_value = [
            GitHubIssue(
                number=99,
                title="Database connection fails",
                body="Connections fail when the database restarts.",
                labels=(),
                url="https://github.com/acme/project/issues/99",
            )
        ]

        (
            _,
            status,
            issue_details,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
        ) = load_issues("acme/project", 10)

        self.assertIn(
            "[#99 Database connection fails]"
            "(https://github.com/acme/project/issues/99) - 100% text similarity "
            "(Closed history)",
            issue_details[0][1],
        )
        self.assertEqual(
            status,
            "Loaded 1 open issue(s); compared against 1 historical issue(s).",
        )

    def test_selects_details_using_dataset_index(self) -> None:
        event = Mock(index=1, selected=True)
        issues = [
            GitHubIssue(1, "First issue", "First detail", (), "https://example.com/1"),
            GitHubIssue(2, "Second issue", "Second detail", (), "https://example.com/2"),
        ]

        details = render_selected_issue(
            [
                ("First title", "First detail", issues[0]),
                ("Second title", "Second detail", issues[1]),
            ],
            event,
        )

        self.assertEqual(details[:3], ("Second title", "Second detail", issues[1]))
        self.assertTrue(details[4]["interactive"])
        self.assertEqual(details[5], "")
        self.assertIsNone(details[6])
        self.assertIsNone(details[7])
        self.assertFalse(details[8]["interactive"])
        self.assertEqual(details[9], "")

    @patch("app.app.analyze_issue")
    def test_renders_llm_analysis(self, analyze_issue: Mock) -> None:
        analyze_issue.return_value = IssueAnalysis(
            summary="The app crashes on startup.",
            category="Bug",
            rationale="The issue describes broken startup behavior.",
        )
        issue = GitHubIssue(
            12,
            "Crash on startup",
            "The application crashes when launched.",
            (),
            "https://example.com/12",
        )

        (
            result,
            review_summary,
            review_category,
            ai_suggestion,
            save_button,
            review_status,
        ) = generate_ai_analysis(issue)

        self.assertIn("AI-generated summary", result)
        self.assertIn("AI-suggested category:** Bug", result)
        self.assertEqual(review_summary, "The app crashes on startup.")
        self.assertEqual(review_category, "Bug")
        self.assertEqual(
            ai_suggestion,
            {"summary": "The app crashes on startup.", "category": "Bug"},
        )
        self.assertTrue(save_button["interactive"])
        self.assertEqual(review_status, "")
        analyze_issue.assert_called_once_with(issue.title, issue.body)

    @patch("app.app.save_review")
    def test_saves_human_review_against_original_ai_suggestion(
        self, save_review: Mock
    ) -> None:
        issue = GitHubIssue(
            12,
            "Crash on startup",
            "The application crashes when launched.",
            (),
            "https://github.com/acme/project/issues/12",
        )

        result = save_issue_review(
            issue,
            {"summary": "The app fails.", "category": "Question"},
            "The app crashes during startup.",
            "Bug",
        )

        self.assertIn("Saved review for issue #12 locally", result)
        save_review.assert_called_once_with(
            issue,
            "The app fails.",
            "Question",
            "The app crashes during startup.",
            "Bug",
        )

    @patch("app.app.export_reviews_csv")
    def test_returns_local_csv_path_for_download(
        self, export_reviews_csv: Mock
    ) -> None:
        export_reviews_csv.return_value = "/tmp/maintainer_reviews.csv"

        result = download_local_reviews()

        self.assertEqual(result, "/tmp/maintainer_reviews.csv")
        export_reviews_csv.assert_called_once_with()

    @patch("app.app.analyze_issue", side_effect=IssueAnalysisNotConfiguredError("Add key."))
    def test_shows_explicit_setup_message_without_api_key(
        self, analyze_issue: Mock
    ) -> None:
        issue = GitHubIssue(
            12,
            "Crash on startup",
            "The application crashes when launched.",
            (),
            "https://example.com/12",
        )

        result, review_summary, review_category, ai_suggestion, save_button, _ = (
            generate_ai_analysis(issue)
        )

        self.assertIn("AI analysis is not configured", result)
        self.assertIn("Rule-based summary", result)
        self.assertEqual(review_summary, "")
        self.assertIsNone(review_category)
        self.assertIsNone(ai_suggestion)
        self.assertFalse(save_button["interactive"])


if __name__ == "__main__":
    unittest.main()
