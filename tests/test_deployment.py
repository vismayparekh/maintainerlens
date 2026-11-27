import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import app
from app.github_client import _request_headers
from app.llm_client import IssueAnalysis


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

    @patch.dict("os.environ", {"MAINTAINERLENS_PUBLIC_DEMO": "1", "GITHUB_TOKEN": "test-github"}, clear=True)
    def test_public_rest_reads_do_not_use_the_server_token(self):
        self.assertNotIn("Authorization", _request_headers())
        self.assertEqual(_request_headers(use_demo_token=True)["Authorization"], "Bearer test-github")
