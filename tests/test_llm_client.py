import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai import OpenAIError

from app.llm_client import (
    MAX_ISSUE_BODY_CHARS,
    IssueAnalysis,
    IssueAnalysisError,
    IssueAnalysisNotConfiguredError,
    ReplyDraft,
    analyze_issue,
    draft_issue_reply,
)


class AnalyzeIssueTests(unittest.TestCase):
    @patch.dict(os.environ, {"HF_TOKEN": "test-token", "HF_MODEL": "test-model"})
    @patch("app.llm_client.OpenAI")
    def test_requests_and_validates_analysis_for_issue_text(
        self, openai_client: Mock
    ) -> None:
        analysis = IssueAnalysis(
            summary="The service crashes at startup.",
            category="Bug",
            rationale="The issue reports broken startup behavior.",
        )
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=analysis.model_dump_json())
                )
            ]
        )
        openai_client.return_value = client

        result = analyze_issue("Startup crash test", "The service crashes at startup.")

        self.assertEqual(result, analysis)
        openai_client.assert_called_once_with(
            base_url="https://router.huggingface.co/v1",
            api_key="test-token",
            timeout=30,
            max_retries=1,
        )
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(call["max_tokens"], 1024)
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertEqual(
            json.loads(call["messages"][1]["content"]),
            {
                "title": "Startup crash test",
                "body": "The service crashes at startup.",
            },
        )
        system_prompt = call["messages"][0]["content"]
        self.assertIn("untrusted data", system_prompt)
        self.assertIn("Question when the author primarily seeks help", system_prompt)
        self.assertIn("new software capability", system_prompt)
        self.assertIn("automated CI/status notices", system_prompt)
        self.assertIn("An error message or failed CI check alone", system_prompt)
        self.assertIn("A reported expected result or a reproduction alone", system_prompt)
        self.assertIn("choose Question unless a project defect is established", system_prompt)

    @patch.dict(os.environ, {"HF_TOKEN": "test-token", "HF_MODEL": "test-model"})
    @patch("app.llm_client.OpenAI")
    def test_reuses_analysis_for_identical_issue_in_process(
        self, openai_client: Mock
    ) -> None:
        analysis = IssueAnalysis(
            summary="The service crashes at startup.",
            category="Bug",
            rationale="The issue reports broken startup behavior.",
        )
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=analysis.model_dump_json())
                )
            ]
        )
        openai_client.return_value = client

        first = analyze_issue("Repeated issue cache test", "Same issue body.")
        second = analyze_issue("Repeated issue cache test", "Same issue body.")

        self.assertEqual(first, analysis)
        self.assertEqual(second, analysis)
        openai_client.assert_called_once()
        client.chat.completions.create.assert_called_once()

    @patch.dict(os.environ, {"HF_TOKEN": ""})
    def test_requires_hugging_face_token(self) -> None:
        with self.assertRaises(IssueAnalysisNotConfiguredError):
            analyze_issue("Missing key test", "Body text.")

    @patch.dict(os.environ, {"HF_TOKEN": "test-token"})
    @patch("app.llm_client.OpenAI")
    def test_rejects_missing_structured_output(
        self, openai_client: Mock
    ) -> None:
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[])
        openai_client.return_value = client

        with self.assertRaises(IssueAnalysisError):
            analyze_issue("No inference output test", "Body text.")

    @patch.dict(os.environ, {"HF_TOKEN": "test-token"})
    @patch("app.llm_client.OpenAI")
    def test_limits_body_sent_to_model(
        self, openai_client: Mock
    ) -> None:
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=IssueAnalysis(
                            summary="A summary.",
                            category="Other",
                            rationale="The issue does not fit another category.",
                        ).model_dump_json()
                    )
                )
            ],
        )
        openai_client.return_value = client
        body = "x" * (MAX_ISSUE_BODY_CHARS + 10)

        analyze_issue("Body limit test", body)

        sent_body = json.loads(
            client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        )["body"]
        self.assertEqual(len(sent_body), MAX_ISSUE_BODY_CHARS)

    @patch.dict(os.environ, {"HF_TOKEN": "test-token"})
    @patch("app.llm_client.OpenAI")
    def test_shortens_overlong_summary_and_marks_it(
        self, openai_client: Mock
    ) -> None:
        summary = "A useful summary sentence. " * 30
        analysis = IssueAnalysis(
            summary=summary,
            category="Bug",
            rationale="The issue reports broken behavior.",
        )
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=analysis.model_dump_json())
                )
            ]
        )
        openai_client.return_value = client

        result = analyze_issue("Long summary test", "Issue body.")

        self.assertLessEqual(len(result.summary), 500)
        self.assertTrue(result.summary.endswith("..."))
        self.assertTrue(result.summary[:-3].endswith("useful"))
        self.assertTrue(result.summary_truncated)


@patch.dict(os.environ, {"HF_TOKEN": "test-token", "HF_MODEL": "test-model"})
class ReplyDraftTests(unittest.TestCase):
    @staticmethod
    def completion(content, finish_reason="stop"):
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=finish_reason, message=SimpleNamespace(content=content),
        )])

    @patch("app.llm_client.OpenAI")
    def test_retries_incomplete_or_malformed_output_once(self, openai_client):
        draft = ReplyDraft(reply="Thanks for the report.", checklist=[], related_issue_numbers=[])
        success = self.completion(draft.model_dump_json())
        failures = (
            (self.completion(None, "length"), "output_token_limit"),
            (SimpleNamespace(choices=[]), "empty_output"),
            (self.completion('{"reply":"missing fields"}'), "invalid_schema"),
        )
        create = openai_client.return_value.chat.completions.create
        for response, reason in failures:
            with self.subTest(reason=reason):
                openai_client.reset_mock()
                create.side_effect = [response, success]
                with self.assertLogs("app.llm_client", level="WARNING") as logs:
                    actual = draft_issue_reply("Example title", "The workaround already works.", [])

                self.assertEqual(actual, draft)
                self.assertEqual([call.kwargs["max_tokens"] for call in create.call_args_list], [4096, 8192])
                self.assertTrue(all(call.kwargs["max_retries"] == 0 for call in openai_client.call_args_list))
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertIn("workarounds the reporter has already tried", prompt)
                self.assertIn("ask no follow-up questions", prompt)
                self.assertIn(f"attempt=1 reason={reason} retrying=True", logs.output[0])
                self.assertNotIn("The workaround already works.", logs.output[0])

    @patch("app.llm_client.OpenAI")
    def test_stops_after_two_malformed_responses(self, openai_client):
        create = openai_client.return_value.chat.completions.create
        create.return_value = self.completion("malformed model output")
        with self.assertLogs("app.llm_client", level="WARNING") as logs:
            with self.assertRaisesRegex(IssueAnalysisError, "incomplete or invalid reply draft"):
                draft_issue_reply("Example title", "Example body.", [])

        self.assertEqual(create.call_count, 2)
        self.assertIn("attempt=2 reason=invalid_schema retrying=False", logs.output[-1])
        self.assertNotIn("malformed model output", "\n".join(logs.output))

    @patch("app.llm_client.OpenAI")
    def test_does_not_retry_provider_failures_or_refusals(self, openai_client):
        create = openai_client.return_value.chat.completions.create
        failures = (
            (OpenAIError("private provider diagnostics"), "provider_error"),
            (self.completion(None, "content_filter"), "provider_refused"),
        )
        for response, reason in failures:
            with self.subTest(reason=reason):
                create.reset_mock()
                create.side_effect = [response]
                with self.assertLogs("app.llm_client", level="WARNING") as logs:
                    with self.assertRaises(IssueAnalysisError):
                        draft_issue_reply("Example title", "Example body.", [])

                create.assert_called_once()
                self.assertIn(f"attempt=1 reason={reason} retrying=False", logs.output[0])
                self.assertNotIn("private provider diagnostics", logs.output[0])


if __name__ == "__main__":
    unittest.main()
