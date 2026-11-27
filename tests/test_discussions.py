import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api import app


class DiscussionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.params = {"repository": "https://github.com/acme/project"}
        self.item = {
            "number": 5, "title": "Usage question", "url": "https://github.com/acme/project/discussions/5",
            "isAnswered": True, "updatedAt": "2026-01-01T00:00:00Z",
            "category": {"name": "Q&A", "isAnswerable": True}, "author": None,
            "labels": {"nodes": [{"name": "help"}]}, "comments": {"totalCount": 1},
        }

    def result(self, repo):
        response = Mock(status_code=200)
        response.json.return_value = {"data": {"repository": repo}}
        return response

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"})
    @patch("app.github_discussions.requests.post")
    def test_loads_public_listing_and_normalizes_accepted_answer(self, post):
        answer = {"body": "Accepted text", "url": self.item["url"] + "#discussioncomment-1", "author": {"login": "helper"}}
        detail = {**self.item, "body": "Original post", "answer": answer, "comments": {"totalCount": 1, "nodes": [answer]}}
        announcement = {
            **self.item,
            "number": 6,
            "isAnswered": None,
            "category": {"name": "Announcements", "isAnswerable": False},
        }
        repo = {"isPrivate": False, "hasDiscussionsEnabled": True}
        post.side_effect = [
            self.result({**repo, "discussions": {"nodes": [self.item, announcement, None]}}),
            self.result({**repo, "discussion": detail}),
        ]
        listing = self.client.get("/api/discussions", params=self.params)
        self.assertEqual(listing.status_code, 200)
        item = listing.json()["discussions"][0]
        self.assertEqual(item["labels"], ["help"])
        self.assertTrue(item["answered"])
        self.assertIsNone(item["author"])
        self.assertFalse(listing.json()["discussions"][1]["answered"])
        self.assertFalse(listing.json()["discussions"][1]["answerable"])
        self.assertEqual(post.call_args.kwargs["json"]["variables"], {"owner": "acme", "name": "project", "limit": 10})
        result = self.client.get("/api/discussions/5", params=self.params)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["answer"]["body"], "Accepted text")
        self.assertEqual(result.json()["recent_comments"][0]["author"], "helper")
        self.assertNotIn("mutation", post.call_args.kwargs["json"]["query"])

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"})
    @patch("app.github_discussions.requests.post")
    def test_distinguishes_disabled_private_and_missing(self, post):
        post.side_effect = [
            self.result({"isPrivate": False, "hasDiscussionsEnabled": False}),
            self.result({"isPrivate": True, "hasDiscussionsEnabled": True, "discussions": {"nodes": [self.item]}}),
            self.result({"isPrivate": False, "hasDiscussionsEnabled": True, "discussion": None}),
        ]
        disabled = self.client.get("/api/discussions", params=self.params)
        self.assertEqual(disabled.json(), {"discussions_enabled": False, "discussions": []})
        self.assertEqual(self.client.get("/api/discussions", params=self.params).status_code, 404)
        self.assertEqual(self.client.get("/api/discussions/5", params=self.params).status_code, 404)

    @patch.dict("os.environ", {}, clear=True)
    @patch("app.github_discussions.requests.post")
    def test_requires_configured_github_token(self, post):
        response = self.client.get("/api/discussions", params=self.params)
        self.assertEqual(response.status_code, 503)
        self.assertIn("GITHUB_TOKEN", response.json()["detail"])
        post.assert_not_called()
