import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import app
from app.deployment import PUBLIC_GENERATION_DAILY_LIMIT, _DailyGenerationQuota
from app.github_client import _request_headers
from app.llm_client import IssueAnalysis, ReplyDraft


class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.issue = {"title": "The application crashes", "body": "The report includes a startup failure."}

    @patch.dict("os.environ", {"MAINTAINERLENS_PUBLIC_DEMO": "1", "HF_TOKEN": "test-hf"}, clear=True)
    @patch("app.api.export_reviews_csv")
    @patch("app.api.save_reply_trial")
    def test_public_demo_disables_review_storage_and_unconfigured_generation(self, save_reply_trial, export_reviews):
        settings = self.client.get("/api/deployment")
        self.assertEqual(settings.json(), {"public_demo": True, "demo_generation": False})
        self.assertEqual(settings.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/api/reviews/export").status_code, 404)
        self.assertEqual(self.client.get("/api/reply-reviews/export").status_code, 404)
        self.assertEqual(self.client.post("/api/reviews", json={}).status_code, 404)
        self.assertEqual(self.client.post("/api/reply-reviews", json={}).status_code, 404)
        self.assertEqual(self.client.post("/api/issues/analyze", json=self.issue).status_code, 503)
        save_reply_trial.assert_not_called()
        export_reviews.assert_not_called()

    @patch.dict("os.environ", {
        "MAINTAINERLENS_PUBLIC_DEMO": "1", "HF_TOKEN": "test-hf", "MAINTAINERLENS_DEMO_ACCESS_KEY": "test-key",
    }, clear=True)
    @patch("app.api.fetch_pull_request_details")
    @patch("app.api.draft_issue_reply")
    @patch("app.api.analyze_issue")
    def test_ai_access_key_is_checked_before_provider_and_github_requests(self, analyze, draft, fetch_pull):
        self.assertTrue(self.client.get("/api/deployment").json()["demo_generation"])
        self.assertEqual(self.client.post("/api/issues/analyze", json=self.issue).status_code, 403)
        self.assertEqual(self.client.post("/api/issues/draft-reply", json=self.issue).status_code, 403)
        self.assertEqual(self.client.post("/api/pull-requests/1/analyze?repository=acme/project").status_code, 403)
        analyze.assert_not_called()
        draft.assert_not_called()
        fetch_pull.assert_not_called()
        analyze.return_value = IssueAnalysis(
            summary="Crashes at startup.", category="Bug", rationale="The report describes a crash."
        )
        response = self.client.post(
            "/api/issues/analyze", json=self.issue, headers={"X-MaintainerLens-Access-Key": "test-key"},
        )
        self.assertEqual(response.status_code, 200)
        analyze.assert_called_once()
        reply = self.client.post(
            "/api/issues/draft-reply", json={"title": "Possible security vulnerability", "body": ""},
        )
        self.assertEqual(reply.status_code, 200)
        self.assertIn("private reporting", reply.json()["reply"])
        draft.assert_not_called()

    @patch.dict("os.environ", {
        "MAINTAINERLENS_PUBLIC_DEMO": "1", "MAINTAINERLENS_PUBLIC_GENERATION": "1", "HF_TOKEN": "test-hf",
    }, clear=True)
    @patch("app.api.analyze_issue")
    @patch("app.api.draft_issue_reply")
    def test_anonymous_generation_uses_one_shared_quota(self, draft, analyze):
        analyze.return_value = IssueAnalysis(summary="Example", category="Bug", rationale="Example rationale.")
        draft.return_value = ReplyDraft(reply="Thanks for the report.", checklist=[], related_issue_numbers=[])
        with patch("app.deployment._public_generation_quota", _DailyGenerationQuota(2)):
            settings = self.client.get("/api/deployment").json()
            self.assertTrue(settings["demo_generation"])
            self.assertEqual(settings["public_generation_daily_limit"], PUBLIC_GENERATION_DAILY_LIMIT)
            self.assertEqual(self.client.post("/api/issues/analyze", json=self.issue).status_code, 200)
            self.assertEqual(self.client.post("/api/issues/draft-reply", json=self.issue).status_code, 200)
            exhausted = self.client.post("/api/issues/draft-reply", json=self.issue)
            self.assertEqual(exhausted.status_code, 429)
            self.assertGreater(int(exhausted.headers["retry-after"]), 0)
            safe_reply = self.client.post(
                "/api/issues/draft-reply", json={"title": "Possible security vulnerability", "body": ""},
            )
            self.assertEqual(safe_reply.status_code, 200)
        analyze.assert_called_once()
        draft.assert_called_once()

    def test_daily_quota_resets_at_utc_midnight(self):
        quota = _DailyGenerationQuota(1)
        before = datetime(2026, 11, 26, 23, 59, tzinfo=timezone.utc)
        quota.take(before)
        with self.assertRaises(HTTPException) as exhausted:
            quota.take(before)
        self.assertEqual(exhausted.exception.headers, {"Retry-After": "60"})
        quota.take(datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc))

    @patch.dict("os.environ", {"MAINTAINERLENS_PUBLIC_DEMO": "1", "GITHUB_TOKEN": "test-github"}, clear=True)
    def test_public_rest_reads_do_not_use_the_server_token(self):
        self.assertNotIn("Authorization", _request_headers())
        self.assertEqual(_request_headers(use_demo_token=True)["Authorization"], "Bearer test-github")

    @patch.dict("os.environ", {"MAINTAINERLENS_PUBLIC_DEMO": "1", "GITHUB_TOKEN": "test-github"}, clear=True)
    @patch("app.github_client.requests.get")
    def test_public_rest_reads_authenticate_after_checking_repository_visibility(self, get):
        from app.github_client import fetch_issues

        get.return_value.status_code = 200
        get.return_value.json.side_effect = [
            {"visibility": "public", "private": False, "full_name": "Acme/Project"},
            [],
        ]
        self.assertEqual(fetch_issues("acme/project"), [])
        self.assertEqual(
            [call.args[0] for call in get.call_args_list],
            ["https://api.github.com/repos/acme/project", "https://api.github.com/repos/acme/project/issues"],
        )
        for call in get.call_args_list:
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-github")
            self.assertIs(call.kwargs["allow_redirects"], False)

    @patch.dict("os.environ", {"MAINTAINERLENS_PUBLIC_DEMO": "1", "GITHUB_TOKEN": "test-github"}, clear=True)
    @patch("app.github_client.requests.get")
    def test_public_rest_reads_fail_closed_for_nonpublic_or_moved_repositories(self, get):
        from app.github_client import fetch_pull_requests

        for status, metadata in (
            (200, {"visibility": "private", "private": True, "full_name": "acme/project"}),
            (200, {"visibility": "internal", "private": False, "full_name": "acme/project"}),
            (200, {"visibility": "public", "private": False, "full_name": "different/project"}),
            (301, {}),
            (404, {}),
        ):
            with self.subTest(status=status, metadata=metadata):
                get.reset_mock()
                get.return_value.status_code = status
                get.return_value.json.return_value = metadata
                with self.assertRaisesRegex(ValueError, "Public GitHub repository not found"):
                    fetch_pull_requests("acme/project")
                get.assert_called_once()
