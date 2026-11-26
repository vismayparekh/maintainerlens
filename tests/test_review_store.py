import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.github_client import GitHubIssue
from app.review_store import ReviewStoreError, export_reviews_csv, save_review


class SaveReviewTests(unittest.TestCase):
    def test_saves_latest_review_without_storing_issue_body(self) -> None:
        issue = GitHubIssue(
            12,
            "Crash on startup",
            "Issue body should remain private to the fetched issue.",
            (),
            "https://github.com/acme/project/issues/12",
        )
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "reviews.sqlite3"

            save_review(
                issue,
                "The app fails.",
                "Question",
                "The app crashes during startup.",
                "Bug",
                database_path=database_path,
            )
            save_review(
                issue,
                "Updated AI summary.",
                "Bug",
                "Updated reviewed summary.",
                "Bug",
                database_path=database_path,
            )

            with sqlite3.connect(database_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(issue_reviews)")
                }
                records = connection.execute(
                    """
                    SELECT issue_url, issue_title, ai_summary, ai_category,
                           reviewed_summary, reviewed_category
                    FROM issue_reviews
                    """
                ).fetchall()

        self.assertNotIn("body", columns)
        self.assertEqual(
            records,
            [
                (
                    issue.url,
                    issue.title,
                    "Updated AI summary.",
                    "Bug",
                    "Updated reviewed summary.",
                    "Bug",
                )
            ],
        )
        self.assertNotIn(issue.body, repr(records))

    def test_rejects_empty_summaries_and_invalid_categories(self) -> None:
        issue = GitHubIssue(
            12,
            "Crash on startup",
            "Body",
            (),
            "https://github.com/acme/project/issues/12",
        )
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "reviews.sqlite3"

            with self.assertRaises(ValueError):
                save_review(
                    issue,
                    "AI summary",
                    "Bug",
                    " ",
                    "Bug",
                    database_path=database_path,
                )
            with self.assertRaises(ValueError):
                save_review(
                    issue,
                    "AI summary",
                    "Invalid",
                    "Reviewed summary",
                    "Bug",
                    database_path=database_path,
                )

    def test_exports_review_fields_without_issue_body(self) -> None:
        issue = GitHubIssue(
            12,
            "Crash on startup",
            "Issue body is not part of the export.",
            (),
            "https://github.com/acme/project/issues/12",
        )
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "reviews.sqlite3"
            export_path = Path(directory) / "reviews.csv"
            save_review(
                issue,
                "The app fails.",
                "Question",
                "The app crashes during startup.",
                "Bug",
                database_path=database_path,
            )

            result_path = export_reviews_csv(
                database_path=database_path,
                export_path=export_path,
            )

            with result_path.open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["issue_url"], issue.url)
        self.assertEqual(rows[0]["ai_category"], "Question")
        self.assertEqual(rows[0]["reviewed_category"], "Bug")
        self.assertNotIn("body", rows[0])
        self.assertNotIn(issue.body, repr(rows))

    def test_rejects_export_when_no_reviews_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "reviews.sqlite3"
            export_path = Path(directory) / "reviews.csv"
            with sqlite3.connect(database_path):
                pass

            with self.assertRaises(ReviewStoreError):
                export_reviews_csv(
                    database_path=database_path,
                    export_path=export_path,
                )


if __name__ == "__main__":
    unittest.main()
