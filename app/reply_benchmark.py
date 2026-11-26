import argparse
import csv
from pathlib import Path
from statistics import median


def summarize_trials(path: Path) -> str:
    times: dict[str, list[int]] = {"manual": [], "assisted": []}
    checked = {"manual": 0, "assisted": 0}
    factual_errors = {"manual": 0, "assisted": 0}
    accepted = 0
    seen_trials: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {
            "trial_id", "mode", "duration_ms", "original_reply", "original_checklist",
            "reviewed_reply", "reviewed_checklist", "factual_error",
        }
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("Use the reply review CSV export, including the factual_error column.")
        for row in reader:
            mode = row["mode"]
            try:
                duration = int(row["duration_ms"])
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Row {reader.line_num} has an invalid duration.") from exc
            if mode not in times or duration < 0:
                raise ValueError(f"Row {reader.line_num} has an invalid mode or duration.")
            trial_id = row["trial_id"]
            if not trial_id or trial_id in seen_trials:
                raise ValueError(f"Row {reader.line_num} needs a unique trial ID.")
            seen_trials.add(trial_id)
            times[mode].append(duration)
            if mode == "assisted" and (
                row["original_reply"] == row["reviewed_reply"]
                and row["original_checklist"] == row["reviewed_checklist"]
            ):
                accepted += 1
            factual_error = (row["factual_error"] or "").strip().lower()
            if factual_error not in {"", "yes", "no"}:
                raise ValueError(f"Row {reader.line_num} needs yes, no, or blank for factual_error.")
            if factual_error:
                checked[mode] += 1
                factual_errors[mode] += factual_error == "yes"

    lines = []
    medians = {}
    for mode, durations in times.items():
        if durations:
            medians[mode] = median(durations) / 1000
            lines.append(f"{mode.title()}: {len(durations)} completed, median {medians[mode]:.2f} s")
        else:
            lines.append(f"{mode.title()}: no completed trials")
        if checked[mode]:
            lines.append(f"  Factual errors: {factual_errors[mode]}/{checked[mode]} checked")
        else:
            lines.append("  Factual errors: no trials checked")
    if times["assisted"]:
        lines.append(f"Assisted drafts accepted unchanged: {accepted}/{len(times['assisted'])}")
    if len(medians) == 2:
        saved = medians["manual"] - medians["assisted"]
        lines.append(f"Median time saved (manual minus assisted): {saved:.2f} s")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize exported maintainer reply trials.")
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()
    try:
        print(summarize_trials(args.csv_file))
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
