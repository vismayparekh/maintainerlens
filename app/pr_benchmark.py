import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

import requests
from pydantic import BaseModel, Field, TypeAdapter

from app.github_client import PullRequestDetails, fetch_pull_request_details
from app.llm_client import IssueAnalysisError, PullRequestAnalysis, _configured_model, analyze_pull_request


class Case(BaseModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    number: int = Field(gt=0)
    focus: Literal["documentation", "bug fix", "tests", "refactor"]

    @property
    def key(self) -> tuple[str, int]:
        return self.repository.casefold(), self.number


class CapturedCase(BaseModel):
    case: Case
    captured_at_utc: datetime
    details: PullRequestDetails


class RunRow(BaseModel):
    run_id: str
    case: Case
    model: str
    elapsed_ms: int
    brief: PullRequestAnalysis | None = None
    error: str | None = None


class Grade(BaseModel):
    run_id: str
    repository: str
    number: int
    change_accuracy: int = Field(ge=0, le=2)
    author_intent: int = Field(ge=0, le=2)
    actionable_checks: int = Field(ge=0, le=2)

    @property
    def key(self) -> tuple[str, int]:
        return self.repository.casefold(), self.number


_SNAPSHOT = TypeAdapter(list[CapturedCase])
_AXES = ("change_accuracy", "author_intent", "actionable_checks")


def _read_cases(path: Path) -> list[Case]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        cases = [Case.model_validate(row) for row in csv.DictReader(file)]
    if not cases or len({case.key for case in cases}) != len(cases):
        raise ValueError("The manifest must contain at least one case and no duplicate PRs.")
    return cases


def _capture_cases(cases: list[Case], snapshot_path: Path) -> list[CapturedCase]:
    if snapshot_path.exists():
        snapshot = _SNAPSHOT.validate_json(snapshot_path.read_bytes())
        if [sample.case for sample in snapshot] != cases:
            raise ValueError("The snapshot and manifest contain different cases or ordering.")
        return snapshot

    snapshot = [
        CapturedCase(
            case=case,
            details=fetch_pull_request_details(case.repository, case.number),
            captured_at_utc=datetime.now(timezone.utc),
        )
        for case in cases
    ]
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with snapshot_path.open("xb") as file:
        file.write(_SNAPSHOT.dump_json(snapshot, indent=2) + b"\n")
    return snapshot


def generate(manifest: Path, snapshot_path: Path, output: Path) -> None:
    if snapshot_path.resolve() == output.resolve():
        raise ValueError("Choose different snapshot and output paths.")
    if output.exists():
        raise ValueError("Choose a new output path for each benchmark run.")
    model = _configured_model()
    cases = _capture_cases(_read_cases(manifest), snapshot_path)
    run_id = uuid4().hex
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        for sample in cases:
            started = perf_counter()
            brief = None
            error = None
            try:
                brief = analyze_pull_request(sample.details)
            except IssueAnalysisError:
                error = "provider_or_validation_error"
            result = RunRow(
                run_id=run_id, case=sample.case, model=model,
                elapsed_ms=round((perf_counter() - started) * 1000), brief=brief, error=error,
            )
            file.write(result.model_dump_json() + "\n")
            file.flush()
            print(f"{sample.case.repository} #{sample.case.number}: {'generated' if brief else error}", flush=True)
    print(f"Run ID: {run_id}")


def score(output: Path, grades_file: Path) -> str:
    with output.open(encoding="utf-8") as file:
        rows = [RunRow.model_validate_json(line) for line in file if line.strip()]
    run_ids = {row.run_id for row in rows}
    if len(run_ids) != 1 or len({row.case.key for row in rows}) != len(rows):
        raise ValueError("Use one nonempty run with unique PRs.")
    generated = {row.case.key: row for row in rows if row.brief is not None}
    with grades_file.open(newline="", encoding="utf-8-sig") as file:
        grades = [Grade.model_validate(row) for row in csv.DictReader(file)]
    if len({grade.key for grade in grades}) != len(grades) or any(
        grade.run_id not in run_ids or grade.key not in generated for grade in grades
    ):
        raise ValueError("Each grade must identify a unique generated brief from this run.")

    lines = [f"Briefs generated: {len(generated)}/{len(rows)}", f"Briefs graded: {len(grades)}/{len(generated)}"]
    by_focus = Counter(generated[grade.key].case.focus for grade in grades)
    lines.extend(f"  {focus}: {count} graded" for focus, count in sorted(by_focus.items()))
    if grades:
        for axis in _AXES:
            values = [getattr(grade, axis) for grade in grades]
            lines.append(f"{axis.replace('_', ' ').title()}: {sum(values)}/{2 * len(grades)} points, {values.count(2)}/{len(grades)} full credit")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and score PR review briefs against captured public PR metadata.")
    commands = parser.add_subparsers(dest="command", required=True)
    generate_parser = commands.add_parser("generate")
    generate_parser.add_argument("manifest", type=Path)
    generate_parser.add_argument("--snapshot", type=Path, required=True)
    generate_parser.add_argument("--output", type=Path, required=True)
    score_parser = commands.add_parser("score")
    score_parser.add_argument("output", type=Path)
    score_parser.add_argument("grades", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            generate(args.manifest, args.snapshot, args.output)
        else:
            print(score(args.output, args.grades))
    except (OSError, ValueError, csv.Error, requests.RequestException, IssueAnalysisError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
