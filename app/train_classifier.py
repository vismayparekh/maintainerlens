import argparse
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from app.evaluate import read_annotations, snapshot_issue_fetcher
from app.github_client import fetch_labeled_issues
from app.processor import ISSUE_CATEGORIES, classify_issue

SOURCE_LABELS = {
    "microsoft/vscode": ("bug", "*question", "feature-request", "docs-experience"),
    "jupyterlab/jupyterlab": ("bug", "question", "enhancement", "documentation"),
    "sphinx-doc/sphinx": ("type:bug", "type:question", "type:enhancement", "type:docs"),
    "encode/httpx": ("bug", "question", "enhancement", "docs"),
}
MODEL_FILE = "issue-classifier.skops"
SUMMARY_FILE = "training-summary.json"
CURATED_WEIGHT = 6.0
CURATED_BUG_BOOST = 1.35
_NON_PROSE = re.compile(
    r"```[\s\S]*?(?:```|\Z)|<!--[\s\S]*?-->|https?://\S+|[\w.+-]+@[\w.-]+\.\w+|(?<!\w)@[\w-]+"
)


def issue_text(title: str, body: str) -> str:
    return f"{_NON_PROSE.sub(' ', title)}\n" * 3 + _NON_PROSE.sub(" ", body)[:3000]


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


def collect_examples(output: Path, per_label: int) -> None:
    if output.exists():
        raise ValueError("Choose a new path for the training snapshot.")
    if not 1 <= per_label <= 50:
        raise ValueError("Choose between 1 and 50 issues per source label.")

    def collect_label(job):
        repository, label, category = job
        known_labels = set(SOURCE_LABELS[repository])
        rows = []
        for issue in fetch_labeled_issues(repository, label, 100):
            if not issue.body.strip() or set(issue.labels) & known_labels != {label}:
                continue
            rows.append({
                "repository": repository,
                "number": issue.number,
                "url": issue.url,
                "source_label": label,
                "category": category,
                "title": issue.title,
                "body": issue.body,
            })
            if len(rows) == per_label:
                break
        return rows

    jobs = [
        (repository, label, category)
        for repository, labels in SOURCE_LABELS.items()
        for category, label in zip(ISSUE_CATEGORIES, labels, strict=True)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [row for batch in pool.map(collect_label, jobs) for row in batch]
    counts = Counter(row["category"] for row in rows)
    if set(counts) != set(ISSUE_CATEGORIES):
        raise ValueError("Training collection did not find examples of all four categories.")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, rows)
    print(f"Saved {len(rows)} weakly labeled examples to {output}")
    for repository in SOURCE_LABELS:
        print(repository, dict(Counter(row["category"] for row in rows if row["repository"] == repository)))


def train(
    training: Path, output: Path, *, curated: Path | None = None, curated_snapshot: Path | None = None
) -> None:
    if (curated is None) != (curated_snapshot is None):
        raise ValueError("Curated annotations and their snapshot path must be supplied together.")
    if output.exists():
        raise ValueError("Choose a new directory for the trained model.")

    import numpy as np
    from skops.io import dump, load
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.utils.class_weight import compute_class_weight

    raw = training.read_bytes()
    rows = json.loads(raw)
    curated_hash = None
    curated_count = 0
    if curated:
        annotations = read_annotations(curated, limit=None)
        fetch = snapshot_issue_fetcher(annotations, curated_snapshot)
        for entry in annotations:
            issue = fetch(entry.repository, entry.number)
            rows.append({
                "repository": entry.repository,
                "number": entry.number,
                "title": issue.title,
                "body": issue.body,
                "category": entry.expected_category,
            })
        curated_count = len(annotations)
        curated_hash = hashlib.sha256(curated.read_bytes()).hexdigest()
    counts = Counter(row["category"] for row in rows)
    if set(counts) != set(ISSUE_CATEGORIES):
        raise ValueError("Training examples must cover all four issue categories.")
    issue_ids = {(row["repository"].casefold(), row["number"]) for row in rows}
    if len(issue_ids) != len(rows):
        raise ValueError("Training examples must have unique issue IDs.")
    fit_texts = [issue_text(row["title"], row["body"]) for row in rows]
    labels = [row["category"] for row in rows]
    fit_options = {}
    class_weight = "balanced"
    if curated_count:
        weights = [1.0] * (len(rows) - curated_count) + [CURATED_WEIGHT] * curated_count
        classes = np.array(ISSUE_CATEGORIES)
        balanced = compute_class_weight("balanced", classes=classes, y=labels, sample_weight=weights)
        class_weight = dict(zip(ISSUE_CATEGORIES, map(float, balanced), strict=True))
        class_weight["Bug"] *= CURATED_BUG_BOOST
        fit_options["logisticregression__sample_weight"] = weights
    model = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=30_000, sublinear_tf=True),
        LogisticRegression(C=2, class_weight=class_weight, max_iter=1000),
    )
    model.fit(fit_texts, labels, **fit_options)
    output.mkdir(parents=True)
    model_path = output / MODEL_FILE
    dump(model, model_path)
    reloaded = load(model_path)
    if list(reloaded.predict(fit_texts[:8])) != list(model.predict(fit_texts[:8])):
        raise ValueError("Saved model does not match the trained classifier.")
    write_json(output / SUMMARY_FILE, {
        "training_repositories": sorted({repo for repo, _ in issue_ids}),
        "training_snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "curated_annotations_sha256": curated_hash,
        "curated_snapshot_sha256": (
            hashlib.sha256(curated_snapshot.read_bytes()).hexdigest() if curated_snapshot else None
        ),
        "curated_samples": curated_count,
        "curated_weight": CURATED_WEIGHT if curated_count else None,
        "bug_boost": CURATED_BUG_BOOST if curated_count else None,
        "samples": len(rows),
        "class_counts": dict(counts),
    })
    print(f"Saved {model_path} with {len(rows)} training examples.")


def compare(
    model_dir: Path, annotations_path: Path, snapshot: Path, output: Path, *, candidate: Path | None = None
) -> None:
    from skops.io import load
    from sklearn.metrics import accuracy_score, classification_report

    if output.exists():
        raise ValueError("Choose a new path for the benchmark report.")
    annotations = read_annotations(annotations_path)
    model_paths = {"trained": model_dir}
    if candidate:
        model_paths["revised"] = candidate
    benchmark_repos = {entry.repository.casefold() for entry in annotations}
    for path in model_paths.values():
        summary = json.loads((path / SUMMARY_FILE).read_bytes())
        if benchmark_repos & set(summary["training_repositories"]):
            raise ValueError("Training and benchmark repositories must be disjoint.")
    fetch = snapshot_issue_fetcher(annotations, snapshot)
    issues = [fetch(entry.repository, entry.number) for entry in annotations]
    expected = [entry.expected_category for entry in annotations]
    predictions = {"rules": [classify_issue(issue, use_labels=False) for issue in issues]}
    texts = [issue_text(issue.title, issue.body) for issue in issues]
    for name, path in model_paths.items():
        predictions[name] = load(path / MODEL_FILE).predict(texts).tolist()
    supported = [category for category in ISSUE_CATEGORIES if category in expected]
    scores = {
        name: {
            **classification_report(expected, values, labels=supported, output_dict=True, zero_division=0),
            "accuracy": accuracy_score(expected, values),
        }
        for name, values in predictions.items()
    }
    write_json(output, {
        "annotations_sha256": hashlib.sha256(annotations_path.read_bytes()).hexdigest(),
        "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "scores": scores,
        "predictions": [
            {"url": issue.url, "expected": category, **{name: values[index] for name, values in predictions.items()}}
            for index, (issue, category) in enumerate(zip(issues, expected, strict=True))
        ],
    })
    print(f"Scored {len(issues)} held-out issues.")
    for name, metrics in scores.items():
        print(f"{name}: macro F1 {metrics['macro avg']['f1-score']:.1%}, accuracy {metrics['accuracy']:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate a text-only issue classifier.")
    commands = parser.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("output", type=Path)
    collect_parser.add_argument("--per-label", type=int, default=40)
    train_parser = commands.add_parser("train")
    train_parser.add_argument("training", type=Path)
    train_parser.add_argument("output", type=Path)
    train_parser.add_argument("--curated", type=Path)
    train_parser.add_argument("--curated-snapshot", type=Path)
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("model_dir", type=Path)
    compare_parser.add_argument("annotations", type=Path)
    compare_parser.add_argument("--snapshot", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "collect":
            collect_examples(args.output, args.per_label)
        elif args.command == "train":
            train(args.training, args.output, curated=args.curated, curated_snapshot=args.curated_snapshot)
        else:
            compare(args.model_dir, args.annotations, args.snapshot, args.output, candidate=args.candidate)
    except (ValueError, OSError, requests.RequestException) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
