import requests
from pydantic import BaseModel, Field, ValidationError

from app.github_client import API_URL, REQUEST_TIMEOUT, _repository_slug, _request_headers

MAX_DISCUSSIONS = 20
_FIELDS = """
    number title url updatedAt isAnswered
    category { name isAnswerable }
    author { login }
    labels(first: 20) { nodes { name } }
"""
_COMMENT = "body url author { login }"
_LIST_QUERY = f"""
query MaintainerLensDiscussions($owner: String!, $name: String!, $limit: Int!) {{
  repository(owner: $owner, name: $name) {{
    isPrivate hasDiscussionsEnabled
    discussions(first: $limit, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
      nodes {{ {_FIELDS} comments {{ totalCount }} }}
    }}
  }}
}}
"""
_DETAIL_QUERY = f"""
query MaintainerLensDiscussion($owner: String!, $name: String!, $number: Int!) {{
  repository(owner: $owner, name: $name) {{
    isPrivate hasDiscussionsEnabled
    discussion(number: $number) {{
      {_FIELDS} body
      answer {{ {_COMMENT} }}
      comments(last: 5) {{ totalCount nodes {{ {_COMMENT} }} }}
    }}
  }}
}}
"""


class DiscussionsError(RuntimeError):
    pass


class DiscussionsAccessError(DiscussionsError):
    pass


class DiscussionsNotFound(DiscussionsError):
    pass


class Discussion(BaseModel):
    number: int
    title: str
    url: str
    category: str
    author: str | None
    updated_at: str
    answerable: bool
    answered: bool
    comment_count: int
    labels: list[str]


class DiscussionComment(BaseModel):
    body: str
    url: str
    author: str | None


class DiscussionDetails(Discussion):
    body: str
    answer: DiscussionComment | None
    recent_comments: list[DiscussionComment] = Field(default_factory=list)


class DiscussionList(BaseModel):
    discussions_enabled: bool
    discussions: list[Discussion]


def _query_repository(repository: str, query: str, **variables: int) -> dict:
    owner, name = _repository_slug(repository).split("/")
    headers = _request_headers(use_demo_token=True)
    if "Authorization" not in headers:
        raise DiscussionsAccessError("Set GITHUB_TOKEN on the server to load GitHub Discussions.")
    response = requests.post(
        f"{API_URL}/graphql",
        headers=headers,
        json={"query": query, "variables": {"owner": owner, "name": name, **variables}},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code in {401, 403}:
        raise DiscussionsAccessError("Check that GITHUB_TOKEN has read access to GitHub Discussions.")
    response.raise_for_status()
    try:
        payload = response.json()
        errors = payload.get("errors", [])
        data = payload.get("data") or {}
        result = data.get("repository")
        error_types = {error.get("type") or (error.get("extensions") or {}).get("code") for error in errors}
    except (AttributeError, TypeError, ValueError) as exc:
        raise DiscussionsError("GitHub returned an unexpected Discussions response.") from exc
    if result is None and ("repository" in data or "NOT_FOUND" in error_types):
        if not error_types or error_types == {"NOT_FOUND"}:
            raise DiscussionsNotFound("Public GitHub repository not found.")
    if isinstance(result, dict) and result.get("isPrivate") is True:
        raise DiscussionsNotFound("Public GitHub repository not found.")
    if isinstance(result, dict) and result.get("isPrivate") is False:
        if result.get("hasDiscussionsEnabled") is False:
            return result
        if "discussion" in result and result["discussion"] is None and error_types == {"NOT_FOUND"}:
            return result
    if error_types & {"FORBIDDEN", "INSUFFICIENT_SCOPES"}:
        raise DiscussionsAccessError("Check that GITHUB_TOKEN has read access to GitHub Discussions.")
    if (
        errors or not isinstance(result, dict)
        or result.get("isPrivate") is not False or result.get("hasDiscussionsEnabled") is not True
    ):
        raise DiscussionsError("GitHub could not load Discussions for this repository.")
    return result


def _discussion(item: dict) -> dict:
    return {
        "number": item["number"],
        "title": item["title"],
        "url": item["url"],
        "category": item["category"]["name"],
        "author": (item["author"] or {}).get("login"),
        "updated_at": item["updatedAt"],
        "answerable": item["category"]["isAnswerable"],
        "answered": item["isAnswered"] is True,
        "comment_count": item["comments"]["totalCount"],
        "labels": [label["name"] for label in item["labels"]["nodes"] if label is not None],
    }


def _comment(item: dict) -> DiscussionComment:
    return DiscussionComment(body=item["body"], url=item["url"], author=(item["author"] or {}).get("login"))


def fetch_discussions(repository: str, limit: int) -> DiscussionList:
    result = _query_repository(repository, _LIST_QUERY, limit=limit)
    if not result["hasDiscussionsEnabled"]:
        return DiscussionList(discussions_enabled=False, discussions=[])
    try:
        nodes = result["discussions"]["nodes"]
        return DiscussionList(
            discussions_enabled=True,
            discussions=[Discussion(**_discussion(item)) for item in nodes if item is not None],
        )
    except (AttributeError, KeyError, TypeError, ValidationError) as exc:
        raise DiscussionsError("GitHub returned an unexpected Discussions list.") from exc


def fetch_discussion(repository: str, number: int) -> DiscussionDetails:
    result = _query_repository(repository, _DETAIL_QUERY, number=number)
    if not result["hasDiscussionsEnabled"]:
        raise DiscussionsNotFound("GitHub Discussions are disabled for this repository.")
    item = result.get("discussion")
    if item is None:
        raise DiscussionsNotFound("GitHub discussion not found.")
    try:
        return DiscussionDetails(
            **_discussion(item),
            body=item["body"],
            answer=_comment(item["answer"]) if item["answer"] else None,
            recent_comments=[_comment(comment) for comment in item["comments"]["nodes"] if comment is not None],
        )
    except (AttributeError, KeyError, TypeError, ValidationError) as exc:
        raise DiscussionsError("GitHub returned unexpected discussion details.") from exc
