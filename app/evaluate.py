import argparse
import csv
from collections import defaultdict
from collections.abc import Hashable
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import TypeVar

import requests

from app.github_client import (
    MAX_ISSUES,
    GitHubIssue,
    fetch_issue_by_number,
    fetch_issues,
)
from app.processor import ISSUE_CATEGORIES, classify_issue, find_similar_issues

CSV_COLUMNS = (
    "repository",
    "number",
    "title",
    "url",
    "expected_category",
    "duplicate_group",
)
MetricItem = TypeVar("MetricItem", bound=Hashable)


@dataclass(frozen=True)
class Annotation:
    repository: str
    number: int
    expected_category: str
    duplicate_group: str


@dataclass(frozen=True)
class Metrics:
    precision: float | None
    recall: float | None
    f1: float | None


def export_template(repository: str, limit: int, output: Path) -> int:
    issues = fetch_issues(repository, limit)
    if not issues:
        raise ValueError(f"No open issues found for {repository}.")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        for issue in issues:
            writer.writerow(
                {
                    "repository": repository,
                    "number": issue.number,
                    "title": issue.title,
                    "url": issue.url,
                    "expected_category": "",
                    "duplicate_group": "",
                }
            )
    return len(issues)


def read_annotations(path: Path) -> list[Annotation]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError("The annotation CSV is empty.")

        missing_columns = set(CSV_COLUMNS) - set(reader.fieldnames)
        if missing_columns:
            raise ValueError(
                "The annotation CSV is missing columns: "
                + ", ".join(sorted(missing_columns))
            )

        annotations: list[Annotation] = []
        seen: set[tuple[str, int]] = set()
        for line_number, row in enumerate(reader, start=2):
            repository = (row["repository"] or "").strip()
            raw_number = (row["number"] or "").strip()
            category = (row["expected_category"] or "").strip()
            duplicate_group = (row["duplicate_group"] or "").strip()

            if not repository or not raw_number:
                raise ValueError(
                    f"CSV row {line_number} must include repository and issue number."
                )
            try:
                number = int(raw_number)
            except ValueError as exc:
                raise ValueError(
                    f"CSV row {line_number} has an invalid issue number."
                ) from exc
            if number < 1:
                raise ValueError(
                    f"CSV row {line_number} must have a positive issue number."
                )
            if category not in ISSUE_CATEGORIES:
                raise ValueError(
                    f"CSV row {line_number} expected_category must be one of: "
                    + ", ".join(ISSUE_CATEGORIES)
                )

            key = (repository, number)
            if key in seen:
                raise ValueError(
                    f"CSV row {line_number} repeats {repository} issue #{number}."
                )
            seen.add(key)
            annotations.append(
                Annotation(
                    repository=repository,
                    number=number,
                    expected_category=category,
                    duplicate_group=duplicate_group,
                )
            )

    if not annotations:
        raise ValueError("The annotation CSV has no issue rows.")
    if len(annotations) > MAX_ISSUES:
        raise ValueError(f"Evaluate at most {MAX_ISSUES} issues per CSV.")
    return annotations


def _metrics(
    expected: set[MetricItem],
    predicted: set[MetricItem],
) -> Metrics:
    true_positives = len(expected & predicted)
    precision = true_positives / len(predicted) if predicted else None
    recall = true_positives / len(expected) if expected else None
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return Metrics(precision=precision, recall=recall, f1=f1)


def _format_metric(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def evaluate_annotations(annotations: list[Annotation]) -> str:
    issues_by_repository: dict[str, list[GitHubIssue]] = defaultdict(list)
    expected_categories: dict[tuple[str, int], str] = {}
    duplicate_groups: dict[tuple[str, str], list[int]] = defaultdict(list)

    for annotation in annotations:
        issue = fetch_issue_by_number(annotation.repository, annotation.number)
        issues_by_repository[annotation.repository].append(
            GitHubIssue(
                number=issue.number,
                title=issue.title,
                body=issue.body,
                labels=(),
                url=issue.url,
            )
        )
        key = (annotation.repository, annotation.number)
        expected_categories[key] = annotation.expected_category
        if annotation.duplicate_group:
            duplicate_groups[
                (annotation.repository, annotation.duplicate_group)
            ].append(annotation.number)

    predicted_categories: dict[tuple[str, int], str] = {}
    predicted_pairs: set[frozenset[tuple[str, int]]] = set()
    for repository, issues in issues_by_repository.items():
        for issue in issues:
            predicted_categories[(repository, issue.number)] = classify_issue(
                issue,
                use_labels=False,
            )

        matches_by_number = find_similar_issues(issues)
        for issue in issues:
            for match in matches_by_number[issue.number]:
                predicted_pairs.add(
                    frozenset(
                        {
                            (repository, issue.number),
                            (repository, match.issue.number),
                        }
                    )
                )

    actual_pairs: set[frozenset[tuple[str, int]]] = set()
    for (repository, _), numbers in duplicate_groups.items():
        for left, right in combinations(sorted(numbers), 2):
            actual_pairs.add(
                frozenset({(repository, left), (repository, right)})
            )

    correct_categories = sum(
        expected_categories[key] == prediction
        for key, prediction in predicted_categories.items()
    )
    lines = [
        f"Evaluated {len(annotations)} issue(s)",
        (
            f"Category accuracy: {correct_categories}/{len(annotations)} "
            f"({correct_categories / len(annotations):.0%})"
        ),
        "",
        "Category metrics (precision / recall / F1; reference support):",
    ]

    for category in ISSUE_CATEGORIES:
        expected = {
            key for key, value in expected_categories.items() if value == category
        }
        predicted = {
            key for key, value in predicted_categories.items() if value == category
        }
        metrics = _metrics(expected, predicted)
        lines.append(
            f"  {category}: {_format_metric(metrics.precision)} / "
            f"{_format_metric(metrics.recall)} / {_format_metric(metrics.f1)}; "
            f"support {len(expected)}"
        )

    pair_metrics = _metrics(actual_pairs, predicted_pairs)
    true_positives = len(actual_pairs & predicted_pairs)
    lines.extend(
        [
            "",
            (
                f"Similar-issue pairs: {true_positives} correct of "
                f"{len(predicted_pairs)} suggested; "
                f"{len(actual_pairs)} annotated as duplicates"
            ),
            (
                f"Pair precision / recall / F1: "
                f"{_format_metric(pair_metrics.precision)} / "
                f"{_format_metric(pair_metrics.recall)} / "
                f"{_format_metric(pair_metrics.f1)}"
            ),
        ]
    )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and score a manually annotated issue evaluation set."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    export_parser = commands.add_parser(
        "export",
        help="create a CSV template from recent public repository issues",
    )
    export_parser.add_argument("repository", help="owner/repo or a GitHub URL")
    export_parser.add_argument(
        "--limit",
        type=int,
        default=MAX_ISSUES,
        help=f"number of issues to export (1-{MAX_ISSUES}; default: {MAX_ISSUES})",
    )
    export_parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/evaluation/annotations.csv"),
        help="CSV output path",
    )

    score_parser = commands.add_parser(
        "score",
        help="score a completed annotation CSV",
    )
    score_parser.add_argument("csv_file", type=Path)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "export":
            count = export_template(args.repository, args.limit, args.output)
            print(f"Wrote {count} issue(s) to {args.output}.")
            return

        annotations = read_annotations(args.csv_file)
        print(evaluate_annotations(annotations))
    except (OSError, csv.Error, ValueError, requests.RequestException) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
