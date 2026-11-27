import csv
import tempfile
import unittest
from pathlib import Path

from app.reply_benchmark import REPLY_REPORT_COLUMNS
from app.reply_pilot import apply_grades, assignments, collect_trials, report, write_blind_sheet


class ReplyPilotTests(unittest.TestCase):
    def test_scores_same_case_across_sequences_and_hides_mode_for_grading(self):
        first = assignments("A")
        second = assignments("B")
        self.assertEqual(len(first), 8)
        self.assertEqual(sum(case["mode"] == "manual" for case in first), 4)
        for case_a, case_b in zip(first, second, strict=True):
            self.assertEqual(case_a["issue_url"], case_b["issue_url"])
            self.assertNotEqual(case_a["mode"], case_b["mode"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manual = root / "manual.csv"
            assisted = root / "assisted.csv"
            write_export(manual, first[0], "manual-trial", 10_000)
            write_export(assisted, second[0], "assisted-trial", 6_000)
            rows, scheduled = collect_trials([manual], [assisted])

            blind = root / "blind.csv"
            write_blind_sheet(blind, rows)
            with blind.open(newline="") as file:
                reader = csv.DictReader(file)
                self.assertEqual(set(reader.fieldnames), {
                    "trial_id", "issue_url", "reviewed_reply", "reviewed_checklist", "factual_error",
                })
                self.assertEqual(len(list(reader)), 2)

            grades = root / "grades.csv"
            grades.write_text("trial_id,factual_error\nassisted-trial,yes\n")
            apply_grades(grades, rows)
            result = report(rows, scheduled)
            self.assertIn("Cases completed in both modes: 1/8", result)
            self.assertIn("Median case-matched difference (manual minus assisted): 4.00 s", result)
            self.assertEqual(result.count("completion: 1/8 assigned"), 2)
            self.assertIn("Factual errors: 1/1 checked", result)
            self.assertIn("Assisted drafts accepted unchanged: 1/1", result)

    def test_rejects_wrong_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-sequence.csv"
            write_export(path, assignments("A")[0], "manual-trial", 10_000)
            with self.assertRaisesRegex(ValueError, "unexpected mode"):
                collect_trials([], [path])


def write_export(path, case, trial_id, duration):
    fields = sorted(REPLY_REPORT_COLUMNS | {"issue_url"})
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "trial_id": trial_id,
            "issue_url": case["issue_url"],
            "mode": case["mode"],
            "duration_ms": duration,
            "original_reply": "Thanks for reporting this." if case["mode"] == "assisted" else "",
            "reviewed_reply": "Thanks for reporting this.",
        })
