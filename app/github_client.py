import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

API_URL = "https://api.github.com"
MAX_ISSUES = 20
REQUEST_TIMEOUT = 15
_REPOSITORY_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "MaintainerLens",
}


@dataclass(frozen=True)
class GitHubIssue:
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    url: str


def _repository_slug(repository: str) -> str:
    if not isinstance(repository, str) or not repository.strip():
        raise ValueError("Enter a GitHub repository as owner/repo or a GitHub URL.")

    value = repository.strip()
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
            raise ValueError("Use a repository URL from https://github.com.")
        if parsed.query or parsed.fragment:
            raise ValueError("Enter the repository URL without a query or fragment.")
        value = parsed.path.strip("/")

    if value.endswith(".git"):
        value = value[:-4]

    parts = value.split("/")
    if (
        len(parts) != 2
        or any(
            not _REPOSITORY_PART.fullmatch(part) or part in {".", ".."}
            for part in parts
        )
    ):
        raise ValueError("Enter a repository as owner/repo or a GitHub repository URL.")

    return "/".join(parts)


def _parse_issue(item: dict[str, object]) -> GitHubIssue:
    title = item.get("title")
    url = item.get("html_url")
    labels = item.get("labels")
    body = item.get("body")
    number = item.get("number")
    if (
        not isinstance(number, int)
        or not isinstance(title, str)
        or not isinstance(url, str)
        or not isinstance(labels, list)
        or (body is not None and not isinstance(body, str))
    ):
        raise ValueError("GitHub returned an issue with an unexpected format.")

    label_names: list[str] = []
    for label in labels:
        if not isinstance(label, dict) or not isinstance(label.get("name"), str):
            raise ValueError("GitHub returned an issue with an unexpected label.")
        label_names.append(label["name"])

    return GitHubIssue(
        number=number,
        title=title,
        body=body or "",
        labels=tuple(label_names),
        url=url,
    )


def fetch_issues(repository: str, limit: int = 10) -> list[GitHubIssue]:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_ISSUES
    ):
        raise ValueError(f"Issue limit must be between 1 and {MAX_ISSUES}.")

    slug = _repository_slug(repository)
    response = requests.get(
        f"{API_URL}/repos/{slug}/issues",
        params={
            "state": "open",
            "sort": "created",
            "direction": "desc",
            "per_page": 100,
        },
        headers=_API_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("GitHub returned an unexpected issues response.")

    issues: list[GitHubIssue] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("GitHub returned an unexpected issue.")
        if "pull_request" in item:
            continue

        issues.append(_parse_issue(item))
        if len(issues) == limit:
            break

    return issues


def fetch_issue_by_number(repository: str, issue_number: int) -> GitHubIssue:
    if (
        isinstance(issue_number, bool)
        or not isinstance(issue_number, int)
        or issue_number < 1
    ):
        raise ValueError("Issue number must be a positive integer.")

    slug = _repository_slug(repository)
    response = requests.get(
        f"{API_URL}/repos/{slug}/issues/{issue_number}",
        headers=_API_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    item = response.json()
    if not isinstance(item, dict):
        raise ValueError("GitHub returned an unexpected issue response.")
    if "pull_request" in item:
        raise ValueError(f"#{issue_number} is a pull request, not an issue.")
    return _parse_issue(item)
