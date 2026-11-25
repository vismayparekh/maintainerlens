import unittest
from unittest.mock import Mock, patch

from app.github_client import fetch_issue_by_number, fetch_issues


class FetchIssuesTests(unittest.TestCase):
    @patch("app.github_client.requests.get")
    def test_fetches_issues_and_excludes_pull_requests(self, get: Mock) -> None:
        response = Mock()
        response.json.return_value = [
            {
                "number": 12,
                "title": "First issue",
                "body": "Issue description",
                "labels": [{"name": "bug"}],
                "html_url": "https://github.com/acme/project/issues/12",
            },
            {
                "number": 13,
                "title": "Pull request",
                "body": None,
                "labels": [],
                "html_url": "https://github.com/acme/project/pull/13",
                "pull_request": {},
            },
            {
                "number": 14,
                "title": "Second issue",
                "body": None,
                "labels": [],
                "html_url": "https://github.com/acme/project/issues/14",
            },
        ]
        get.return_value = response

        issues = fetch_issues("https://github.com/acme/project.git", limit=2)

        self.assertEqual([issue.number for issue in issues], [12, 14])
        self.assertEqual(issues[0].labels, ("bug",))
        self.assertEqual(issues[1].body, "")
        self.assertEqual(
            get.call_args.args[0],
            "https://api.github.com/repos/acme/project/issues",
        )
        self.assertEqual(get.call_args.kwargs["params"]["state"], "open")
        response.raise_for_status.assert_called_once_with()

    @patch("app.github_client.requests.get")
    def test_rejects_invalid_repository_and_limit_without_requesting(
        self, get: Mock
    ) -> None:
        with self.assertRaises(ValueError):
            fetch_issues("https://example.com/acme/project")
        with self.assertRaises(ValueError):
            fetch_issues("acme/project", limit=21)

        get.assert_not_called()

    @patch("app.github_client.requests.get")
    def test_fetches_a_single_issue_by_number(self, get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "number": 42,
            "title": "Issue title",
            "body": "Issue body",
            "labels": [{"name": "bug"}],
            "html_url": "https://github.com/acme/project/issues/42",
        }
        get.return_value = response

        issue = fetch_issue_by_number("acme/project", 42)

        self.assertEqual(issue.number, 42)
        self.assertEqual(
            get.call_args.args[0],
            "https://api.github.com/repos/acme/project/issues/42",
        )
        response.raise_for_status.assert_called_once_with()

    @patch("app.github_client.requests.get")
    def test_rejects_invalid_issue_number_without_requesting(self, get: Mock) -> None:
        with self.assertRaises(ValueError):
            fetch_issue_by_number("acme/project", 0)

        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
