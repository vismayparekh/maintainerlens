import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.evaluate import (
    Annotation,
    evaluate_annotations,
    export_template,
    read_annotations,
)
from app.github_client import GitHubIssue


class EvaluationTests(unittest.TestCase):
    @patch("app.evaluate.fetch_issues")
    def test_exports_annotation_columns_without_issue_bodies(
        self, fetch_issues: Mock
    ) -> None:
        fetch_issues.return_value = [
            GitHubIssue(
                number=12,
                title="Issue title",
                body="Do not copy the full body into the CSV.",
                labels=("bug",),
                url="https://github.com/acme/project/issues/12",
            )
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nested" / "annotations.csv"
            count = export_template("acme/project", 1, path)

            with path.open(newline="", encoding="utf-8") as file:
                row = next(csv.DictReader(file))
            with self.assertRaisesRegex(ValueError, "expected_category"):
                read_annotations(path)

        self.assertEqual(count, 1)
        self.assertEqual(row["expected_category"], "")
        self.assertEqual(row["duplicate_group"], "")
        self.assertNotIn("body", row)

    @patch("app.evaluate.fetch_issue_by_number")
    def test_reports_category_and_duplicate_metrics(
        self, fetch_issue: Mock
    ) -> None:
        fetch_issue.side_effect = [
            GitHubIssue(
                number=1,
                title="Crash while logging in",
                body="Login crashes and returns an authentication error.",
                labels=("question",),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="Authentication login error",
                body="Login crashes and returns an authentication error.",
                labels=(),
                url="https://github.com/acme/project/issues/2",
            ),
            GitHubIssue(
                number=3,
                title="Document installation steps",
                body="Instructions for setting up the package.",
                labels=(),
                url="https://github.com/acme/project/issues/3",
            ),
        ]
        annotations = [
            Annotation("acme/project", 1, "Bug", "login-error"),
            Annotation("acme/project", 2, "Bug", "login-error"),
            Annotation("acme/project", 3, "Other", ""),
        ]

        report = evaluate_annotations(annotations)

        self.assertIn("Category accuracy: 3/3 (100%)", report)
        self.assertIn("Similar-issue pairs: 1 correct of 1 suggested", report)
        self.assertIn("Pair precision / recall / F1: 100% / 100% / 100%", report)


if __name__ == "__main__":
    unittest.main()
