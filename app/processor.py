from collections.abc import Sequence
from dataclasses import dataclass
import re

from app.github_client import GitHubIssue

MAX_SUMMARY_LENGTH = 240
SIMILARITY_THRESHOLD = 0.2
MAX_SIMILAR_ISSUES = 3
_STOPWORDS = set(
    "a about after all also an and are as at be been but by can could did do does "
    "for from had has have he her here him his how i if in into is it its me more "
    "most my no not of on or our out same she should so some than that the their "
    "them then there these they this those to too up was we were what when where "
    "which while who why will with would you your issue issues".split()
)


@dataclass(frozen=True)
class SimilarityMatch:
    issue: GitHubIssue
    score: float


def summarize_issue(body: str) -> str:
    if not isinstance(body, str):
        raise TypeError("Issue body must be text.")

    text = re.sub(r"\s+", " ", body).strip()
    if not text:
        return "No description provided."

    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentences[:2])
    if len(summary) <= MAX_SUMMARY_LENGTH:
        return summary

    shortened = summary[: MAX_SUMMARY_LENGTH - 3]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened.rstrip(" ,;:-") + "..."


def _issue_tokens(issue: GitHubIssue) -> set[str]:
    text = f"{issue.title} {issue.body}"
    return {
        token
        for token in re.findall(r"[a-z0-9]{2,}", text.casefold())
        if token not in _STOPWORDS
    }


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def find_similar_issues(
    issues: Sequence[GitHubIssue],
) -> dict[int, list[SimilarityMatch]]:
    tokens_by_number = {issue.number: _issue_tokens(issue) for issue in issues}
    matches: dict[int, list[SimilarityMatch]] = {}

    for issue in issues:
        candidates = [
            SimilarityMatch(candidate, score)
            for candidate in issues
            if candidate.number != issue.number
            and (
                score := _jaccard_similarity(
                    tokens_by_number[issue.number],
                    tokens_by_number[candidate.number],
                )
            )
            >= SIMILARITY_THRESHOLD
        ]
        matches[issue.number] = sorted(
            candidates,
            key=lambda match: (-match.score, match.issue.number),
        )[:MAX_SIMILAR_ISSUES]

    return matches