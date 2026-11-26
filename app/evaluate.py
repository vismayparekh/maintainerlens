import argparse
import csv
import json
from collections import defaultdict
from collections.abc import Callable, Hashable
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
from app.processor import (
    ISSUE_CATEGORIES,
    MAX_SIMILAR_ISSUES,
    classify_issue,
    find_similar_issues,
)

CSV_COLUMNS = (
    "repository",
    "number",
    "title",
    "url",
    "expected_category",
    "duplicate_group",
)
SIMILARITY_CSV_COLUMNS = (
    "repository",
    "number",
    "title",
    "url",
    "duplicate_group",
)
MAX_EVALUATION_ISSUES = 40
MetricItem = TypeVar("MetricItem", bound=Hashable)


@dataclass(frozen=True)
class Annotation:
    repository: str
    number: int
    expected_category: str
    duplicate_group: str


@dataclass(frozen=True)
class SimilarityAnnotation:
    repository: str
    number: int
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
    if len(annotations) > MAX_EVALUATION_ISSUES:
        raise ValueError(
            f"Evaluate at most {MAX_EVALUATION_ISSUES} issues per CSV."
        )
    return annotations


def read_similarity_annotations(path: Path) -> list[SimilarityAnnotation]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError("The annotation CSV is empty.")

        missing_columns = set(SIMILARITY_CSV_COLUMNS) - set(reader.fieldnames)
        if missing_columns:
            raise ValueError(
                "The annotation CSV is missing columns: "
                + ", ".join(sorted(missing_columns))
            )

        annotations: list[SimilarityAnnotation] = []
        seen: set[tuple[str, int]] = set()
        group_sizes: dict[tuple[str, str], int] = defaultdict(int)
        for line_number, row in enumerate(reader, start=2):
            repository = (row["repository"] or "").strip()
            raw_number = (row["number"] or "").strip()
            title = (row["title"] or "").strip()
            url = (row["url"] or "").strip()
            duplicate_group = (row["duplicate_group"] or "").strip()

            if not repository or not raw_number or not title or not url:
                raise ValueError(
                    f"CSV row {line_number} must include repository, number, title, and URL."
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

            key = (repository, number)
            if key in seen:
                raise ValueError(
                    f"CSV row {line_number} repeats {repository} issue #{number}."
                )
            seen.add(key)
            if duplicate_group:
                group_sizes[(repository, duplicate_group)] += 1
            annotations.append(
                SimilarityAnnotation(
                    repository=repository,
                    number=number,
                    duplicate_group=duplicate_group,
                )
            )

    if not annotations:
        raise ValueError("The annotation CSV has no issue rows.")
    if len(annotations) > MAX_EVALUATION_ISSUES:
        raise ValueError(
            f"Evaluate at most {MAX_EVALUATION_ISSUES} issues per CSV."
        )
    invalid_groups = [
        group
        for group, size in group_sizes.items()
        if size < 2
    ]
    if invalid_groups:
        raise ValueError(
            "Each duplicate_group must include at least two issues: "
            + ", ".join(f"{repository}/{group}" for repository, group in invalid_groups)
        )
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


def _predicted_duplicate_links(
    issues_by_repository: dict[str, list[GitHubIssue]],
) -> set[tuple[str, int, int]]:
    predicted_pairs: set[tuple[str, int, int]] = set()
    for repository, issues in issues_by_repository.items():
        matches_by_number = find_similar_issues(issues)
        for issue in issues:
            for match in matches_by_number[issue.number]:
                predicted_pairs.add((repository, issue.number, match.issue.number))
    return predicted_pairs


def _annotated_duplicate_links(
    duplicate_groups: dict[tuple[str, str], list[int]],
) -> set[tuple[str, int, int]]:
    pairs: set[tuple[str, int, int]] = set()
    for (repository, _), numbers in duplicate_groups.items():
        for left, right in combinations(sorted(numbers), 2):
            pairs.update(((repository, left, right), (repository, right, left)))
    return pairs


def _similarity_metric_lines(
    actual_links: set[tuple[str, int, int]],
    predicted_links: set[tuple[str, int, int]],
) -> list[str]:
    actual_pairs = {(repo, min(a, b), max(a, b)) for repo, a, b in actual_links}
    predicted_pairs = {(repo, min(a, b), max(a, b)) for repo, a, b in predicted_links}
    metrics = _metrics(actual_pairs, predicted_pairs)
    retrieval = _metrics(actual_links, predicted_links)
    true_positives = len(actual_pairs & predicted_pairs)
    return [
        (
            f"Similar-issue pairs: {true_positives} correct of "
            f"{len(predicted_pairs)} suggested; "
            f"{len(actual_pairs)} annotated as duplicates"
        ),
        (
            f"Pair precision / recall / F1: "
            f"{_format_metric(metrics.precision)} / "
            f"{_format_metric(metrics.recall)} / "
            f"{_format_metric(metrics.f1)}"
        ),
        (
            f"Top-{MAX_SIMILAR_ISSUES} precision / recall (micro by query): "
            f"{_format_metric(retrieval.precision)} / "
            f"{_format_metric(retrieval.recall)}"
        ),
    ]


def evaluate_annotations(
    annotations: list[Annotation],
    *,
    fetch_issue: Callable[[str, int], GitHubIssue] | None = None,
) -> str:
    fetch_issue = fetch_issue or fetch_issue_by_number
    issues_by_repository: dict[str, list[GitHubIssue]] = defaultdict(list)
    expected_categories: dict[tuple[str, int], str] = {}
    duplicate_groups: dict[tuple[str, str], list[int]] = defaultdict(list)

    for annotation in annotations:
        issue = fetch_issue(annotation.repository, annotation.number)
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
    for repository, issues in issues_by_repository.items():
        for issue in issues:
            predicted_categories[(repository, issue.number)] = classify_issue(
                issue,
                use_labels=False,
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

    supported_f1 = []
    for category in ISSUE_CATEGORIES:
        expected = {
            key for key, value in expected_categories.items() if value == category
        }
        predicted = {
            key for key, value in predicted_categories.items() if value == category
        }
        metrics = _metrics(expected, predicted)
        category_f1 = metrics.f1
        if expected:
            category_f1 = category_f1 if category_f1 is not None else 0.0
            supported_f1.append(category_f1)
        lines.append(
            f"  {category}: {_format_metric(metrics.precision)} / "
            f"{_format_metric(metrics.recall)} / {_format_metric(category_f1)}; "
            f"support {len(expected)}"
        )

    lines.extend(
        [
            f"Macro F1 (categories with reference support): "
            f"{_format_metric(sum(supported_f1) / len(supported_f1))}",
            "",
            *_similarity_metric_lines(
                _annotated_duplicate_links(duplicate_groups),
                _predicted_duplicate_links(issues_by_repository),
            ),
        ]
    )
    return "\n".join(lines)


def evaluate_similarity_annotations(
    annotations: list[SimilarityAnnotation],
    *,
    fetch_issue: Callable[[str, int], GitHubIssue] | None = None,
) -> str:
    fetch_issue = fetch_issue or fetch_issue_by_number
    issues_by_repository: dict[str, list[GitHubIssue]] = defaultdict(list)
    duplicate_groups: dict[tuple[str, str], list[int]] = defaultdict(list)

    for annotation in annotations:
        issue = fetch_issue(annotation.repository, annotation.number)
        issues_by_repository[annotation.repository].append(
            GitHubIssue(
                number=issue.number,
                title=issue.title,
                body=issue.body,
                labels=(),
                url=issue.url,
            )
        )
        if annotation.duplicate_group:
            duplicate_groups[
                (annotation.repository, annotation.duplicate_group)
            ].append(annotation.number)

    actual_links = _annotated_duplicate_links(duplicate_groups)
    predicted_links = _predicted_duplicate_links(issues_by_repository)
    return "\n".join(
        [
            f"Evaluated {len(annotations)} issue(s) for similarity",
            *_similarity_metric_lines(actual_links, predicted_links),
        ]
    )


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

    similarity_parser = commands.add_parser(
        "score-similarity",
        help="score a similarity-only annotation CSV",
    )
    similarity_parser.add_argument("csv_file", type=Path)
    for scorer in (score_parser, similarity_parser):
        scorer.add_argument(
            "--snapshot",
            type=Path,
            help="load issue text from this local JSON file or capture it if absent",
        )
    return parser


def _score_file(csv_file: Path, snapshot: Path | None, *, similarity: bool) -> str:
    annotations = (
        read_similarity_annotations(csv_file) if similarity else read_annotations(csv_file)
    )
    payload = None
    if snapshot is not None:
        if snapshot.exists():
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
        else:
            payload = {}
            for annotation in annotations:
                issue = fetch_issue_by_number(annotation.repository, annotation.number)
                payload[f"{annotation.repository}#{annotation.number}"] = {
                    "title": issue.title,
                    "body": issue.body,
                    "url": issue.url,
                }
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            with snapshot.open("x", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")

    def fetch_issue(repository: str, number: int) -> GitHubIssue:
        if payload is None:
            return fetch_issue_by_number(repository, number)
        key = f"{repository}#{number}"
        record = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(record, dict) or not all(
            isinstance(record.get(field), str) for field in ("title", "body", "url")
        ):
            raise ValueError(f"Snapshot has no valid issue text for {key}.")
        return GitHubIssue(number, record["title"], record["body"], (), record["url"])

    if similarity:
        return evaluate_similarity_annotations(annotations, fetch_issue=fetch_issue)
    return evaluate_annotations(annotations, fetch_issue=fetch_issue)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "export":
            count = export_template(args.repository, args.limit, args.output)
            print(f"Wrote {count} issue(s) to {args.output}.")
            return

        print(_score_file(
            args.csv_file, args.snapshot, similarity=args.command == "score-similarity"
        ))
    except (OSError, csv.Error, ValueError, requests.RequestException) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
