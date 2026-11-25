import unittest
from unittest.mock import Mock, patch

from app.app import load_issues
from app.github_client import GitHubIssue


class LoadIssuesTests(unittest.TestCase):
    @patch("app.app.fetch_issues")
    def test_includes_category_summary_and_similarity_matches(
        self, fetch_issues: Mock
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

        rows, status = load_issues("acme/project", 10)

        self.assertEqual(
            rows[0],
            [
                12,
                "Bug",
                "First issue",
                "The app crashes. It happens on startup.",
                "#13 Related issue (67%)",
                "The app crashes. It happens on startup.",
                "bug",
                "https://github.com/acme/project/issues/12",
            ],
        )
        self.assertEqual(status, "Loaded 2 open issue(s).")


if __name__ == "__main__":
    unittest.main()
