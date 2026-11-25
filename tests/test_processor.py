import unittest

from app.github_client import GitHubIssue
from app.processor import find_similar_issues, summarize_issue


class IssueProcessorTests(unittest.TestCase):
    def test_returns_first_two_sentences_with_normalized_whitespace(self) -> None:
        body = "The app crashes.  It happens on startup.\nMore details follow."

        self.assertEqual(
            summarize_issue(body),
            "The app crashes. It happens on startup.",
        )

    def test_handles_empty_and_long_bodies(self) -> None:
        self.assertEqual(summarize_issue(" \n "), "No description provided.")

        summary = summarize_issue("A" * 300)
        self.assertEqual(len(summary), 240)
        self.assertTrue(summary.endswith("..."))

    def test_finds_related_issues_and_excludes_unrelated_ones(self) -> None:
        issues = [
            GitHubIssue(
                number=1,
                title="Login form fails during password reset",
                body="Reset requests return a server error.",
                labels=(),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="Password reset login form returns server error",
                body="Reset requests return a server error.",
                labels=(),
                url="https://github.com/acme/project/issues/2",
            ),
            GitHubIssue(
                number=3,
                title="Document installation steps",
                body="Add examples for setting up the project.",
                labels=(),
                url="https://github.com/acme/project/issues/3",
            ),
        ]

        matches = find_similar_issues(issues)

        self.assertEqual([match.issue.number for match in matches[1]], [2])
        self.assertGreaterEqual(matches[1][0].score, 0.2)
        self.assertEqual(matches[3], [])


if __name__ == "__main__":
    unittest.main()
