from typing import Literal
from urllib.parse import urlsplit

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
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
)
from app.processor import SimilarityMatch, classify_issue, find_similar_issues
from app.review_store import ReviewStoreError, export_reviews_csv, save_review

IssueCategory = Literal["Bug", "Question", "Feature request", "Other"]

app = FastAPI(title="MaintainerLens API", version="1.0.0")


class SimilarIssueResponse(BaseModel):
    number: int
    title: str
    url: str
    category: IssueCategory
    is_closed: bool
    score: float


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


class AnalyzeIssueRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(max_length=100_000)


class AnalyzeIssueResponse(BaseModel):
    summary: str
    category: IssueCategory
    rationale: str
    summary_truncated: bool


class ReviewRequest(BaseModel):
    issue_number: int = Field(ge=1)
    issue_title: str = Field(min_length=1, max_length=500)
    issue_url: AnyHttpUrl
    ai_summary: str = Field(min_length=1, max_length=500)
    ai_category: IssueCategory
    reviewed_summary: str = Field(min_length=1, max_length=500)
    reviewed_category: IssueCategory

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
        similar_issues=[
            SimilarIssueResponse(
                number=match.issue.number,
                title=match.issue.title,
                url=match.issue.url,
                category=classify_issue(match.issue),
                is_closed=match.issue.number not in open_issue_numbers,
                score=match.score,
            )
            for match in similar_issues
        ],
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
    )


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
