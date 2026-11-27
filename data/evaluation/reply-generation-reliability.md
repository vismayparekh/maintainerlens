# Reply-generation reliability

The updated generator allows one retry for incomplete or malformed output.
The first call has a 4,096-token budget and the retry can use up to 8,192.
The model still has to return the same short reply and checklist schema.
Provider errors and refusals end the request. Transport-level retries are
disabled for this workflow so a draft uses at most two provider calls.
Failure logs record the attempt, reason, and retry decision without including
issue text, generated output, credentials, or provider error messages.

The revised prompt asks the model to inspect code, output, version tables,
and attempted workarounds before asking a question. It should ask at most
two questions and skip them if it already has enough to triage the issue.

## Results

The rerun used the four issues from the
[expanded holdout](expanded-holdout-results.md#maintainer-replies).
A fresh comparison ran both versions on four additional issue descriptions,
alternating the order of old and updated code. Both variants used
`deepseek-ai/DeepSeek-V4.1-Flash:cheapest` and identical captured inputs with
an empty related-issue list. The historical rerun comparison spans separate
provider sessions. These samples are small and provider latency varies.

| Cases and version | First-attempt drafts | Drafts with one retry allowed | Median first-attempt elapsed time | Median total elapsed time | Drafts asking for or marking supplied information as missing |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original four, previous version | 1 / 4 | 3 / 4 | 8.71 s | 14.77 s | 1 / 3 |
| Original four, updated version | 4 / 4 | 4 / 4 | 6.32 s | 6.32 s | 0 / 4 |
| Fresh four, previous version | 4 / 4 | 4 / 4 | 7.05 s | 7.05 s | 1 / 4 |
| Fresh four, updated version | 4 / 4 | 4 / 4 | 5.39 s | 5.39 s | 0 / 4 |

Median elapsed time includes both successful and failed cases. The previous
version's original-case totals combine the first attempt and separately
timed manual retry, without idle time between them. The updated run needed
no retry. Automated tests exercise recovery after empty, truncated, and
invalid responses, and confirm the retry limit when failures persist.

### Fresh comparison cases

| Issue | Previous version | Updated version | Source-review observation |
| --- | ---: | ---: | --- |
| [Pillow #9385](https://github.com/python-pillow/Pillow/issues/9385) | 7.80 s | 7.55 s | Both asked for relevant details in text. The updated draft added a version-check command absent from the report. |
| [Typer #1787](https://github.com/fastapi/typer/issues/1787) | 6.31 s | 4.96 s | The previous draft asked for the invocation already shown. The updated draft skipped the question but drew an inference about the error from a truncated output sample. |
| [uv #23323](https://github.com/astral-sh/uv/issues/23323) | 3.91 s | 5.82 s | The updated draft skipped setup questions and correctly treated the flag as a proposal. It also claimed it had logged the issue for review, an action the app does not perform. |
| [pip-tools #2208](https://github.com/jazzband/pip-tools/issues/2208) | 7.97 s | 2.80 s | Both drafts left the reproduction checklist empty. The updated draft acknowledged the documentation proposal without asking for implementation details. |

On the original pip-tools case, the updated reply acknowledged the
workaround instead of asking the reporter to confirm it again. It still
blurred the suspected starting version of the regression with the
environment used for reproduction. The review checked all completed drafts
against the issue text and recorded assistant judgments. The observed
reduction in repeated questions does not establish factual accuracy on other
projects or estimate time saved by maintainers.
[pip-tools #2232](https://github.com/jazzband/pip-tools/issues/2232)
