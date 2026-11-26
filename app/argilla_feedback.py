from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from app.pr_benchmark import CapturedCase, Grade, RunRow

if TYPE_CHECKING:
    import argilla as rg

DEFAULT_WORKSPACE = "maintainerlens"
DEFAULT_DATASET = "pr-review-development"
_RUBRIC = {
    "change_accuracy": ("Change accuracy", "Describes the visible changes and attributes unverified claims."),
    "author_intent": ("Author intent", "Preserves the stated purpose, qualifications, and crossed-out topics."),
    "actionable_checks": ("Actionable review checks", "Gives concrete, relevant checks grounded in the source."),
}
_FIELDS = {
    "source": "Pull request and source URL",
    "description": "Captured PR description (original Markdown)",
    "files": "Changed-file metadata",
    "summary": "Generated summary",
    "checklist": "Generated review checklist",
}
_CORRECTION_FIELDS = ("corrected_checklist", "notes")
_EXPORT_COLUMNS = ("run_id", "repository", "number", "reviewer_id", *_RUBRIC, *_CORRECTION_FIELDS)
_RESPONSE_FIELDS = {*_RUBRIC, *_CORRECTION_FIELDS}


def _record_fields(snapshot: Path, run: Path) -> dict[str, dict[str, str]]:
    samples = TypeAdapter(list[CapturedCase]).validate_json(snapshot.read_bytes())
    cases = {sample.case.key: sample for sample in samples}
    with run.open(encoding="utf-8") as file:
        rows = [RunRow.model_validate_json(line) for line in file if line.strip()]
    if len({row.run_id for row in rows}) != 1 or len({row.case.key for row in rows}) != len(rows):
        raise ValueError("Use a single benchmark run with one row per pull request.")
    if len(cases) != len(samples) or {row.case.key for row in rows} != cases.keys():
        raise ValueError("The benchmark run must match the captured pull request set.")

    records = {}
    for row in rows:
        sample = cases[row.case.key]
        if row.case != sample.case:
            raise ValueError(f"Run metadata does not match the snapshot for PR #{row.case.number}.")
        if row.brief is None:
            continue
        details = sample.details
        pull = details.pull_request
        file_summary = f"{details.changed_files} files (+{details.additions}/−{details.deletions})"
        if len(details.files) < details.changed_files:
            file_summary += f". Previewing {len(details.files)}."
        files = "\n".join(
            f"{file.path} · {file.status} · +{file.additions}/−{file.deletions}"
            for file in details.files
        )
        record_id = f"{row.run_id}:{row.case.repository}:{row.case.number}"
        records[record_id] = {
            "source": f"{row.case.repository} #{pull.number} · {row.case.focus}\n{pull.title}\n{pull.url}",
            "description": pull.body or "No description provided.",
            "files": f"{file_summary}\n{files}".rstrip(),
            "summary": row.brief.summary,
            "checklist": "\n".join(f"{index}. {step}" for index, step in enumerate(row.brief.checklist, start=1)),
        }
    if not records:
        raise ValueError("This run has no generated briefs to import.")
    return records


def import_reviews(client: rg.Argilla, workspace_name: str, dataset_name: str, fields: dict[str, dict[str, str]]) -> int:
    import argilla as rg

    workspace = client.workspaces(name=workspace_name)
    if workspace is None:
        workspace = rg.Workspace(name=workspace_name, client=client).create()
    dataset = client.datasets(name=dataset_name, workspace=workspace_name)
    if dataset is None:
        settings = rg.Settings(
            guidelines=(
                "Read the description and file list, then check the generated brief against that evidence. "
                "Rate each criterion from 0 to 2: 0 means absent or materially misleading, 1 means useful "
                "with a meaningful correction, and 2 means fully meets the criterion. If you would change "
                "the review checklist, enter the full replacement. Use notes for unsupported claims or "
                "summary corrections. The file list provides metadata, without a diff or test results."
            ),
            fields=[rg.TextField(name=key, title=title, use_markdown=False) for key, title in _FIELDS.items()],
            questions=[
                rg.RatingQuestion(name=key, title=title, description=description, values=[0, 1, 2], required=True)
                for key, (title, description) in _RUBRIC.items()
            ] + [
                rg.TextQuestion(name="corrected_checklist", title="Replacement checklist", required=False),
                rg.TextQuestion(name="notes", title="Evidence or other corrections", required=False),
            ],
        )
        dataset = rg.Dataset(name=dataset_name, workspace=workspace, settings=settings, client=client).create()
    elif (
        {field.name for field in dataset.fields} != set(_FIELDS)
        or {question.name for question in dataset.questions} != _RESPONSE_FIELDS
    ):
        raise ValueError("The existing dataset has a different review schema. Choose another name.")

    existing = {str(record.id) for record in dataset.records}
    if existing and {key.partition(":")[0] for key in existing} != {
        key.partition(":")[0] for key in fields
    }:
        raise ValueError("Use a separate Argilla dataset name for each benchmark run.")
    pending = [rg.Record(id=key, fields=value) for key, value in fields.items() if key not in existing]
    if pending:
        dataset.records.log(records=pending, batch_size=min(len(pending), 256))
    return len(pending)


def export_reviews(dataset: rg.Dataset, output: Path, reviewer_id: str | None = None) -> int:
    rows = []
    for record in dataset.records(with_responses=True):
        run_id, repository, number = str(record.id).split(":", maxsplit=2)
        by_reviewer = defaultdict(dict)
        for response in record.responses:
            reviewer = str(response.user_id)
            if (
                response.status == "submitted"
                and (reviewer_id is None or reviewer == reviewer_id)
                and response.question_name in _RESPONSE_FIELDS
            ):
                by_reviewer[reviewer][response.question_name] = response.value
        for reviewer, answers in by_reviewer.items():
            if not _RUBRIC.keys() <= answers.keys():
                raise ValueError(f"A submitted review for {repository} #{number} has incomplete ratings.")
            grade = Grade.model_validate({"run_id": run_id, "repository": repository, "number": number, **answers})
            rows.append({
                **grade.model_dump(), "reviewer_id": reviewer,
                **{key: answers.get(key, "") for key in _CORRECTION_FIELDS},
            })

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=_EXPORT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import PR briefs into Argilla and export completed reviews.")
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import")
    importer.add_argument("--snapshot", type=Path, required=True)
    importer.add_argument("--run", type=Path, required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument("--output", type=Path, required=True)
    exporter.add_argument("--reviewer-id")
    args = parser.parse_args()

    try:
        import argilla as rg
        from argilla._exceptions import ArgillaError
    except ImportError:
        parser.error("Install requirements-argilla.txt to use Argilla feedback.")

    api_url = os.getenv("ARGILLA_API_URL", "http://127.0.0.1:6900")
    api_key = os.getenv("ARGILLA_API_KEY")
    if not api_key:
        parser.error("Set ARGILLA_API_KEY to your Argilla API key.")
    try:
        client = rg.Argilla(api_url=api_url, api_key=api_key)
        if args.command == "import":
            fields = _record_fields(args.snapshot, args.run)
            count = import_reviews(client, args.workspace, args.dataset, fields)
            print(f"Added {count} records to {args.workspace}/{args.dataset} ({len(fields)} briefs in the run).")
        else:
            dataset = client.datasets(name=args.dataset, workspace=args.workspace)
            if dataset is None:
                raise ValueError(f"Could not find {args.workspace}/{args.dataset}.")
            count = export_reviews(dataset, args.output, args.reviewer_id)
            print(f"Exported {count} submitted reviews to {args.output}.")
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    except ArgillaError as exc:
        parser.error(f"Argilla request failed ({type(exc).__name__}). Check the server and workspace access.")


if __name__ == "__main__":
    main()
