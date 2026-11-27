import os
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

API_URL = "https://api.github.com"
MAX_ISSUES = 20
MAX_HISTORICAL_ISSUES = 100
MAX_PULL_REQUESTS = 20
MAX_PULL_REQUEST_FILES = 20
REQUEST_TIMEOUT = 15
_ISSUE_PAGE_SIZE = 100
_REPOSITORY_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
_ISSUE_REFERENCES = re.compile(
    r"https://github\.com/(?P<link_repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/"
    r"(?P<link_number>[1-9][0-9]{0,15})(?![\w/])|"
    r"\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s*:?\s+"
    r"(?:(?P<closing_repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?"
    r"#(?P<closing_number>[1-9][0-9]{0,15})\b",
    re.IGNORECASE,
)
_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "MaintainerLens",
}

load_dotenv()


@dataclass(frozen=True)
class GitHubIssue:
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    url: str


@dataclass(frozen=True)
class GitHubPullRequest:
    number: int
    title: str
    body: str
    url: str
    status: Literal["draft", "open", "closed", "merged"]
    author: str | None
    updated_at: str


@dataclass(frozen=True)
class PullRequestFile:
    path: str
    status: str
    additions: int
    deletions: int


@dataclass(frozen=True)
class LinkedIssueReference:
    repository: str
    number: int
    url: str


@dataclass(frozen=True)
class PullRequestDetails:
    pull_request: GitHubPullRequest
    base_branch: str
    head_branch: str
    changed_files: int
    additions: int
    deletions: int
    files: tuple[PullRequestFile, ...]
    issue_references: tuple[LinkedIssueReference, ...]


def _request_headers() -> dict[str, str]:
    headers = _API_HEADERS.copy()
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


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


def _fetch_repository_issues(
    repository: str,
    *,
    state: str,
    sort: str,
    limit: int,
) -> list[GitHubIssue]:
    slug = _repository_slug(repository)
    issues: list[GitHubIssue] = []
    page = 1
    while len(issues) < limit:
        response = requests.get(
            f"{API_URL}/repos/{slug}/issues",
            params={
                "state": state,
                "sort": sort,
                "direction": "desc",
                "per_page": _ISSUE_PAGE_SIZE,
                "page": page,
            },
            headers=_request_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("GitHub returned an unexpected issues response.")
        if not payload:
            break

        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("GitHub returned an unexpected issue.")
            if "pull_request" in item:
                continue

            issues.append(_parse_issue(item))
            if len(issues) == limit:
                break

        if len(payload) < _ISSUE_PAGE_SIZE:
            break
        page += 1

    return issues


def fetch_repository_labels(repository: str) -> list[str]:
    slug = _repository_slug(repository)
    labels: list[str] = []
    page = 1
    while True:
        response = requests.get(
            f"{API_URL}/repos/{slug}/labels",
            params={"per_page": _ISSUE_PAGE_SIZE, "page": page},
            headers=_request_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("GitHub returned an unexpected repository label response.")
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
                raise ValueError("GitHub returned an invalid repository label.")
            if not item.get("archived_at"):
                labels.append(item["name"])
        if "next" not in response.links:
            return labels
        page += 1


def fetch_issues(repository: str, limit: int = 10) -> list[GitHubIssue]:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_ISSUES
    ):
        raise ValueError(f"Issue limit must be between 1 and {MAX_ISSUES}.")

    return _fetch_repository_issues(
        repository,
        state="open",
        sort="created",
        limit=limit,
    )


def fetch_closed_issues(
    repository: str,
    limit: int = MAX_HISTORICAL_ISSUES,
) -> list[GitHubIssue]:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_HISTORICAL_ISSUES
    ):
        raise ValueError(
            f"Historical issue limit must be between 1 and {MAX_HISTORICAL_ISSUES}."
        )

    return _fetch_repository_issues(
        repository,
        state="closed",
        sort="updated",
        limit=limit,
    )


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
        headers=_request_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    item = response.json()
    if not isinstance(item, dict):
        raise ValueError("GitHub returned an unexpected issue response.")
    if "pull_request" in item:
        raise ValueError(f"#{issue_number} is a pull request, not an issue.")
    return _parse_issue(item)


def _parse_pull_request(item: object) -> GitHubPullRequest:
    if not isinstance(item, dict):
        raise ValueError("GitHub returned an unexpected pull request.")
    base = item.get("base")
    base_repository = base.get("repo") if isinstance(base, dict) else None
    if not isinstance(base_repository, dict) or base_repository.get("private") is not False:
        raise ValueError("MaintainerLens can only load pull requests from public repositories.")

    number = item.get("number")
    title = item.get("title")
    body = item.get("body")
    url = item.get("html_url")
    updated_at = item.get("updated_at")
    state = item.get("state")
    if (
        type(number) is not int or number < 1
        or not isinstance(title, str)
        or not isinstance(url, str)
        or not isinstance(updated_at, str)
        or (body is not None and not isinstance(body, str))
        or state not in ("open", "closed")
    ):
        raise ValueError("GitHub returned an unexpected pull request format.")

    status = state
    if state == "open" and item.get("draft") is True:
        status = "draft"
    if state == "closed" and (item.get("merged") is True or item.get("merged_at")):
        status = "merged"
    user = item.get("user")
    author = user.get("login") if isinstance(user, dict) else None
    return GitHubPullRequest(
        number, title, body or "", url, status, author if isinstance(author, str) else None, updated_at
    )


def _get_pull_request_json(slug: str, path: str, **params):
    response = requests.get(
        f"{API_URL}/repos/{slug}/pulls{path}",
        params=params or None,
        headers=_request_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def fetch_pull_requests(repository: str, limit: int = 10) -> list[GitHubPullRequest]:
    if type(limit) is not int or not 1 <= limit <= MAX_PULL_REQUESTS:
        raise ValueError(f"Pull request limit must be between 1 and {MAX_PULL_REQUESTS}.")
    slug = _repository_slug(repository)
    items = _get_pull_request_json(
        slug, "", state="open", sort="updated", direction="desc", per_page=limit
    )
    if not isinstance(items, list):
        raise ValueError("GitHub returned an unexpected pull request list.")
    return [_parse_pull_request(item) for item in items[:limit]]


def _linked_issue_references(body: str, repository: str, pr_number: int) -> tuple[LinkedIssueReference, ...]:
    references: dict[tuple[str, int], LinkedIssueReference] = {}
    for match in _ISSUE_REFERENCES.finditer(body):
        slug = match["link_repo"] or match["closing_repo"] or repository
        if any(part in {".", ".."} for part in slug.split("/")):
            continue
        number = int(match["link_number"] or match["closing_number"])
        key = (slug.casefold(), number)
        if key != (repository.casefold(), pr_number):
            references.setdefault(key, LinkedIssueReference(slug, number, f"https://github.com/{slug}/issues/{number}"))
        if len(references) == 10:
            break
    return tuple(references.values())


def _parse_pull_request_file(item: object) -> PullRequestFile:
    if not isinstance(item, dict):
        raise ValueError("GitHub returned an unexpected changed file.")
    filename = item.get("filename")
    status = item.get("status")
    additions = item.get("additions")
    deletions = item.get("deletions")
    if (
        not isinstance(filename, str) or not isinstance(status, str)
        or type(additions) is not int or additions < 0
        or type(deletions) is not int or deletions < 0
    ):
        raise ValueError("GitHub returned an unexpected changed-file format.")
    return PullRequestFile(filename, status, additions, deletions)


def fetch_pull_request_details(repository: str, number: int) -> PullRequestDetails:
    if type(number) is not int or number < 1:
        raise ValueError("Pull request number must be a positive integer.")
    slug = _repository_slug(repository)
    item = _get_pull_request_json(slug, f"/{number}")
    pull_request = _parse_pull_request(item)
    base = item.get("base")
    head = item.get("head")
    base_branch = base.get("ref") if isinstance(base, dict) else None
    head_branch = head.get("ref") if isinstance(head, dict) else None
    changed_files = item.get("changed_files")
    additions = item.get("additions")
    deletions = item.get("deletions")
    if not isinstance(base_branch, str) or not isinstance(head_branch, str) or any(
        type(count) is not int or count < 0 for count in (changed_files, additions, deletions)
    ):
        raise ValueError("GitHub returned unexpected pull request details.")

    files = ()
    if changed_files:
        payload = _get_pull_request_json(slug, f"/{number}/files", per_page=MAX_PULL_REQUEST_FILES)
        if not isinstance(payload, list):
            raise ValueError("GitHub returned an unexpected changed-file list.")
        files = tuple(_parse_pull_request_file(file) for file in payload[:MAX_PULL_REQUEST_FILES])
    return PullRequestDetails(
        pull_request, base_branch, head_branch, changed_files, additions, deletions, files,
        _linked_issue_references(pull_request.body, slug, number),
    )
