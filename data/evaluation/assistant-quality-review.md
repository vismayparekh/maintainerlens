# MaintainerLens assistant quality review

Codex reviewed the available evidence and recorded the results as assistant
judgments. The independent human review count remains zero in the recorded
study. Periodic retraining still needs reviewed feedback.

## Pull request briefs

Scored the six captured scikit-learn and pandas briefs with the existing
review rubric and the second-pass assistant grades. The reviewer considered
the captured descriptions and file metadata.

| Criterion | Points | Briefs with full credit |
| --- | ---: | ---: |
| Change accuracy | 12 / 12 | 6 / 6 |
| Author intent | 12 / 12 | 6 / 6 |
| Actionable review checklist | 10 / 12 | 4 / 6 |

Two pandas checklists still need editing. The any/all documentation brief
spent checks on template fields and the AI-use disclosure. The
daylight-saving regression brief spent a check on a follow-up the author
had placed outside this change. Replacement checks are in the
[assistant grades](pr-review-assistant-second-pass.csv).

## Issue labels

The 32 records in the original Argilla queue already had a local assistant
second pass. It returned 15 Bug, 12 Question, one Other, and four Unclear.
The first and second assistant passes differed on four records. Those
assistant reviews remain outside the Argilla human consensus.

I also audited the separate 32-issue classifier holdout using frozen issue
titles and descriptions. I recorded the [assistant labels and evidence](classifier-external-32-assistant-audit.csv)
before joining the labels to the cached model predictions. The assistant
disagreed with five of the source GitHub tags, including three cases marked
Unclear. For example, Streamlit's feedback poll is Other under this rubric,
and Flask's concurrent gevent failure reports a concrete defect even
though the sampled tag was documentation.

| Method | Correct on 29 assistant-labeled cases | Macro F1 |
| --- | ---: | ---: |
| Live text rules | 24 / 29 | 82.5% |
| Classifier v1 | 20 / 29 | 69.2% |
| Classifier v2 | 24 / 29 | 84.4% |
| Classifier v3 | 22 / 29 | 76.0% |

This sensitivity check excludes the three Unclear cases. The same two
methods each got 24 right, and their macro-F1 ordering changed under the
assistant labels. The original [32-issue benchmark](2026-11-27-results.md)
remains the reference for the published scores. Live triage continues to
use the text rules.

## Reply quality and timing

I graded three recorded replies using the blinded sheet, where drafting
mode, elapsed time, and original drafts are hidden. I scored a reply as
having a factual error when it contained an incorrect API call or made a
specific claim the source report did not establish. I joined the grades to
the timing records after recording the judgments.

- One reply suggested passing `as_index=False` to `nunique()`. The option
  belongs on `groupby()`. [pandas issue #72276](https://github.com/pandas-dev/pandas/issues/72276) ·
  [pandas nunique reference](https://pandas.pydata.org/docs/reference/api/pandas.api.typing.SeriesGroupBy.nunique.html) ·
  [pandas groupby guide](https://pandas.pydata.org/docs/user_guide/groupby.html)
- Another reply attributed the reported error to an exact main-branch
  commit. The issue reports that main is affected and lists a hash in
  its installed-versions block. It leaves their precise relationship
  ambiguous. The third reply framed that relationship as a question.
  [pandas issue #72353](https://github.com/pandas-dev/pandas/issues/72353)

| Mode | Recorded trials | Recorded drafting time | Replies with an error flagged by Codex |
| --- | ---: | ---: | ---: |
| Manual | 2 | 7.28 s median | 1 / 2 |
| Assisted | 1 | 65.77 s | 1 / 1 |

The assisted draft was saved unchanged in the one assisted trial. These
three entries span two issues and do not follow the planned assignments.
The paired human time-savings estimate remains unavailable. The pilot
texts and per-trial grades remain in the local ignored directory.
