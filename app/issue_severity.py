import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from app.github_client import GitHubIssue


SeverityLevel = Literal["high", "moderate", "low", "needs_review"]


@dataclass(frozen=True)
class SeveritySuggestion:
    level: SeverityLevel
    reason: str


_APPLICATION = r"(?:the )?(?:application|app|server|program|editor|service|cli)"
_STARTUP = re.compile(
    rf"\b(?:startup (?:failures?|crash(?:es)?)|"
    rf"(?:crash(?:es|ed|ing)?|hangs?|freezes?|fails?)\s+(?:on|during|at)\s+(?:start[- ]?up|boot)|"
    rf"(?:cannot|can['’]t|unable to) (?:start|launch|open|use) {_APPLICATION}|"
    rf"{_APPLICATION} (?:fails|refuses) to (?:start|launch|boot))\b",
    re.IGNORECASE,
)
_DATA_LOSS = re.compile(
    r"\b(?:data (?:loss|corruption) (?:after|when|during|on|occurred|occurs|happens)|"
    r"(?:causes?|caused|experienced|reports?|reported) data (?:loss|corruption)|"
    r"(?:loses?|lost|deletes?|deleted|corrupts?|corrupted) "
    r"(?:existing |saved |user )?(?:data|files|records|work))\b",
    re.IGNORECASE,
)
_WORKFLOW_FAILURE = re.compile(
    r"\b(?:(?:crash(?:es|ed|ing)?|hangs?|freezes?|fails?) (?:when|if|after|while|during|on|with) \w+|"
    r"fails? to (?:compile|export|import|load|parse|read|render|save|write)|"
    r"(?:raises|throws) (?:an? )?(?:[a-z]+(?:error|exception)|exception)|"
    r"(?:incorrect|wrong|invalid) (?:output|results?|values?)|"
    r"returns? (?:an? )?(?:incorrect|wrong|invalid))\b",
    re.IGNORECASE,
)
_MINOR = re.compile(r"\b(?:typos?|misspellings?|cosmetic|visual alignment|formatting only)\b", re.IGNORECASE)
_UNCERTAIN = re.compile(
    r"\b(?:no|not|never|without|avoid|prevent\w*|potential|possible|possibly|may|might|could|risk of|"
    r"\w+n['’]t|cannot reproduce|unable to reproduce)\b",
    re.IGNORECASE,
)
_RETRACTED = re.compile(
    r"^\s+(?:(?:does|did|has|have|was|is)\s+(?:not|never)|is possible|may|might|could)\b",
    re.IGNORECASE,
)
_HYPOTHETICAL = re.compile(r"^\s*(?:if|what if|whether|how to)\b", re.IGNORECASE)
_EXPECTED = re.compile(r"^expected(?:\s+(?:behavio[u]?r|results?|output))?\b", re.IGNORECASE)
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+)$|^\*\*(.+?)\*\*\s*:?\s*$")
_FENCE = re.compile(r"^(`{3,}|~{3,})")


def _reported_text(issue: GitHubIssue) -> Iterator[str]:
    yield issue.title
    body = re.sub(r"<!--[\s\S]*?(?:-->|\Z)", "", issue.body)
    fence = ""
    expected_section = False
    for raw in body.splitlines():
        line = raw.strip()
        marker = _FENCE.match(line)
        if marker:
            if not fence:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = ""
            continue
        if fence or line.startswith(">"):
            continue
        heading = _MARKDOWN_HEADING.match(line)
        if heading:
            expected_section = bool(_EXPECTED.match(heading[1] or heading[2]))
        elif _EXPECTED.fullmatch(line.rstrip(":")):
            expected_section = True
        elif re.match(r"^(?:actual|observed)\s+(?:behavio[u]?r|results?|output)\s*:", line, re.IGNORECASE):
            expected_section = False
        if not expected_section and not _EXPECTED.match(line.lstrip("*")):
            yield line


def _asserted(pattern: re.Pattern[str], lines: list[str]) -> bool:
    for line in lines:
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if sentence.endswith("?") or _HYPOTHETICAL.match(sentence):
                continue
            for match in pattern.finditer(sentence):
                before = " ".join(sentence[:match.start()].split()[-6:])
                if not _UNCERTAIN.search(before) and not _RETRACTED.match(sentence[match.end():]):
                    return True
    return False


def suggest_severity(issue: GitHubIssue, category: str) -> SeveritySuggestion:
    """Estimate reported impact using explicit evidence in the issue text."""
    if category in {"Question", "Feature request"}:
        return SeveritySuggestion("needs_review", "Confirm whether this report describes a failure of existing behavior.")

    lines = list(_reported_text(issue))
    if _asserted(_DATA_LOSS, lines):
        return SeveritySuggestion("high", "The report describes data loss or corruption.")
    if _asserted(_STARTUP, lines):
        return SeveritySuggestion("high", "The report describes a failure that blocks startup or normal use.")
    if _asserted(_MINOR, lines[:1]):
        return SeveritySuggestion("low", "The title describes a wording or cosmetic issue.")
    if _asserted(_WORKFLOW_FAILURE, lines):
        return SeveritySuggestion("moderate", "The report describes a concrete failure in an affected workflow.")
    return SeveritySuggestion("needs_review", "Confirm which workflow is affected and how much it is blocked.")
