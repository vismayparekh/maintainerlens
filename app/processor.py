from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from math import log
import re

from app.github_client import GitHubIssue

MAX_SUMMARY_LENGTH = 240
SIMILARITY_THRESHOLD = 0.16
TITLE_SIMILARITY_WEIGHT = 0.7
TITLE_SIMILARITY_THRESHOLD = 0.2
BODY_SIMILARITY_THRESHOLD = 0.2
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
    r"would like|please add|promot(?:e|es|ed|ing)|support\s+\w+ing|"
    r"looking for (?:an easy )?way to)\b|\benh\s*:"
)
_FEATURE_TITLE_START = re.compile(r"^(?:add|allow|introduce|provide)\b")
_QUESTION_START = re.compile(
    r"^(?:how|what|why|when|where|who|can|could|do|does|is|are|should|help|questions?|"
    r"request for clarification)\b"
)
_QUESTION_IN_BODY = re.compile(
    r"(?:^|[\n.!?,;]\s*)(?:how|what|why|when|where|who|can|could|do|does|is|are|"
    r"should|was|were)\b[^!?\n]{0,1500}\?|"
    r"\b(?:i am|i'm) seeking clarification\b|"
    r"\b(?:my question|i don't know if|does anyone know|has anyone seen|"
    r"not sure how to|wanted to know if|want to know if)\b"
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
    "which while who why will with would you your bug bugs issue issues".split()
)
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


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
    if (
        title.startswith(("[question]", "[query]"))
        or _QUESTION_START.search(title)
        or title.endswith("?")
    ):
        return "Question"

    if _FEATURE_TERMS.search(title) or _FEATURE_TITLE_START.search(title):
        return "Feature request"
    if _OTHER_TITLE_TERMS.search(title):
        return "Other"
    if _BUG_TITLE_TERMS.search(title):
        return "Bug"
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
    return truncate_summary(summary, MAX_SUMMARY_LENGTH)[0]


def truncate_summary(summary: str, max_length: int) -> tuple[str, bool]:
    if max_length < 3:
        raise ValueError("Maximum summary length must be at least 3.")
    if len(summary) <= max_length:
        return summary, False

    shortened = summary[: max_length - 3]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened.rstrip(" ,;:-") + "...", True


def _text_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(
            r"[a-z0-9]{2,}",
            _URL_PATTERN.sub(" ", text).casefold(),
        )
        if token not in _STOPWORDS
    }


def _issue_similarity(
    left: tuple[set[str], set[str]],
    right: tuple[set[str], set[str]],
    term_weights: dict[str, float],
) -> float:
    title_similarity = _weighted_jaccard_similarity(
        left[0],
        right[0],
        term_weights,
    )
    body_similarity = _weighted_jaccard_similarity(
        left[1],
        right[1],
        term_weights,
    )
    if (
        title_similarity < TITLE_SIMILARITY_THRESHOLD
        and body_similarity < BODY_SIMILARITY_THRESHOLD
    ):
        return 0.0
    return (
        TITLE_SIMILARITY_WEIGHT * title_similarity
        + (1 - TITLE_SIMILARITY_WEIGHT) * body_similarity
    )


def _weighted_jaccard_similarity(
    left: set[str],
    right: set[str],
    term_weights: dict[str, float],
) -> float:
    union = left | right
    if not union:
        return 0.0
    return sum(term_weights[token] for token in left & right) / sum(
        term_weights[token] for token in union
    )


def find_similar_issues(
    issues: Sequence[GitHubIssue],
) -> dict[int, list[SimilarityMatch]]:
    tokens_by_number = {
        issue.number: (_text_tokens(issue.title), _text_tokens(issue.body))
        for issue in issues
    }
    document_frequency = Counter(
        token
        for title_tokens, body_tokens in tokens_by_number.values()
        for token in title_tokens | body_tokens
    )
    document_count = len(tokens_by_number)
    term_weights = {
        token: 1 + log((document_count + 1) / (count + 1))
        for token, count in document_frequency.items()
    }
    matches: dict[int, list[SimilarityMatch]] = {}

    for issue in issues:
        candidates = [
            SimilarityMatch(candidate, score)
            for candidate in issues
            if candidate.number != issue.number
            and (
                score := _issue_similarity(
                    tokens_by_number[issue.number],
                    tokens_by_number[candidate.number],
                    term_weights,
                )
            )
            >= SIMILARITY_THRESHOLD
        ]
        matches[issue.number] = sorted(
            candidates,
            key=lambda match: (-match.score, match.issue.number),
        )[:MAX_SIMILAR_ISSUES]

    return matches