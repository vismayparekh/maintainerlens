import unittest

from app.github_client import GitHubIssue
from app.label_suggestions import suggest_labels


class LabelSuggestionTests(unittest.TestCase):
    def test_custom_category_and_scoped_module_use_catalog_spelling(self):
        issue = GitHubIssue(1, "How to use linear_model with samples?", "", (), "https://github.com/a/b/issues/1")
        result = suggest_labels(issue, "Question", ["Question/Not a bug", "module:linear_model", "Help Wanted"])
        self.assertEqual([item.name for item in result], ["Question/Not a bug", "module:linear_model"])

    def test_avoids_second_category_when_a_category_label_is_present(self):
        issue = GitHubIssue(1, "Request crashes", "", ("Question/Not a bug",), "https://github.com/a/b/issues/1")
        self.assertEqual(suggest_labels(issue, "Bug", ["Bug", "Question/Not a bug"]), [])

    def test_recommends_documentation_for_explicit_title_and_ignores_security_tag(self):
        issue = GitHubIssue(1, "Correct the README security section", "", (), "https://github.com/a/b/issues/1")
        result = suggest_labels(issue, "Other", ["area:security", "Docs", "Documentation", "needs triage"])
        self.assertEqual([item.name for item in result], ["Docs"])
