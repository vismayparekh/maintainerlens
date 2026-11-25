# MaintainerLens

AI assistant for summarizing, classifying, and finding duplicate GitHub issues.

## Run locally

Create and activate a virtual environment, then install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Start the app from the repository root:

```bash
python -m app.app
```

Enter a public GitHub repository as `owner/repo` or as a GitHub URL. The app
fetches up to 20 recent open issues, excluding pull requests. No GitHub token is
required for this first version.

The Summary column currently uses a simple extractive baseline: it shows up to
the first two sentences of each issue description, capped at 240 characters.
It does not call an AI model yet.

The Potential matches column compares the fetched issues using token overlap.
It shows up to three suggestions with at least 20% overlap; it only compares
issues in the current batch, and matches are not confirmed duplicates.

The Category column first checks recognized GitHub labels, then uses title
signals and common keywords in the issue title and body to suggest Bug,
Question, Feature request, or Other. This is a rule-based baseline, not a
trained classifier.

## Evaluate the baseline

Create a CSV of recent issues to label:

```bash
python -m app.evaluate export psf/requests --limit 20 \
  --output data/evaluation/psf-requests.csv
```

In the CSV, fill `expected_category` with `Bug`, `Question`, `Feature request`,
or `Other` (use Bug for broken behavior, Question for help requests, Feature
request for new capabilities, and Other for the rest). Use the same
`duplicate_group` value for issues you confirm are duplicates; leave it blank
for issues that are not duplicates. The scorer fetches issue text from GitHub
by number and does not store issue bodies in the CSV. It ignores existing
GitHub labels when scoring categories so the text baseline is evaluated
independently.

Run the evaluation after annotating the rows:

```bash
python -m app.evaluate score data/evaluation/psf-requests.csv
```

The report includes category accuracy, per-category precision/recall/F1, and
similar-issue pair precision/recall/F1.

## Run tests

```bash
python -m unittest discover -s tests
```
