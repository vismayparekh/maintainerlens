import argparse
import csv
from pathlib import Path
from random import SystemRandom
from statistics import median
from urllib.parse import urlencode

from app.reply_benchmark import REPLY_REPORT_COLUMNS, summarize_rows


MANIFEST = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "reply-pilot.csv"
MODES = ("manual", "assisted")
BLIND_COLUMNS = ("trial_id", "issue_url", "reviewed_reply", "reviewed_checklist", "factual_error")


def read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError(f"{path} must contain {', '.join(sorted(required))}.")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}, line {reader.line_num} has the wrong number of fields.")
            rows.append(row)
        return rows


def assignments(sequence: str) -> list[dict[str, str]]:
    cases = read_csv(MANIFEST, {"order", "repository", "issue_number", "issue_url", "mode"})
    if sequence == "B":
        for case in cases:
            case["mode"] = MODES[1 - MODES.index(case["mode"])]
    return cases


def print_plan(sequence: str, base_url: str) -> None:
    for case in assignments(sequence):
        query = urlencode({"repository": case["repository"], "issue": case["issue_number"]})
        print(f"{case['order']}. {case['mode']} — {base_url.rstrip('/')}/?{query}")


def collect_trials(group_a: list[Path], group_b: list[Path]) -> tuple[list[dict[str, str]], dict[str, int]]:
    exports = [path.resolve() for path in (*group_a, *group_b)]
    if len(exports) != len(set(exports)):
        raise ValueError("Supply one distinct CSV export per participant.")
    rows = []
    scheduled = dict.fromkeys(MODES, 0)
    for sequence, paths in (("A", group_a), ("B", group_b)):
        expected = {case["issue_url"]: case["mode"] for case in assignments(sequence)}
        for path in paths:
            for mode in expected.values():
                scheduled[mode] += 1
            seen = set()
            for row in read_csv(path, REPLY_REPORT_COLUMNS | {"issue_url"}):
                url = row["issue_url"]
                if expected.get(url) != row["mode"] or url in seen:
                    raise ValueError(f"{path} has an unexpected mode, case, or repeat for {url}.")
                seen.add(url)
                rows.append(row)
    summarize_rows(rows)
    return rows, scheduled


def write_blind_sheet(path: Path, rows: list[dict[str, str]]) -> None:
    shuffled = list(rows)
    SystemRandom().shuffle(shuffled)
    with path.open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=BLIND_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({**row, "factual_error": ""} for row in shuffled)


def apply_grades(path: Path, rows: list[dict[str, str]]) -> None:
    by_trial_id = {row["trial_id"]: row for row in rows}
    seen = set()
    for grade in read_csv(path, {"trial_id", "factual_error"}):
        trial_id = grade["trial_id"]
        if trial_id not in by_trial_id or trial_id in seen:
            raise ValueError(f"{path} contains an unknown or repeated trial ID.")
        seen.add(trial_id)
        by_trial_id[trial_id]["factual_error"] = grade["factual_error"]


def report(rows: list[dict[str, str]], scheduled: dict[str, int]) -> str:
    case_times = {}
    for row in rows:
        durations = case_times.setdefault(row["issue_url"], {mode: [] for mode in MODES})
        durations[row["mode"]].append(int(row["duration_ms"]))
    differences = [
        (median(times["manual"]) - median(times["assisted"])) / 1000
        for times in case_times.values()
        if all(times.values())
    ]
    lines = [summarize_rows(rows)]
    for mode in MODES:
        completed = sum(row["mode"] == mode for row in rows)
        lines.append(f"{mode.title()} completion: {completed}/{scheduled[mode]} assigned")
    total_cases = len(assignments("A"))
    lines.append(f"Cases completed in both modes: {len(differences)}/{total_cases}")
    if differences:
        lines.append(
            f"Median case-matched difference (manual minus assisted): {median(differences):.2f} s"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the counterbalanced maintainer reply pilot.")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Print one participant's assigned tasks.")
    plan.add_argument("sequence", choices=("A", "B"))
    plan.add_argument("--base-url", default="http://localhost:5173")

    for command, help_text in (
        ("blind", "Export saved replies for independent quality review."),
        ("score", "Report completion, drafting time, and quality."),
    ):
        subparser = commands.add_parser(command, help=help_text)
        subparser.add_argument("--group-a", type=Path, action="append", default=[])
        subparser.add_argument("--group-b", type=Path, action="append", default=[])
        if command == "blind":
            subparser.add_argument("--output", type=Path, required=True)
        else:
            subparser.add_argument("--grades", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "plan":
            print_plan(args.sequence, args.base_url)
            return
        if not (args.group_a or args.group_b):
            parser.error("Supply at least one participant export via --group-a or --group-b.")
        rows, scheduled = collect_trials(args.group_a, args.group_b)
        if args.command == "blind":
            write_blind_sheet(args.output, rows)
            print(f"Wrote {len(rows)} drafts for blind review to {args.output}.")
        else:
            if args.grades:
                for row in rows:
                    row["factual_error"] = ""
                apply_grades(args.grades, rows)
            print(report(rows, scheduled))
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
