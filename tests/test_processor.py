import unittest

from app.processor import summarize_issue


class SummarizeIssueTests(unittest.TestCase):
    def test_returns_first_two_sentences_with_normalized_whitespace(self) -> None:
        body = "The app crashes.  It happens on startup.\nMore details follow."

        self.assertEqual(
            summarize_issue(body),
            "The app crashes. It happens on startup.",
        )

    def test_handles_empty_and_long_bodies(self) -> None:
        self.assertEqual(summarize_issue(" \n "), "No description provided.")

        summary = summarize_issue("A" * 300)
        self.assertEqual(len(summary), 240)
        self.assertTrue(summary.endswith("..."))


if __name__ == "__main__":
    unittest.main()
