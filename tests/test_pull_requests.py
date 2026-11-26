import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api import app


def pull_payload(*, private=False):
    return {
        "number": 18,
        "title": "Preserve formatting in exports",
        "body": (
            "Fixes #12 and resolves another/repo#6. "
            "See https://github.com/Acme/Example/issues/12 and https://github.com/acme/example/issues/15."
        ),
        "html_url": "https://github.com/acme/example/pull/18",
        "state": "open",
        "draft": True,
        "updated_at": "2026-11-26T00:00:00Z",
        "user": {"login": "example-contributor"},
        "base": {"ref": "main", "repo": {"private": private}},
        "head": {"ref": "preserve-format"},
        "changed_files": 24,
        "additions": 28,
        "deletions": 4,
    }


def github_response(payload):
    response = Mock()
    response.json.return_value = payload
    return response


def completion(content, *, finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish_reason, message=SimpleNamespace(content=content),
    )])


class PullRequestWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.repo = {"repository": "https://github.com/acme/example"}

    @patch("app.github_client.requests.get")
    def test_lists_recent_pull_requests_and_loads_selected_details(self, get):
        pull = pull_payload()
        get.side_effect = [
            github_response([pull]),
            github_response(pull),
            github_response([{"filename": "export.py", "status": "modified", "additions": 8, "deletions": 2}]),
        ]

        listing = self.client.get("/api/pull-requests", params=self.repo)
        details = self.client.get("/api/pull-requests/18", params=self.repo)

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["pull_requests"][0]["status"], "draft")
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.json()["changed_files"], 24)
        self.assertEqual(details.json()["files"][0]["path"], "export.py")
        self.assertEqual(
            [reference["url"] for reference in details.json()["issue_references"]],
            ["https://github.com/acme/example/issues/12", "https://github.com/another/repo/issues/6",
             "https://github.com/acme/example/issues/15"],
        )
        self.assertEqual(get.call_args_list[0].kwargs["params"], {
            "state": "open", "sort": "updated", "direction": "desc", "per_page": 10,
        })
        self.assertEqual(get.call_args_list[2].kwargs["params"], {"per_page": 20})

    @patch.dict(os.environ, {"HF_TOKEN": "test-token", "HF_MODEL": "test-model"})
    @patch("app.llm_client.OpenAI")
    @patch("app.github_client.requests.get")
    def test_brief_sends_metadata_without_source_diff(self, get, openai_client):
        get.side_effect = [
            github_response(pull_payload()),
            github_response([{
                "filename": "export.py", "status": "modified", "additions": 8, "deletions": 2,
                "patch": "diff content excluded from AI input",
            }]),
        ]
        create = openai_client.return_value.chat.completions.create
        create.return_value = completion(json.dumps({
            "summary": "The author proposes preserving export formatting.",
            "checklist": ["Review the changes in export.py."],
        }))

        response = self.client.post("/api/pull-requests/18/analyze", params=self.repo)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["checklist"], ["Review the changes in export.py."])
        payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(payload["changed_files"], 24)
        self.assertEqual(payload["files"], [{
            "path": "export.py", "status": "modified", "additions": 8, "deletions": 2,
        }])

    @patch.dict(os.environ, {"HF_TOKEN": "test-token", "HF_MODEL": "test-model"})
    @patch("app.llm_client.OpenAI")
    @patch("app.github_client.requests.get")
    def test_brief_retries_incomplete_or_invalid_output_with_more_tokens(self, get, openai_client):
        complete = completion('{"summary":"Proposed change","checklist":["Inspect the changed files."]}')
        failures = (
            completion(None, finish_reason="length"),
            completion('{"summary":"Missing checklist"}'),
        )
        for first in failures:
            with self.subTest(finish_reason=first.choices[0].finish_reason):
                get.side_effect = [github_response(pull_payload()), github_response([])]
                create = openai_client.return_value.chat.completions.create
                create.reset_mock()
                create.side_effect = [first, complete]

                response = self.client.post("/api/pull-requests/18/analyze", params=self.repo)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["checklist"], ["Inspect the changed files."])
                self.assertEqual([call.kwargs["max_tokens"] for call in create.call_args_list], [4096, 8192])

    @patch.dict(os.environ, {"HF_TOKEN": "test-token", "HF_MODEL": "test-model"})
    @patch("app.llm_client.OpenAI")
    @patch("app.github_client.requests.get")
    def test_brief_stops_after_two_incomplete_outputs(self, get, openai_client):
        get.side_effect = [github_response(pull_payload()), github_response([])]
        create = openai_client.return_value.chat.completions.create
        create.return_value = completion('{"summary":', finish_reason="length")

        response = self.client.post("/api/pull-requests/18/analyze", params=self.repo)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(create.call_count, 2)

    @patch("app.api.analyze_pull_request")
    @patch("app.github_client.requests.get")
    def test_private_pull_requests_never_reach_provider(self, get, analyze):
        get.return_value = github_response(pull_payload(private=True))

        response = self.client.post("/api/pull-requests/18/analyze", params=self.repo)

        self.assertEqual(response.status_code, 400)
        get.assert_called_once()
        analyze.assert_not_called()
