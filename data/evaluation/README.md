---
pretty_name: MaintainerLens Issue Triage Benchmark
configs:
  - config_name: category
    data_files:
      - split: development
        path: psf-requests.csv
      - split: test
        path: fresh-holdout-40.csv
  - config_name: similarity
    data_files:
      - split: development
        path: similarity-development.csv
      - split: test
        path: similarity-holdout-4.csv
---

# MaintainerLens issue triage benchmark

These annotations cover public GitHub issues. Each record contains a repository,
issue number, title, and source URL. The category configuration adds
`expected_category`. Both configurations include `duplicate_group`, which is
scoped to the corresponding repository and CSV. An empty group means the issue
has no annotated duplicate in that pool.

| Configuration | Development | Test |
| --- | ---: | ---: |
| `category` | 27 issues | 40 issues |
| `similarity` | 40 issues | 40 issues |

The category labels are Bug, Question, Feature request, and Other. They reflect
maintainer triage intent as defined in the [project README](../../README.md).
The similarity development set contains maintainer-confirmed duplicate reports
and manually reviewed hard negatives. A duplicate link is relevant when the
query and candidate share a non-empty group in the same repository. The two
development tasks share four issue IDs. Neither selected test split shares
issue IDs with either selected development split. Additional CSVs in this
directory are supplementary evaluation sets.

Use development data for iteration and keep test data out of training and
tuning. This small, curated dataset measures performance on selected samples.
Candidate pools are limited to the annotated issues in each file, and missing
duplicate annotations can undercount useful suggestions. Full issue text is
retrieved separately for scoring and can change on GitHub over time. Local
snapshots preserve the text used for comparisons.

Use [Hugging Face Datasets](https://huggingface.co/docs/datasets/loading) to load
the CSVs locally. From the project root with `datasets` installed:

```python
from datasets import load_dataset

category = load_dataset("csv", data_files={
    "development": "data/evaluation/psf-requests.csv",
    "test": "data/evaluation/fresh-holdout-40.csv",
})
similarity = load_dataset("csv", data_files={
    "development": "data/evaluation/similarity-development.csv",
    "test": "data/evaluation/similarity-holdout-4.csv",
})
```
