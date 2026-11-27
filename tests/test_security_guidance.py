import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import app
from app.github_client import GitHubIssue
from app.security_guidance import security_guidance


class SecurityGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.issue = GitHubIssue(
            12, "Question about an access check", "Synthetic security review fixture.", ("type: security",),
            "https://github.com/acme/project/issues/12",
        )

    def test_constructs_repository_links_and_ignores_hidden_template_text(self):
        guidance = security_guidance(self.issue)
        self.assertEqual(guidance.security_url, "https://github.com/acme/project/security")
        self.assertEqual(guidance.policy_url, "https://github.com/acme/project/security/policy")
        self.assertIn("private contact", guidance.reply)
        regular = GitHubIssue(8, "Import fails", "<!-- Report a vulnerability privately -->", (), self.issue.url)
        self.assertIsNone(security_guidance(regular))

    @patch("app.api.fetch_closed_issues")
    @patch("app.api.fetch_issues")
    def test_keeps_flagged_issues_out_of_related_issue_candidates(self, fetch_issues, fetch_closed):
        regular = GitHubIssue(8, self.issue.title, self.issue.body, (), "https://github.com/acme/project/issues/8")
        fetch_issues.return_value = [regular, self.issue]
        fetch_closed.return_value = []
        response = self.client.get("/api/issues", params={"repository": "acme/project"})
        self.assertEqual(response.status_code, 200)
        normal, flagged = response.json()["issues"]
        self.assertIsNone(normal["security_guidance"])
        self.assertEqual(normal["similar_issues"], [])
        self.assertEqual(flagged["security_guidance"]["security_url"], "https://github.com/acme/project/security")
        self.assertEqual(flagged["similar_issues"], [])

    @patch("app.api.draft_issue_reply")
    @patch("app.api.analyze_issue")
    def test_detected_security_text_stays_out_of_provider_calls(self, analyze, draft):
        payload = {"title": "Possible security vulnerability", "body": "Synthetic test report."}
        response = self.client.post("/api/issues/analyze", json=payload)
        self.assertEqual(response.status_code, 422)
        result = self.client.post("/api/issues/draft-reply", json=payload)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["checklist"], [])
        self.assertIn("private reporting", result.json()["reply"])
        analyze.assert_not_called()
        draft.assert_not_called()
