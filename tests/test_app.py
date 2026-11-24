import unittest
from unittest.mock import Mock, patch

from app.app import load_issues
from app.github_client import GitHubIssue


class LoadIssuesTests(unittest.TestCase):
    @patch("app.app.fetch_issues")
    def test_includes_summary_in_results(self, fetch_issues: Mock) -> None:
        fetch_issues.return_value = [
            GitHubIssue(
                number=12,
                title="First issue",
                body="The app crashes. It happens on startup.",
                labels=("bug",),
                url="https://github.com/acme/project/issues/12",
            )
        ]

        rows, status = load_issues("acme/project", 10)

        self.assertEqual(
            rows[0],
            [
                12,
                "First issue",
                "The app crashes. It happens on startup.",
                "The app crashes. It happens on startup.",
                "bug",
                "https://github.com/acme/project/issues/12",
            ],
        )
        self.assertEqual(status, "Loaded 1 open issue(s).")


if __name__ == "__main__":
    unittest.main()
