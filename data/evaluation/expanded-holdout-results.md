# Expanded MaintainerLens holdouts

This round adds cases to the earlier benchmarks and scores the existing
rules, retrieval methods, and models. The case lists were fixed before
scoring. Issue text, PR metadata snapshots, and raw generations used for the
run are kept locally. The manifests reference public GitHub records.

## Issue classification

The [39-issue holdout](classifier-cross-repository-39.csv) spans uv, Pillow,
Typer, and pip-tools. Each project supplies three bugs, three questions,
and three feature requests. uv, Pillow, and pip-tools each also supply
one documentation issue mapped to Other. GitHub tags provide weak labels.
The models and text rules received the same frozen titles and descriptions,
with labels excluded from their inputs. All four repos are outside the
classifier training sources.

| Method | Macro F1 | Correct | Bug recall | Question recall | Feature request recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Live text rules | 57.8% | 24 / 39 | 8 / 12 | 9 / 12 | 5 / 12 |
| Classifier v1 | 62.3% | 24 / 39 | 7 / 12 | 9 / 12 | 6 / 12 |
| Classifier v2 | 63.7% | 25 / 39 | 10 / 12 | 8 / 12 | 5 / 12 |
| Classifier v3 | 63.8% | 25 / 39 | 9 / 12 | 9 / 12 | 5 / 12 |

Each method correctly identified two of the three documentation issues. V2
caught the most bugs on this sample. V2 and v3 achieved the same accuracy,
and their macro F1 scores differ by 0.1 percentage points. The previous
[32-issue holdout](2026-11-27-results.md#classifier-holdout-and-release)
favored the rules. The sample size, disagreements across the two holdouts,
and tags that may describe project-specific triage conventions all matter
when deciding which model to use. Feature request recall was low for every
method on this new set.

## Duplicate retrieval

The [28-issue holdout](similarity-verified-holdout-28.csv) covers six
repositories. It contains eight duplicate pairs, six same-topic issues that
ask for different changes, and six issues with no known match in their
repository's candidate pool. Every positive pair has a GitHub duplicate
closure and a public comment by the person who closed it naming the paired
issue. The negative examples are judgments about these small, fixed pools.

| Method | Annotated pairs retrieved | Top-3 precision | Top-3 recall | Lookalikes suggested a match | No-known-match issues suggested a match |
| --- | ---: | ---: | ---: | ---: | ---: |
| Weighted text overlap | 2 / 8 | 100% | 25% | 0 / 6 | 0 / 6 |
| Text overlap + FAISS fallback at 0.85 | 5 / 8 | 100% | 62.5% | 0 / 6 | 0 / 6 |

The FAISS fallback uses the threshold already selected on development
data. The 100% precision figures describe two and five returned pairs,
respectively. Both methods missed confirmed duplicates, and the small
candidate pools can make precision higher than it would be in a larger
live repository. Local warm retrieval across the pools took about 7 ms
with overlap and 8 ms with the hybrid. The hybrid's cold embedding pass
took about 10.5 seconds.

## PR review briefs

The [12-PR holdout](pr-review-holdout.csv) includes three bug fixes, three
documentation changes, three test changes, and three refactors across
Pillow, Starlette, pandas, uv, and Typer. The existing DeepSeek generator
returned all 12 briefs in the app's format. One assistant graded the
generated summaries and checks against the frozen PR descriptions and file
metadata. [Case grades](pr-review-holdout-assistant-grades.csv)

| Criterion | Points | Briefs with full credit |
| --- | ---: | ---: |
| Change accuracy | 24 / 24 | 12 / 12 |
| Author intent | 24 / 24 | 12 / 12 |
| Actionable checks | 22 / 24 | 10 / 12 |

The two weaker checklists devoted space to PR template fields, an
out-of-scope layout issue, or an AI disclaimer's manual-review statement.
These are artifact-level judgments from a single assistant reviewer. They
do not establish whether the underlying PRs were correct.

## Maintainer replies

Four new issue descriptions were used to check draft success and whether the
drafts invented API calls or command options. One of the four produced a
draft on the first attempt. Retrying the three failures once yielded two
more drafts. The three completed drafts did not contain an invalid API
call or flag in this review. One nevertheless requested confirmation of a
workaround the reporter had already checked. Typer #1353 returned
incomplete output on the retry. [Case grades](reply-holdout-assistant-grades.csv) ·
[pip-tools issue #2232](https://github.com/jazzband/pip-tools/issues/2232) ·
[pip-tools CLI reference](https://pip-tools.readthedocs.io/_/downloads/en/stable/pdf/)

The next improvement to test is reply-generation reliability, followed by
grounding checks for facts already supplied in issue bodies. Keep the
existing holdouts available for regression comparisons and use fresh
cases to choose future training or similarity thresholds.
