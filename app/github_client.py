import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

API_URL = "https://api.github.com"
MAX_ISSUES = 20
REQUEST_TIMEOUT = 15
_REPOSITORY_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")


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


def fetch_issues(repository: str, limit: int = 10) -> list[GitHubIssue]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_ISSUES:
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
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "MaintainerLens",
        },
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

        issues.append(
            GitHubIssue(
                number=number,
                title=title,
                body=body or "",
                labels=tuple(label_names),
                url=url,
            )
        )
        if len(issues) == limit:
            break

    return issues
