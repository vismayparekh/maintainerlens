import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

from app.github_client import GitHubIssue
from app.review_store import REVIEW_DB_PATH, ReviewStoreError


class ReplyTrial(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    trial_id: UUID4
    mode: Literal["manual", "assisted"]
    duration_ms: int = Field(ge=0)
    original_reply: str | None = Field(default=None, min_length=1, max_length=3000)
    original_checklist: str | None = Field(default=None, max_length=2000)
    reviewed_reply: str = Field(min_length=1, max_length=3000)
    reviewed_checklist: str = Field(max_length=2000)

    @model_validator(mode="after")
    def validate_original(self):
        has_original = self.original_reply is not None and self.original_checklist is not None
        if self.mode == "assisted" and not has_original:
            raise ValueError("An assisted trial requires the original reply and checklist.")
        if self.mode == "manual" and (self.original_reply is not None or self.original_checklist is not None):
            raise ValueError("A manual trial starts with an empty draft.")
        return self


_COLUMNS = (
    "trial_id", "issue_url", "issue_number", "issue_title", "mode", "duration_ms",
    "original_reply", "original_checklist", "reviewed_reply", "reviewed_checklist",
    "reviewed_at_utc",
)


def save_reply_trial(
    issue: GitHubIssue, trial: ReplyTrial, *, database_path: Path = REVIEW_DB_PATH
) -> None:
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS reply_trials (
                    trial_id TEXT PRIMARY KEY,
                    issue_url TEXT NOT NULL,
                    issue_number INTEGER NOT NULL,
                    issue_title TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    original_reply TEXT,
                    original_checklist TEXT,
                    reviewed_reply TEXT NOT NULL,
                    reviewed_checklist TEXT NOT NULL,
                    reviewed_at_utc TEXT NOT NULL
                )
            """)
            connection.execute("""
                INSERT INTO reply_trials VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trial_id) DO NOTHING
            """, (
                str(trial.trial_id), issue.url, issue.number, issue.title, trial.mode,
                trial.duration_ms, trial.original_reply, trial.original_checklist,
                trial.reviewed_reply, trial.reviewed_checklist,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ))
    except (OSError, sqlite3.Error) as exc:
        raise ReviewStoreError("Could not save the local reply review.") from exc


def export_reply_trials(*, database_path: Path = REVIEW_DB_PATH) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow((*_COLUMNS, "factual_error"))
    if not database_path.exists():
        return output.getvalue()

    try:
        with closing(sqlite3.connect(database_path)) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'reply_trials'"
            ).fetchone()
            if table:
                rows = connection.execute(
                    "SELECT * FROM reply_trials ORDER BY reviewed_at_utc, trial_id"
                )
                writer.writerows((*row, "") for row in rows)
    except sqlite3.Error as exc:
        raise ReviewStoreError("Could not export local reply reviews.") from exc

    return output.getvalue()
