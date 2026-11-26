import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.github_client import GitHubPullRequest, PullRequestDetails
from app.llm_client import PullRequestAnalysis
from app.pr_benchmark import generate, score


class PRBenchmarkTests(unittest.TestCase):
    @patch("app.pr_benchmark._configured_model", return_value="example-model")
    @patch("app.pr_benchmark.analyze_pull_request")
    @patch("app.pr_benchmark.fetch_pull_request_details")
    def test_reuses_capture_and_checks_grades_belong_to_exact_run(self, fetch, analyze, _model):
        pull = GitHubPullRequest(
            12, "Document exports", "Update the export guide.",
            "https://github.com/acme/example/pull/12", "open", None, "2026-11-26T00:00:00Z",
        )
        fetch.return_value = PullRequestDetails(pull, "main", "docs", 0, 0, 0, (), ())
        analyze.return_value = PullRequestAnalysis(
            summary="Updates the export guide.", checklist=["Verify the guide describes the export format."],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.csv"
            manifest.write_text("repository,number,focus\nacme/example,12,documentation\n", encoding="utf-8")
            snapshot, first, second = (root / filename for filename in ("capture.json", "one.jsonl", "two.jsonl"))
            with patch("builtins.print"):
                generate(manifest, snapshot, first)
                generate(manifest, snapshot, second)

            grades = root / "grades.csv"
            run_id = json.loads(first.read_text(encoding="utf-8"))["run_id"]
            grades.write_text(
                "run_id,repository,number,change_accuracy,author_intent,actionable_checks\n"
                f"{run_id},acme/example,12,2,2,1\n",
                encoding="utf-8",
            )
            report = score(first, grades)
            with self.assertRaisesRegex(ValueError, "from this run"):
                score(second, grades)

        fetch.assert_called_once_with("acme/example", 12)
        self.assertEqual(analyze.call_count, 2)
        self.assertIn("Briefs generated: 1/1", report)
        self.assertIn("Actionable Checks: 1/2 points, 0/1 full credit", report)
