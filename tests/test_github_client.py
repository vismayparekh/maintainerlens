import unittest
from unittest.mock import Mock, patch

from app.github_client import (
    fetch_closed_issues,
    fetch_issue_by_number,
    fetch_issues,
)


class FetchIssuesTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
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
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])
        response.raise_for_status.assert_called_once_with()

    @patch("app.github_client.requests.get")
    def test_fetches_closed_issues_across_pages_and_excludes_pull_requests(
        self, get: Mock
    ) -> None:
        first_page = [{"pull_request": {}} for _ in range(99)]
        first_page.append(
            {
                "number": 12,
                "title": "Closed issue",
                "body": "Issue description",
                "labels": [],
                "html_url": "https://github.com/acme/project/issues/12",
            }
        )
        second_page = [
            {
                "number": 13,
                "title": "Another closed issue",
                "body": None,
                "labels": [],
                "html_url": "https://github.com/acme/project/issues/13",
            }
        ]
        first_response = Mock()
        first_response.json.return_value = first_page
        second_response = Mock()
        second_response.json.return_value = second_page
        get.side_effect = [first_response, second_response]

        issues = fetch_closed_issues("acme/project", limit=2)

        self.assertEqual([issue.number for issue in issues], [12, 13])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["state"], "closed")
        self.assertEqual(get.call_args_list[0].kwargs["params"]["sort"], "updated")
        self.assertEqual(get.call_args_list[0].kwargs["params"]["page"], 1)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["page"], 2)
        first_response.raise_for_status.assert_called_once_with()
        second_response.raise_for_status.assert_called_once_with()

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

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"})
    @patch("app.github_client.requests.get")
    def test_uses_optional_github_token(self, get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "number": 42,
            "title": "Issue title",
            "body": "Issue body",
            "labels": [],
            "html_url": "https://github.com/acme/project/issues/42",
        }
        get.return_value = response

        fetch_issue_by_number("acme/project", 42)

        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-token",
        )

    @patch("app.github_client.requests.get")
    def test_rejects_invalid_issue_number_without_requesting(self, get: Mock) -> None:
        with self.assertRaises(ValueError):
            fetch_issue_by_number("acme/project", 0)

        get.assert_not_called()

    @patch("app.github_client.requests.get")
    def test_rejects_invalid_closed_issue_limit_without_requesting(
        self, get: Mock
    ) -> None:
        with self.assertRaises(ValueError):
            fetch_closed_issues("acme/project", limit=0)

        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
