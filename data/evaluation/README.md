---
pretty_name: MaintainerLens Issue Triage Benchmark
license: mit
language:
  - en
tags:
  - github
  - issue-triage
  - duplicate-detection
configs:
  - config_name: category
    default: true
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
has no annotated duplicate in that pool. Project-created annotations are
provided under the MIT license. Issue titles are attributable to their linked
GitHub sources.

| Configuration | Development | Test |
| --- | ---: | ---: |
| `category` | 27 issues | 40 issues |
| `similarity` | 40 issues | 40 issues |

The category labels are Bug, Question, Feature request, and Other. They reflect
maintainer triage intent as defined in the
[MaintainerLens project README](https://github.com/vismayparekh/maintainerlens#evaluate-the-baseline).
The category test split has 10 cases per label, so its class balance should
not be used to estimate the frequency of categories in production.
The similarity development set contains maintainer-confirmed duplicate reports
and manually reviewed hard negatives. A duplicate link is relevant when the
query and candidate share a non-empty group in the same repository. The two
development tasks share four issue IDs. Neither selected test split shares
issue IDs with either selected development split or with the other test split.

Use development data for iteration and keep test data out of training and
tuning. This small, curated dataset measures performance on selected samples.
Candidate pools are limited to the annotated issues in each file, and missing
duplicate annotations can undercount useful suggestions. Full issue text is
retrieved separately for scoring and can change on GitHub over time. Local
snapshots preserve the text used for comparisons.

## Load the benchmark

Use [Hugging Face Datasets](https://huggingface.co/docs/datasets/loading):

```python
from datasets import load_dataset

repo = "vismayparekh/maintainerlens-benchmark"
category = load_dataset(repo, "category")
similarity = load_dataset(repo, "similarity")
```

The [project source](https://github.com/vismayparekh/maintainerlens/tree/main/data/evaluation)
also provides the CSVs for local scoring. The repository's
[evaluation instructions](https://github.com/vismayparekh/maintainerlens#reproduce-the-development-baseline)
document baseline results and how to run the scorer.
