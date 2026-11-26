from contextlib import closing
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.github_client import GitHubIssue
from app.processor import ISSUE_CATEGORIES

REVIEW_DB_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "maintainer_reviews.sqlite3"
)
REVIEW_CSV_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "maintainer_reviews.csv"
)
REVIEW_CSV_COLUMNS = (
    "issue_url",
    "issue_number",
    "issue_title",
    "ai_summary",
    "ai_category",
    "reviewed_summary",
    "reviewed_category",
    "reviewed_at_utc",
)


class ReviewStoreError(RuntimeError):
    pass


def save_review(
    issue: GitHubIssue,
    ai_summary: str,
    ai_category: str,
    reviewed_summary: str,
    reviewed_category: str,
    *,
    database_path: Path = REVIEW_DB_PATH,
) -> None:
    if not ai_summary.strip() or not reviewed_summary.strip():
        raise ValueError("AI and reviewed summaries must not be empty.")
    if (
        ai_category not in ISSUE_CATEGORIES
        or reviewed_category not in ISSUE_CATEGORIES
    ):
        raise ValueError("AI and reviewed categories must be valid issue categories.")

    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS issue_reviews (
                        issue_url TEXT PRIMARY KEY,
                        issue_number INTEGER NOT NULL,
                        issue_title TEXT NOT NULL,
                        ai_summary TEXT NOT NULL,
                        ai_category TEXT NOT NULL,
                        reviewed_summary TEXT NOT NULL,
                        reviewed_category TEXT NOT NULL,
                        reviewed_at_utc TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO issue_reviews (
                        issue_url,
                        issue_number,
                        issue_title,
                        ai_summary,
                        ai_category,
                        reviewed_summary,
                        reviewed_category,
                        reviewed_at_utc
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(issue_url) DO UPDATE SET
                        issue_number = excluded.issue_number,
                        issue_title = excluded.issue_title,
                        ai_summary = excluded.ai_summary,
                        ai_category = excluded.ai_category,
                        reviewed_summary = excluded.reviewed_summary,
                        reviewed_category = excluded.reviewed_category,
                        reviewed_at_utc = excluded.reviewed_at_utc
                    """,
                    (
                        issue.url,
                        issue.number,
                        issue.title,
                        ai_summary.strip(),
                        ai_category,
                        reviewed_summary.strip(),
                        reviewed_category,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
    except (OSError, sqlite3.Error) as exc:
        raise ReviewStoreError(f"Could not save the local review: {exc}") from exc


def export_reviews_csv(
    *,
    database_path: Path = REVIEW_DB_PATH,
    export_path: Path = REVIEW_CSV_PATH,
) -> Path:
    if not database_path.exists():
        raise ReviewStoreError("No saved reviews are available to export.")

    try:
        with closing(sqlite3.connect(database_path)) as connection:
            rows = connection.execute(
                """
                SELECT issue_url, issue_number, issue_title, ai_summary,
                       ai_category, reviewed_summary, reviewed_category,
                       reviewed_at_utc
                FROM issue_reviews
                ORDER BY reviewed_at_utc, issue_url
                """
            ).fetchall()
        if not rows:
            raise ReviewStoreError("No saved reviews are available to export.")

        export_path.parent.mkdir(parents=True, exist_ok=True)
        with export_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(REVIEW_CSV_COLUMNS)
            writer.writerows(rows)
    except (OSError, sqlite3.Error, csv.Error) as exc:
        raise ReviewStoreError(f"Could not export local reviews: {exc}") from exc

    return export_path
