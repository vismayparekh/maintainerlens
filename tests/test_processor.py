import unittest

from app.github_client import GitHubIssue
from app.processor import classify_issue, find_similar_issues, summarize_issue


class IssueProcessorTests(unittest.TestCase):
    def test_classifies_labels_and_common_text_patterns(self) -> None:
        cases = [
            (
                "How to recover from a crash?",
                "The app crashes during login.",
                ("question",),
                "Question",
            ),
            (
                "Saving data fails",
                "An exception is raised.",
                (),
                "Bug",
            ),
            (
                "Feature request: allow custom themes",
                "",
                (),
                "Feature request",
            ),
            (
                "How do I configure custom themes?",
                "",
                (),
                "Question",
            ),
            (
                "Questions about pep3118 format strings",
                "This behavior is sometimes described as a bug.",
                (),
                "Question",
            ),
            (
                "PR 5410 got merged but is not in fact merged",
                "Was there a rebase that removed it? Should we send it again?",
                (),
                "Question",
            ),
            (
                "ENH: let user DTypes convert Python scalars",
                "The current implementation raises an error.",
                (),
                "Feature request",
            ),
            (
                "Promoting the platform to Tier 2",
                "This proposal also mentions failures in the current setup.",
                (),
                "Feature request",
            ),
            (
                "Docs: link security vulnerability reports",
                "The current bug report process is documented here.",
                (),
                "Other",
            ),
            (
                "TestTimeout abandons requests and later tests wait for the server",
                "An exception is raised during cleanup.",
                (),
                "Other",
            ),
            (
                "get_encoding_from_headers treats any content type containing text as text",
                "",
                (),
                "Bug",
            ),
            (
                "parse_header_links drops parameters from quoted values",
                "",
                (),
                "Bug",
            ),
            (
                "Fix broken links in the documentation",
                "Several documentation links are broken.",
                (),
                "Other",
            ),
            (
                "CI failed on Unit tests Linux",
                "The test job failed on this platform.",
                (),
                "Other",
            ),
            (
                "Request for clarification: URL parsing behavior",
                "I am seeking clarification about the URL parsing rules.",
                (),
                "Question",
            ),
            (
                "Help with POST request with XML payload",
                "The request fails with status code 411.",
                (),
                "Question",
            ),
            (
                "Unable to remove default content-length header field",
                "After I re-initiate the request, how do I fix this?",
                (),
                "Question",
            ),
            (
                "Any IPv6 request spuriously stays stuck",
                "I have an issue with my OS that I am not sure how to diagnose.",
                (),
                "Question",
            ),
            (
                "Running pipeline.fit automatically runs pipeline.transform",
                "I wanted to know if there is a way to run fit without transform.",
                (),
                "Question",
            ),
            (
                "CURL and Requests.session() returning different values",
                "I don't know if anyone has seen this happen.",
                (),
                "Question",
            ),
            (
                "Status of SWIG support",
                "Hence my question: what are the expectations regarding SWIG support?",
                (),
                "Question",
            ),
            (
                "Order of individual FFTs for calculating irfftn",
                "Should it be changed to axes[-2], axes[-3], .. axes[0], while "
                + "considering the complex-to-real transform ordering " * 25
                + "? In general, order is not important for complex-to-complex FFTs.",
                (),
                "Question",
            ),
            (
                "[QUESTION] precision_recall_curve with softmax output",
                "The output scores and true labels look like this.",
                (),
                "Question",
            ),
            (
                "Accessing array elements by key",
                "I am looking for an easy way to access elements by string key.",
                (),
                "Feature request",
            ),
            (
                "Support specifying adapter per-request",
                "There is no workaround other than using separate sessions.",
                (),
                "Feature request",
            ),
            (
                "Add response status code to HTTPError exceptions",
                "This would make it easier to inspect failed requests.",
                (),
                "Feature request",
            ),
            (
                "Document the install command",
                "",
                (),
                "Other",
            ),
        ]

        for number, (title, body, labels, expected) in enumerate(cases, start=1):
            with self.subTest(title=title):
                issue = GitHubIssue(
                    number=number,
                    title=title,
                    body=body,
                    labels=labels,
                    url=f"https://github.com/acme/project/issues/{number}",
                )
                self.assertEqual(classify_issue(issue), expected)

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

    def test_finds_related_issues_and_excludes_unrelated_ones(self) -> None:
        issues = [
            GitHubIssue(
                number=1,
                title="Login form fails during password reset",
                body="Reset requests return a server error.",
                labels=(),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="Password reset login form returns server error",
                body="Reset requests return a server error.",
                labels=(),
                url="https://github.com/acme/project/issues/2",
            ),
            GitHubIssue(
                number=3,
                title="Document installation steps",
                body="Add examples for setting up the project.",
                labels=(),
                url="https://github.com/acme/project/issues/3",
            ),
        ]

        matches = find_similar_issues(issues)

        self.assertEqual([match.issue.number for match in matches[1]], [2])
        self.assertGreaterEqual(matches[1][0].score, 0.2)
        self.assertEqual(matches[3], [])

    def test_uses_title_overlap_and_avoids_shared_template_false_matches(
        self,
    ) -> None:
        issues = [
            GitHubIssue(
                number=1,
                title="ENH: NumPy bfloat16 support",
                body="TensorFlow has its own reduced-precision numeric type.",
                labels=(),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="Feature request: bfloat16 support in NumPy",
                body="I need a smaller floating point format for accelerator data.",
                labels=(),
                url="https://github.com/acme/project/issues/2",
            ),
            GitHubIssue(
                number=3,
                title=(
                    "get_encoding_from_headers treats any content type containing "
                    "text as text ISO-8859-1"
                ),
                body=(
                    "The application/vnd.context+xml media type incorrectly "
                    "receives the Latin-1 fallback."
                ),
                labels=(),
                url="https://github.com/acme/project/issues/3",
            ),
            GitHubIssue(
                number=4,
                title=(
                    "get_encoding_from_headers is case-sensitive to media type "
                    "tokens RFC 9110"
                ),
                body=(
                    "Uppercase TEXT/PLAIN and APPLICATION/JSON are not "
                    "normalized and return None."
                ),
                labels=(),
                url="https://github.com/acme/project/issues/4",
            ),
        ]

        matches = find_similar_issues(issues)

        self.assertIn(2, [match.issue.number for match in matches[1]])
        self.assertNotIn(4, [match.issue.number for match in matches[3]])

    def test_title_match_can_recover_when_issue_bodies_differ(self) -> None:
        issues = [
            GitHubIssue(
                number=1,
                title=(
                    "Nystroem has misleading parts makes precomputed kernel "
                    "seemingly possible"
                ),
                body="Large matrices return a stable result.",
                labels=(),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="kernel_approximation.Nystroem with precomputed kernel",
                body="Examples omit the model settings.",
                labels=(),
                url="https://github.com/acme/project/issues/2",
            ),
        ]

        matches = find_similar_issues(issues)

        self.assertIn(2, [match.issue.number for match in matches[1]])

    def test_moderate_body_overlap_can_recover_a_match(self) -> None:
        issues = [
            GitHubIssue(
                number=1,
                title="Qt5 toolbar icon black macOS renderer",
                body=(
                    "High contrast settings keep macOS toolbar icons sharply "
                    "visible using pale foreground controls."
                ),
                labels=(),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="Qt5Agg toolbar icon glyph dark Linux widget",
                body=(
                    "High contrast settings make Linux navigation glyphs clearly "
                    "legible using bright foreground controls."
                ),
                labels=(),
                url="https://github.com/acme/project/issues/2",
            ),
        ]

        matches = find_similar_issues(issues)

        self.assertIn(2, [match.issue.number for match in matches[1]])

    def test_downweights_repeated_issue_boilerplate(self) -> None:
        issues = [
            GitHubIssue(
                number=1,
                title="BUG report PyArrow timestamp index",
                body=(
                    "Observed behavior expected result: PyArrow timestamp index "
                    "slices date values."
                ),
                labels=(),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="BUG report PyArrow timestamp index slicing",
                body=(
                    "Observed behavior expected result: PyArrow timestamp index "
                    "returns date values."
                ),
                labels=(),
                url="https://github.com/acme/project/issues/2",
            ),
            GitHubIssue(
                number=3,
                title="BUG report unrelated renderer",
                body=(
                    "Observed behavior expected result: renderer clips legends "
                    "during resize."
                ),
                labels=(),
                url="https://github.com/acme/project/issues/3",
            ),
        ]

        matches = find_similar_issues(issues)

        self.assertIn(2, [match.issue.number for match in matches[1]])
        self.assertNotIn(3, [match.issue.number for match in matches[1]])

    def test_ignores_urls_when_comparing_issue_bodies(self) -> None:
        issues = [
            GitHubIssue(
                number=1,
                title="Tensor shape overflow in model",
                body="https://github.com/acme/project/issues/1",
                labels=(),
                url="https://github.com/acme/project/issues/1",
            ),
            GitHubIssue(
                number=2,
                title="Socket timeout during request",
                body="https://github.com/acme/project/issues/2",
                labels=(),
                url="https://github.com/acme/project/issues/2",
            ),
        ]

        matches = find_similar_issues(issues)

        self.assertEqual(matches[1], [])
        self.assertEqual(matches[2], [])


if __name__ == "__main__":
    unittest.main()
