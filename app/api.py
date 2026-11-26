import logging
import os
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.github_client import (
    MAX_ISSUES,
    GitHubIssue,
    fetch_closed_issues,
    fetch_issues,
)
from app.llm_client import (
    IssueAnalysisError,
    IssueAnalysisNotConfiguredError,
    analyze_issue,
    draft_issue_reply,
)
from app.processor import SimilarityMatch, classify_issue, find_similar_issues
from app.review_store import ReviewStoreError, export_reviews_csv, save_review
from app.reply_reviews import ReplyTrial, export_reply_trials, save_reply_trial
from app.semantic_retrieval import EmbeddingCache, find_semantic_fallbacks

IssueCategory = Literal["Bug", "Question", "Feature request", "Other"]

app = FastAPI(title="MaintainerLens API", version="1.0.0")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelatedIssueBatch:
    candidates: tuple[GitHubIssue, ...]
    open_numbers: set[int]
    query_numbers: set[int]


_MAX_RELATED_BATCHES = 16
_related_batches: OrderedDict[str, RelatedIssueBatch] = OrderedDict()
_related_batches_lock = Lock()
_embedding_cache = EmbeddingCache()


class SimilarIssueResponse(BaseModel):
    number: int
    title: str
    url: str
    category: IssueCategory
    is_closed: bool
    score: float
    method: Literal["text", "semantic"] = "text"


class IssueResponse(BaseModel):
    number: int
    title: str
    body: str
    labels: list[str]
    url: str
    category: IssueCategory
    similar_issues: list[SimilarIssueResponse]


class IssueListResponse(BaseModel):
    repository: str
    issues: list[IssueResponse]
    historical_issue_count: int
    related_lookup_id: str | None = None


class AnalyzeIssueRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(max_length=100_000)


class AnalyzeIssueResponse(BaseModel):
    summary: str
    category: IssueCategory
    rationale: str
    summary_truncated: bool


class IssueReference(BaseModel):
    issue_number: int = Field(ge=1)
    issue_title: str = Field(min_length=1, max_length=500)
    issue_url: AnyHttpUrl

    @field_validator("issue_url")
    @classmethod
    def require_github_issue_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        parsed = urlsplit(str(value))
        if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
            raise ValueError("Issue URL must be an https://github.com issue link.")
        if len(parsed.path.strip("/").split("/")) != 4:
            raise ValueError("Issue URL must point to a repository issue.")
        if parsed.path.strip("/").split("/")[2] != "issues":
            raise ValueError("Issue URL must point to a repository issue.")
        return value


class ReviewRequest(IssueReference):
    ai_summary: str = Field(min_length=1, max_length=500)
    ai_category: IssueCategory
    reviewed_summary: str = Field(min_length=1, max_length=500)
    reviewed_category: IssueCategory


class ReplyDraftRequest(AnalyzeIssueRequest):
    related_issues: list[IssueReference] = Field(default_factory=list, max_length=3)

    @field_validator("related_issues")
    @classmethod
    def require_matching_issue_links(cls, issues: list[IssueReference]) -> list[IssueReference]:
        for issue in issues:
            url = issue.issue_url
            if (url.path or "").rstrip("/").split("/")[-1] != str(issue.issue_number):
                raise ValueError("A related issue URL must match its issue number.")
            if url.query or url.fragment or len(str(url)) > 240:
                raise ValueError("Use a direct GitHub issue URL for each related issue.")
        return issues


class ReplyDraftResponse(BaseModel):
    reply: str
    checklist: list[str]


class ReplyReviewRequest(IssueReference, ReplyTrial):
    pass


class ReviewResponse(BaseModel):
    message: str


def _issue_response(
    issue: GitHubIssue,
    similar_issues: list[SimilarityMatch],
    open_issue_numbers: set[int],
) -> IssueResponse:
    return IssueResponse(
        number=issue.number,
        title=issue.title,
        body=issue.body,
        labels=list(issue.labels),
        url=issue.url,
        category=classify_issue(issue),
        similar_issues=[_similar_issue_response(match, open_issue_numbers) for match in similar_issues],
    )


def _similar_issue_response(
    match: SimilarityMatch,
    open_issue_numbers: set[int],
    *,
    method: Literal["text", "semantic"] = "text",
) -> SimilarIssueResponse:
    return SimilarIssueResponse(
        number=match.issue.number,
        title=match.issue.title,
        url=match.issue.url,
        category=classify_issue(match.issue),
        is_closed=match.issue.number not in open_issue_numbers,
        score=match.score,
        method=method,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/issues", response_model=IssueListResponse)
def list_repository_issues(
    repository: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=MAX_ISSUES),
) -> IssueListResponse:
    try:
        open_issues = fetch_issues(repository, limit)
        if not open_issues:
            return IssueListResponse(
                repository=repository,
                issues=[],
                historical_issue_count=0,
            )
        closed_issues = fetch_closed_issues(repository)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch issues from GitHub: {exc}",
        ) from exc

    open_issue_numbers = {issue.number for issue in open_issues}
    candidates = list(open_issues)
    seen_numbers = set(open_issue_numbers)
    for issue in closed_issues:
        if issue.number not in seen_numbers:
            candidates.append(issue)
            seen_numbers.add(issue.number)

    matches_by_number = find_similar_issues(candidates)
    lookup_id = None
    if os.getenv("MAINTAINERLENS_SEMANTIC_SEARCH") == "1" and len(candidates) > 1:
        query_numbers = {issue.number for issue in open_issues if not matches_by_number[issue.number]}
        if query_numbers:
            lookup_id = uuid4().hex
            with _related_batches_lock:
                _related_batches[lookup_id] = RelatedIssueBatch(
                    tuple(candidates), open_issue_numbers, query_numbers
                )
                if len(_related_batches) > _MAX_RELATED_BATCHES:
                    _related_batches.popitem(last=False)
    return IssueListResponse(
        repository=repository,
        issues=[
            _issue_response(
                issue,
                matches_by_number[issue.number],
                open_issue_numbers,
            )
            for issue in open_issues
        ],
        historical_issue_count=len(candidates) - len(open_issues),
        related_lookup_id=lookup_id,
    )


@app.get("/api/issues/related/{lookup_id}", response_model=dict[int, list[SimilarIssueResponse]])
def find_background_related_issues(lookup_id: str) -> dict[int, list[SimilarIssueResponse]]:
    with _related_batches_lock:
        batch = _related_batches.get(lookup_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Fetch issues again to refresh related matches.")

    try:
        matches = find_semantic_fallbacks(
            batch.candidates, issue_numbers=batch.query_numbers, cache=_embedding_cache
        )
    except Exception:
        logger.exception("Background semantic retrieval failed")
        raise HTTPException(status_code=503, detail="Semantic search is unavailable.") from None

    return {
        number: [
            _similar_issue_response(match, batch.open_numbers, method="semantic") for match in results
        ]
        for number, results in matches.items()
    }


@app.post("/api/issues/analyze", response_model=AnalyzeIssueResponse)
def analyze_repository_issue(
    request: AnalyzeIssueRequest,
) -> AnalyzeIssueResponse:
    try:
        analysis = analyze_issue(request.title, request.body)
    except IssueAnalysisNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IssueAnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AnalyzeIssueResponse(
        summary=analysis.summary,
        category=analysis.category,
        rationale=analysis.rationale,
        summary_truncated=analysis.summary_truncated,
    )


@app.post("/api/reviews", response_model=ReviewResponse)
def save_issue_review(request: ReviewRequest) -> ReviewResponse:
    issue = GitHubIssue(
        number=request.issue_number,
        title=request.issue_title,
        body="",
        labels=(),
        url=str(request.issue_url),
    )
    try:
        save_review(
            issue,
            request.ai_summary,
            request.ai_category,
            request.reviewed_summary,
            request.reviewed_category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReviewStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ReviewResponse(message="Review saved locally.")


@app.post("/api/issues/draft-reply", response_model=ReplyDraftResponse)
def draft_repository_reply(request: ReplyDraftRequest) -> ReplyDraftResponse:
    try:
        draft = draft_issue_reply(
            request.title,
            request.body,
            [(issue.issue_number, issue.issue_title) for issue in request.related_issues],
        )
    except IssueAnalysisNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IssueAnalysisError:
        raise HTTPException(status_code=502, detail="The AI reply could not be generated. Please retry.") from None

    known_links = {issue.issue_number: issue.issue_url for issue in request.related_issues}
    links = [
        f"[#{number}]({known_links[number]})"
        for number in dict.fromkeys(draft.related_issue_numbers) if number in known_links
    ]
    reply = draft.reply
    if links:
        reply += "\n\nPossibly related: " + ", ".join(links) + "."
    return ReplyDraftResponse(reply=reply, checklist=draft.checklist)


@app.post("/api/reply-reviews", response_model=ReviewResponse)
def save_reply_review(request: ReplyReviewRequest) -> ReviewResponse:
    issue = GitHubIssue(request.issue_number, request.issue_title, "", (), str(request.issue_url))
    try:
        save_reply_trial(issue, request)
    except ReviewStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ReviewResponse(message="Reply review saved locally.")


@app.get("/api/reply-reviews/export")
def download_reply_reviews() -> Response:
    try:
        export = export_reply_trials()
    except ReviewStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        export,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="maintainer_reply_trials.csv"'},
    )


@app.get("/api/reviews/export")
def download_reviews() -> FileResponse:
    try:
        path = export_reviews_csv()
    except ReviewStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        filename=path.name,
        media_type="text/csv",
    )


__all__ = ["app"]
