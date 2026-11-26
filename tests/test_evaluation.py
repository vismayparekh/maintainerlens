import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.evaluate import (
    Annotation,
    SimilarityAnnotation,
    _score_file,
    evaluate_annotations,
    evaluate_similarity_annotations,
    export_template,
    read_annotations,
    read_similarity_annotations,
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
        self.assertIn("Macro F1 (categories with reference support): 100%", report)
        self.assertIn("Similar-issue pairs: 1 correct of 1 suggested", report)
        self.assertIn("Pair precision / recall / F1: 100% / 100% / 100%", report)
        self.assertIn("Top-3 precision / recall (micro by query): 100% / 100%", report)

    def test_reads_similarity_annotations_without_category_labels(self) -> None:
        contents = (
            "repository,number,title,url,duplicate_group\n"
            "acme/project,1,Original issue,https://github.com/acme/project/issues/1,group-a\n"
            "acme/project,2,Duplicate issue,https://github.com/acme/project/issues/2,group-a\n"
            "acme/project,3,Hard negative,https://github.com/acme/project/issues/3,\n"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "similarity.csv"
            path.write_text(contents, encoding="utf-8")

            annotations = read_similarity_annotations(path)

        self.assertEqual(
            annotations,
            [
                SimilarityAnnotation("acme/project", 1, "group-a"),
                SimilarityAnnotation("acme/project", 2, "group-a"),
                SimilarityAnnotation("acme/project", 3, ""),
            ],
        )

    def test_requires_duplicate_groups_to_contain_a_pair(self) -> None:
        contents = (
            "repository,number,title,url,duplicate_group\n"
            "acme/project,1,Only member,https://github.com/acme/project/issues/1,group-a\n"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "similarity.csv"
            path.write_text(contents, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "at least two issues"):
                read_similarity_annotations(path)

    @patch("app.evaluate.fetch_issue_by_number")
    def test_scores_similarity_annotations_without_category_metrics(
        self, fetch_issue: Mock
    ) -> None:
        fetch_issue.side_effect = [
            GitHubIssue(
                number=1,
                title="Login form fails during password reset",
                body="Reset requests return a server error.",
                labels=(),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="Password reset login form returns server error",
                body="Reset requests return a server error.",
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
            SimilarityAnnotation("acme/project", 1, "login-error"),
            SimilarityAnnotation("acme/project", 2, "login-error"),
            SimilarityAnnotation("acme/project", 3, ""),
        ]

        report = evaluate_similarity_annotations(annotations)

        self.assertIn("Evaluated 3 issue(s) for similarity", report)
        self.assertIn("Pair precision / recall / F1: 100% / 100% / 100%", report)
        self.assertNotIn("Category", report)

    @patch("app.evaluate.fetch_issue_by_number")
    def test_reuses_snapshot_without_fetching_github(self, fetch_issue: Mock) -> None:
        fetch_issue.return_value = GitHubIssue(
            12, "Crash on startup", "The app crashes.", (),
            "https://github.com/acme/project/issues/12",
        )
        with tempfile.TemporaryDirectory() as directory:
            annotations = Path(directory) / "category.csv"
            annotations.write_text(
                "repository,number,title,url,expected_category,duplicate_group\n"
                "acme/project,12,Crash,https://github.com/acme/project/issues/12,Bug,\n",
                encoding="utf-8",
            )
            snapshot = Path(directory) / "snapshots" / "category.json"
            first_report = _score_file(annotations, snapshot, similarity=False)
            second_report = _score_file(annotations, snapshot, similarity=False)

        self.assertEqual(first_report, second_report)
        fetch_issue.assert_called_once_with("acme/project", 12)


if __name__ == "__main__":
    unittest.main()
