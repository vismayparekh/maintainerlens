from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from random import Random
from typing import TYPE_CHECKING

import requests

from app.evaluate import CSV_COLUMNS
from app.github_client import fetch_labeled_issues
from app.processor import ISSUE_CATEGORIES

if TYPE_CHECKING:
    import argilla as rg

WORKSPACE = "maintainerlens-issue-review"
DATASET = "bug-question-blind-01"
MIN_REVIEWERS = 2
SOURCE_LABELS = {
    "pre-commit/pre-commit": ("bug", "question"),
    "psf/black": ("T: bug", "T: user support"),
    "aio-libs/aiohttp": ("bug", "question"),
    "python/mypy": ("bug", "question"),
}
FIELDS = {"title": "Issue title", "body": "Issue description"}
QUESTIONS = {"category", "evidence"}
LABELS = (*ISSUE_CATEGORIES, "Unclear")
CASE_ID = re.compile(r"([\w.-]+/[\w.-]+)#([1-9]\d*)\Z")
_SECURITY = re.compile(r"\b(?:cve|vulnerability|exploit|security)\b", re.IGNORECASE)
GUIDELINES = (
    "Choose the action implied by the reported evidence. Read the issue text and review it independently. "
    "Bug: a concrete failure of existing behavior, such as a reproducible mismatch or regression. "
    "Question: help with usage, configuration, or intended behavior without clear evidence of a product defect. "
    "A traceback alone is insufficient to label a bug. Feature request: a new capability or behavior. "
    "Other: maintenance or documentation work outside those categories. "
    "Unclear: evidence is insufficient or two categories remain plausible. "
    "Cite one detail that drove your choice. Use the captured text and avoid looking up GitHub labels or other reviews."
)


def collect(path: Path) -> int:
    if path.exists():
        raise ValueError("Choose a fresh output path for the captured review set.")

    def sample(job):
        repo, label = job
        issues = fetch_labeled_issues(repo, label, 40)
        eligible = [
            issue for issue in issues
            if 120 <= len(issue.body.strip()) <= 12_000
            and set(issue.labels).intersection(SOURCE_LABELS[repo]) == {label}
            and not any(_SECURITY.search(text) for text in (issue.title, *issue.labels))
        ]
        if len(eligible) < 4:
            raise ValueError(f"Fewer than four eligible issues for {repo} / {label}.")
        return repo, Random(f"issue-review-01:{repo}:{label}").sample(eligible, 4)

    jobs = [(repo, label) for repo, labels in SOURCE_LABELS.items() for label in labels]
    with ThreadPoolExecutor(max_workers=4) as pool:
        cases = {
            f"{repo}#{issue.number}": {"title": issue.title, "body": issue.body, "url": issue.url}
            for repo, issues in pool.map(sample, jobs)
            for issue in issues
        }
    if len(cases) != 4 * len(jobs):
        raise ValueError("Duplicate issue IDs in the captured review set.")
    entries = list(cases.items())
    Random(41).shuffle(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        json.dump(dict(entries), file, ensure_ascii=False, indent=2)
        file.write("\n")
    return len(cases)


def issue_fields(snapshot: Path) -> dict[str, dict[str, str]]:
    raw = snapshot.read_bytes()
    cases = json.loads(raw)
    if not isinstance(cases, dict) or not cases:
        raise ValueError("Use a nonempty captured issue snapshot.")
    batch = hashlib.sha256(raw).hexdigest()[:16]
    fields = {}
    for key, case in cases.items():
        match = CASE_ID.fullmatch(key)
        if not match or not isinstance(case, dict) or any(
            not isinstance(case.get(name), str) or not case[name].strip() for name in (*FIELDS, "url")
        ):
            raise ValueError(f"Invalid captured issue {key}.")
        repo, number = match.groups()
        if case["url"] != f"https://github.com/{repo}/issues/{number}":
            raise ValueError(f"Unexpected source URL for {key}.")
        fields[f"{batch}:{key}"] = {name: case[name] for name in FIELDS}
    return fields


def import_issues(client: rg.Argilla, workspace_name: str, dataset_name: str, snapshot: Path) -> tuple[rg.Dataset, int]:
    import argilla as rg

    fields = issue_fields(snapshot)
    workspace = client.workspaces(name=workspace_name)
    if workspace is None:
        workspace = rg.Workspace(name=workspace_name, client=client).create()
    dataset = client.datasets(name=dataset_name, workspace=workspace_name)
    if dataset is None:
        settings = rg.Settings(
            guidelines=GUIDELINES,
            fields=[rg.TextField(name=name, title=title, use_markdown=False) for name, title in FIELDS.items()],
            questions=[
                rg.LabelQuestion(name="category", title="Triage category", labels=list(LABELS), required=True),
                rg.TextQuestion(name="evidence", title="Evidence for your choice", required=True),
            ],
            distribution=rg.TaskDistribution(min_submitted=MIN_REVIEWERS),
        )
        dataset = rg.Dataset(name=dataset_name, workspace=workspace, settings=settings, client=client).create()
    elif (
        {field.name for field in dataset.fields} != set(FIELDS)
        or {question.name for question in dataset.questions} != QUESTIONS
        or dataset.settings.distribution.min_submitted != MIN_REVIEWERS
    ):
        raise ValueError("Choose a new dataset name for this review schema.")

    existing = {str(record.id) for record in dataset.records}
    if existing - fields.keys():
        raise ValueError("Choose a new dataset name for a different captured review set.")
    pending = [rg.Record(id=key, fields=value) for key, value in fields.items() if key not in existing]
    if pending:
        dataset.records.log(records=pending)
    return dataset, len(pending)


def review_rows(dataset: rg.Dataset) -> tuple[list[dict], list[dict], dict[str, int]]:
    reviews, consensus = [], []
    counts = dict.fromkeys(("pending", "agreed", "needs_review"), 0)
    for record in dataset.records(with_responses=True):
        match = CASE_ID.fullmatch(str(record.id).partition(":")[2])
        if not match:
            raise ValueError("Unexpected record ID. Use the issue review dataset.")
        repo, number = match.groups()
        issue = {
            "repository": repo,
            "number": number,
            "title": record.fields["title"],
            "url": f"https://github.com/{repo}/issues/{number}",
        }
        answers = defaultdict(dict)
        for response in record.responses:
            if response.status == "submitted" and response.question_name in QUESTIONS:
                answers[str(response.user_id)][response.question_name] = response.value
        for reviewer, answer in answers.items():
            if answer.get("category") not in LABELS or not (answer.get("evidence") or "").strip():
                raise ValueError(f"Submitted review for {repo} #{number} is incomplete.")
            reviews.append({**issue, "reviewer_id": reviewer, **answer})
        if len(answers) < MIN_REVIEWERS:
            counts["pending"] += 1
            continue
        choices = {answer["category"] for answer in answers.values()}
        if len(choices) == 1 and choices <= set(ISSUE_CATEGORIES):
            counts["agreed"] += 1
            consensus.append({**issue, "expected_category": choices.pop(), "duplicate_group": ""})
        else:
            counts["needs_review"] += 1
    return reviews, consensus, counts


def write_rows(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect blind issue reviews in Argilla.")
    parser.add_argument("--workspace", default=WORKSPACE)
    parser.add_argument("--dataset", default=DATASET)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect").add_argument("snapshot", type=Path)
    commands.add_parser("import").add_argument("snapshot", type=Path)
    commands.add_parser("status")
    export = commands.add_parser("export")
    export.add_argument("--reviews", type=Path, required=True)
    export.add_argument("--consensus", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "collect":
        try:
            print(f"Captured {collect(args.snapshot)} issues in {args.snapshot}.")
        except (OSError, ValueError, requests.RequestException) as exc:
            parser.error(str(exc))
        return

    try:
        import argilla as rg
        from argilla._exceptions import ArgillaError
    except ImportError:
        parser.error("Install requirements-argilla.txt to use the issue review queue.")
    api_key = os.getenv("ARGILLA_API_KEY")
    if not api_key:
        parser.error("Set ARGILLA_API_KEY to your Argilla API key.")
    try:
        api_url = os.getenv("ARGILLA_API_URL", "http://127.0.0.1:6900")
        client = rg.Argilla(api_url=api_url, api_key=api_key)
        if args.command == "import":
            dataset, added = import_issues(client, args.workspace, args.dataset, args.snapshot)
            print(f"Added {added} records. {api_url.rstrip('/')}/dataset/{dataset.id}/annotation-mode")
            return
        dataset = client.datasets(name=args.dataset, workspace=args.workspace)
        if dataset is None:
            raise ValueError("Issue review dataset not found.")
        reviews, consensus, counts = review_rows(dataset)
        if args.command == "export":
            if args.reviews.resolve() == args.consensus.resolve() or args.reviews.exists() or args.consensus.exists():
                raise ValueError("Choose two distinct, new paths for the review exports.")
            write_rows(args.reviews, (*CSV_COLUMNS[:4], "reviewer_id", "category", "evidence"), reviews)
            write_rows(args.consensus, CSV_COLUMNS, consensus)
        print(f"{len(reviews)} submitted reviews from {len({row['reviewer_id'] for row in reviews})} reviewers.")
        for name, count in counts.items():
            print(f"{name}: {count}")
    except (ArgillaError, OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
