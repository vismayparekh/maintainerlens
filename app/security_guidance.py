import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.github_client import GitHubIssue


_SECURITY_LABELS = {"security", "vulnerability", "security vulnerability", "security issue", "security report"}
_SECURITY_TERMS = re.compile(
    r"\b(?:vulnerabilit(?:y|ies)|CVE-\d{4}-\d{4,}|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|"
    r"security (?:issue|flaw|advisory|report|bug)|"
    r"(?:authentication|authorization|access control) bypass|"
    r"remote code execution|privilege escalation|cross-site scripting|SQL injection)\b",
    re.IGNORECASE,
)
_SECURITY_TITLE = re.compile(r"^\s*(?:\[security\]|security\s*[:—-])", re.IGNORECASE)
_PUBLIC_ISSUE_PATH = re.compile(r"/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/[1-9]\d*/?")


@dataclass(frozen=True)
class SecurityGuidance:
    reason: str
    security_url: str | None
    policy_url: str | None
    reply: str


def security_reason(title: str, body: str, labels: tuple[str, ...] = ()) -> str | None:
    for label in labels:
        normalized = " ".join(re.findall(r"[a-z]+", label.lower()))
        normalized = re.sub(r"^(?:type|kind|t|category|area|topic|priority) ", "", normalized)
        if normalized in _SECURITY_LABELS:
            return "The repository has applied a security-related label."
    # Ignore hidden issue-template guidance. Visible text is kept so that
    # a report accompanied by a fenced example is still eligible for review.
    text = re.sub(r"<!--[\s\S]*?(?:-->|\Z)", "", body)
    if _SECURITY_TITLE.match(title) or _SECURITY_TERMS.search(title) or _SECURITY_TERMS.search(text):
        return "The issue text describes a possible vulnerability or references a security report."
    return None


def private_reporting_reply(security_url: str | None = None) -> str:
    destination = (
        f"[the repository’s security page]({security_url})"
        if security_url else "the repository’s security page"
    )
    return (
        f"Thanks for flagging this. Please check {destination} for private reporting options "
        "and follow the repository’s security policy for contacting maintainers privately. "
        "Please keep further technical details out of this public thread. "
        "If you can’t find a private channel, ask the maintainers for a private contact."
    )


def security_guidance(issue: GitHubIssue) -> SecurityGuidance | None:
    reason = security_reason(issue.title, issue.body, issue.labels)
    if reason is None:
        return None
    parsed = urlsplit(issue.url)
    match = _PUBLIC_ISSUE_PATH.fullmatch(parsed.path) if parsed.scheme == "https" and parsed.netloc == "github.com" else None
    repo = match[1] if match else None
    security_url = f"https://github.com/{repo}/security" if repo and not {".", ".."}.intersection(repo.split("/")) else None
    return SecurityGuidance(
        reason=reason,
        security_url=security_url,
        policy_url=f"{security_url}/policy" if security_url else None,
        reply=private_reporting_reply(security_url),
    )
