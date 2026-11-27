import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.github_client import GitHubIssue


_CATEGORY_LABELS = {
    "Bug": ("bug", "defect", "bug report"),
    "Question": ("question", "usage question", "user support", "support request", "question not a bug", "support"),
    "Feature request": ("feature request", "enhancement", "feature", "new feature"),
}
_ALL_CATEGORY_ALIASES = {alias for aliases in _CATEGORY_LABELS.values() for alias in aliases}
_CATEGORY_PREFIX = re.compile(r"^(?:type|kind|t|issue|category)\s+")
_TOPIC_PREFIX = re.compile(r"^(?:module|component|area|topic|package|subsystem)\s*[:/]\s*(.+)$", re.IGNORECASE)
_TOPIC_LABELS = {
    "documentation": ("documentation", "docs", "doc", "docstrings"),
    "testing": ("testing", "tests", "test"),
    "csv": ("io csv", "csv"),
    "parquet": ("io parquet", "parquet"),
    "groupby": ("groupby", "group by"),
}
_TOPIC_SIGNALS = {
    "documentation": (*_TOPIC_LABELS["documentation"], "docstring", "readme"),
    **{name: aliases for name, aliases in _TOPIC_LABELS.items() if name != "documentation"},
}
_SECURITY_TOPIC = re.compile(r"\b(?:security|vulnerability|vulnerabilities|exploit|exploits|cve)\b")


@dataclass(frozen=True)
class LabelSuggestion:
    name: str
    reason: str


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def _topic_name(label: str) -> str:
    scope = _TOPIC_PREFIX.fullmatch(label)
    normalized = _normalize(scope[1] if scope else label)
    return next(
        (name for name, aliases in _TOPIC_LABELS.items() if normalized in aliases),
        normalized if scope else "",
    )


def suggest_labels(issue: GitHubIssue, category: str, repository_labels: Iterable[str]) -> list[LabelSuggestion]:
    """Suggest at most one category label and two evidence-backed topic labels."""
    applied = {name.casefold() for name in issue.labels}
    labels = list(repository_labels)
    category_aliases = _CATEGORY_LABELS.get(category, ())

    def category_name(label: str) -> str:
        return _CATEGORY_PREFIX.sub("", _normalize(label))

    suggestions = []
    if category_aliases and not any(category_name(label) in _ALL_CATEGORY_ALIASES for label in applied):
        candidates = [(label, category_name(label)) for label in labels]
        choice = min(
            ((label, alias) for label, alias in candidates if alias in category_aliases),
            key=lambda pair: (category_aliases.index(pair[1]), _normalize(pair[0]) != pair[1], pair[0].casefold()),
            default=None,
        )
        if choice:
            suggestions.append(LabelSuggestion(choice[0], f"Matches the suggested {category.lower()} category."))

    title = f" {_normalize(issue.title)} "
    used_topics = {_topic_name(label) for label in applied}
    max_suggestions = len(suggestions) + 2
    for label in labels:
        if label.casefold() in applied:
            continue
        topic = _topic_name(label)
        if not topic or topic in used_topics or _SECURITY_TOPIC.search(topic):
            continue
        signal = next((phrase for phrase in _TOPIC_SIGNALS.get(topic, (topic,)) if f" {phrase} " in title), None)
        if signal:
            suggestions.append(LabelSuggestion(label, f"The issue title mentions {signal}."))
            used_topics.add(topic)
            if len(suggestions) == max_suggestions:
                break
    return suggestions
