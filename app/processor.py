from collections.abc import Sequence
from dataclasses import dataclass
import re

from app.github_client import GitHubIssue

MAX_SUMMARY_LENGTH = 240
SIMILARITY_THRESHOLD = 0.2
MAX_SIMILAR_ISSUES = 3
ISSUE_CATEGORIES = ("Bug", "Question", "Feature request", "Other")
_BUG_TERMS = re.compile(
    r"\b(?:bug|crash(?:es|ed)?|error|exception|regression|broken|"
    r"fail(?:s|ed)?|failure)\b"
)
_BUG_TITLE_TERMS = re.compile(
    r"\b(?:bug|crash(?:es|ed)?|regression|broken|fail(?:s|ed)?|failure|"
    r"incorrect|wrong|invalid|drop(?:s|ped)?|treat(?:s|ed)?)\b"
)
_FEATURE_TERMS = re.compile(
    r"\b(?:feature request|new feature|feature|enhancement|add support|support for|"
    r"would like|please add|promot(?:e|es|ed|ing))\b|\benh\s*:"
)
_QUESTION_START = re.compile(
    r"^(?:how|what|why|when|where|who|can|could|do|does|is|are|should|questions?)\b"
)
_QUESTION_IN_BODY = re.compile(
    r"(?:^|[\n.!?]\s*)(?:how|what|why|when|where|who|can|could|do|does|is|are|"
    r"should|was|were)\b[^.!?\n]{0,200}\?"
)
_OTHER_TITLE_TERMS = re.compile(
    r"\b(?:tests?\b|test[a-z0-9_]*timeout\b|coverage|docs?|documentation|"
    r"docstrings?|examples?|quickstart)"
)
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


def classify_issue(issue: GitHubIssue, *, use_labels: bool = True) -> str:
    if use_labels:
        label_tokens = {
            token
            for label in issue.labels
            for token in re.findall(r"[a-z0-9]+", label.casefold())
        }
        if "bug" in label_tokens:
            return "Bug"
        if "question" in label_tokens:
            return "Question"
        if {"feature", "enhancement"} & label_tokens:
            return "Feature request"

    title = issue.title.strip().casefold()
    if _QUESTION_START.search(title) or title.endswith("?"):
        return "Question"

    if _FEATURE_TERMS.search(title):
        return "Feature request"
    if _BUG_TITLE_TERMS.search(title):
        return "Bug"
    if _OTHER_TITLE_TERMS.search(title):
        return "Other"
    if _QUESTION_IN_BODY.search(issue.body.casefold()):
        return "Question"

    text = f"{title} {issue.body}".casefold()
    if _BUG_TERMS.search(text):
        return "Bug"
    if _FEATURE_TERMS.search(text):
        return "Feature request"
    return "Other"


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