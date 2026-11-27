import unittest

from app.github_client import GitHubIssue
from app.issue_severity import suggest_severity


class SeverityTests(unittest.TestCase):
    def test_uses_reported_impact_to_set_severity(self):
        cases = [
            ("Crash on startup", "", "Bug", "high"),
            ("Crash while importing CSV", "", "Bug", "moderate"),
            ("Report export", "It loses saved files after exporting.", "Bug", "high"),
            ("Data loss after exporting", "", "Bug", "high"),
            ("Docs typo", "", "Other", "low"),
            ("Rendering error", "Here's an error message.", "Bug", "needs_review"),
            ("Data loss prevention notes", "", "Other", "needs_review"),
            ("How do I start the app?", "I can't start the application with my setup.", "Question", "needs_review"),
        ]
        for title, body, category, level in cases:
            with self.subTest(title=title):
                issue = GitHubIssue(1, title, body, (), "https://github.com/acme/app/issues/1")
                suggested = suggest_severity(issue, category)
                self.assertEqual(suggested.level, level)
                self.assertTrue(suggested.reason)

    def test_ignores_unobserved_impact_and_keeps_actual_behavior(self):
        cases = [
            ("During import, no data loss was observed.", "needs_review"),
            ("Data loss could occur.", "needs_review"),
            ("No saved records were lost.", "needs_review"),
            ("The app doesn't crash on startup.", "needs_review"),
            ("### Expected behavior\nThe app fails to start.\n### Actual behavior\nImport raises TypeError.", "moderate"),
            ("**Expected behavior**\nNo data loss.\n**Actual behavior**\nThe app fails to start.", "high"),
            ("<!-- Data loss -->\n```text\nThe app fails to start.\n```\n> Crash on startup", "needs_review"),
        ]
        for body, level in cases:
            with self.subTest(body=body):
                issue = GitHubIssue(1, "Unexpected behavior", body, (), "https://github.com/acme/app/issues/1")
                self.assertEqual(suggest_severity(issue, "Bug").level, level)
