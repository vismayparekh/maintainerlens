import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.argilla_issue_review import issue_fields, review_rows


class ArgillaIssueReviewTests(unittest.TestCase):
    def test_import_uses_only_issue_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "issues.json"
            path.write_text(json.dumps({
                "owner/project#1": {
                    "title": "Incorrect result",
                    "body": "An example illustrating the mismatch.",
                    "url": "https://github.com/owner/project/issues/1",
                    "source_label": "bug",
                    "prediction": "Bug",
                },
            }))
            fields = issue_fields(path)
        self.assertEqual(list(fields.values()), [{
            "title": "Incorrect result", "body": "An example illustrating the mismatch.",
        }])

    def test_only_two_distinct_agreeing_reviews_enter_consensus(self):
        def answer(user, category, status="submitted"):
            return [
                SimpleNamespace(user_id=user, status=status, question_name="category", value=category),
                SimpleNamespace(user_id=user, status=status, question_name="evidence", value="Issue text."),
            ]

        def record(number, responses):
            return SimpleNamespace(id=f"batch:owner/project#{number}", fields={"title": "Title"}, responses=responses)

        records = [
            record(1, answer("a", "Bug") + answer("b", "Bug")),
            record(2, answer("a", "Question") + answer("b", "Bug")),
            record(3, answer("a", "Bug") + answer("b", "Bug", status="draft")),
            record(4, answer("a", "Unclear") + answer("b", "Unclear")),
        ]
        dataset = SimpleNamespace(records=lambda with_responses: records if with_responses else [])
        reviews, consensus, counts = review_rows(dataset)
        self.assertEqual(len(reviews), 7)
        self.assertEqual([(row["number"], row["expected_category"]) for row in consensus], [("1", "Bug")])
        self.assertEqual(counts, {"agreed": 1, "pending": 1, "needs_review": 2})
