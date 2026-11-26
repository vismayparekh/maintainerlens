# MaintainerLens

AI assistant for triaging GitHub issues and preparing pull request reviews.

## Run the Docker demo

Build the image and open the dashboard at `http://127.0.0.1:7860`:

```bash
docker build -t maintainerlens-demo .
docker run --rm -p 127.0.0.1:7860:7860 \
  --mount source=maintainerlens-demo-data,target=/app/data \
  maintainerlens-demo
```

FastAPI serves the compiled Vue dashboard and API on the same port. The named
volume keeps reply and issue reviews between container restarts. Public issue
and PR loading works without a token. To enable Hugging Face generation or
use GitHub authentication, add `--env-file .env` to `docker run`. To enable
semantic related-issue search, add `-e MAINTAINERLENS_SEMANTIC_SEARCH=1`. The
first semantic lookup downloads the embedding model. Mount a second named
volume at `/app/.cache` to reuse the downloaded model across runs.

Check the packaged dashboard and API, including live public repository loading:

```bash
python tests/smoke_demo.py http://127.0.0.1:7860 --repository psf/requests
```

GitHub Actions runs the Python tests, builds Vue, and starts the Docker demo on
pushes and pull requests. The CI smoke test exercises health, built assets,
and both API routes without GitHub or Hugging Face credentials.

## Run locally

Create and activate a virtual environment, then install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Start the Vue frontend and Python API in separate terminals.

Terminal 1, from the repository root:

```bash
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal (usually `http://localhost:5173`) and
enter a public GitHub repository as `owner/repo` or as a GitHub URL. The app
fetches up to 20 recent open issues to review and up to 100 recently updated
closed issues as historical candidates, excluding pull requests. No GitHub
token is required for this first version.

The original Gradio interface remains available from the repository root as a
legacy alternative:

```bash
python -m app.app
```

The Vue interface shows a searchable, category-filterable inbox beside the
selected issue's description and related issues. Potential matches compare each
open issue against the other open issues in the current batch and the fetched
closed-issue history. Up to three ranked suggestions link to candidate issues.
Similarity scores are signals, not probabilities, and suggestions are not
confirmed duplicates. Review them before taking action.

### Review public pull requests

In the Vue dashboard, switch to **Pull requests**, enter a public GitHub
repository, and select **Fetch pull requests**. The inbox lists up to 20
recently updated open pull requests, including drafts. Select a pull request
to see its description, branches, total changed-file count, line counts, and
a preview of up to 20 files. Issue references come from closing keywords and
GitHub issue links in the description.

Click **Generate review brief** for a summary and review checklist. Only this
action sends the selected description and file metadata to the configured
Hugging Face provider. The brief uses those inputs to suggest what to check.
Open the pull request on GitHub to inspect the diff and review status.

The equivalent API routes are `GET /api/pull-requests`,
`GET /api/pull-requests/{number}`, and `POST /api/pull-requests/{number}/analyze`.
Pass `repository=owner/repo` to each route. If you use a fine-grained token,
enable read access to pull requests for the repository.

### Evaluate PR review briefs

The [PR development manifest](data/evaluation/pr-review-development.csv)
contains six public PRs across scikit-learn and pandas, with two each for
documentation, bug fixes, and tests. Capture their metadata and generate one
brief per PR:

```bash
python -m app.pr_benchmark generate data/evaluation/pr-review-development.csv \
  --snapshot data/evaluation/snapshots/pr-review-development.json \
  --output data/evaluation/snapshots/pr-review-development-run-1.jsonl
```

The snapshot freezes PR descriptions and file metadata. A new run can use
the same snapshot with a fresh output path. Each result records the model,
elapsed inference time, and run ID. The scorer associates grades with the
specific generated run. Snapshots and generated drafts stay local.

Read the captured description and file metadata before grading the brief.
Score each dimension on a 0–2 scale. Give 2 for fully meeting the criterion,
1 for a useful result that needs a meaningful correction, and 0 for an absent
or materially misleading result.

| Dimension | Full-credit criterion |
| --- | --- |
| Change accuracy | Describes the visible scope correctly and attributes unverified results to the PR author. |
| Author intent | Captures the main purpose and preserves qualifications, uncertainty, and crossed-out proposals. |
| Actionable review checks | Provides concrete, PR-specific verification steps and avoids unsupported claims about implementation or tests. |

The first development run (Nov 26, 2026) generated all six briefs using the
configured DeepSeek V4.1 Flash model. An assistant graded each brief against
the captured metadata. This is a development baseline with one reviewer.

| Dimension | Score | Full-credit briefs |
| --- | ---: | ---: |
| Change accuracy | 12/12 | 6/6 |
| Author intent | 12/12 | 6/6 |
| Actionable review checks | 10/12 | 4/6 |

The [grade sheet](data/evaluation/pr-review-development-grades.csv) records
the findings and suggested corrections. The weaker checklists spent time on
PR-template fields or broadened review to a case the author excluded. Score
the existing run locally without calling the model again:

```bash
python -m app.pr_benchmark score \
  data/evaluation/snapshots/pr-review-development-run-1.jsonl \
  data/evaluation/pr-review-development-grades.csv
```

### Collect human PR feedback in Argilla

Install the optional SDK with `python -m pip install -r requirements-argilla.txt`.
Use an Argilla 2.8 server and set `ARGILLA_API_URL` and `ARGILLA_API_KEY` for
its owner account. See the [Argilla deployment guide](https://docs.argilla.io/latest/getting_started/how-to-deploy-argilla-with-docker/)
for another machine. The local setup in this workspace is available at
`http://127.0.0.1:6900` and keeps its login in the ignored
`.cache/argilla-local/credentials.env` file.
After a restart of this machine, run `bash .cache/argilla-local/start-local.sh`
from the project root to bring the existing local review server back up.

Import the same captured PRs and generated briefs used in the benchmark:

```bash
# With the workspace's local Argilla server
source .cache/argilla-local/credentials.env
python -m app.argilla_feedback import \
  --snapshot data/evaluation/snapshots/pr-review-development.json \
  --run data/evaluation/snapshots/pr-review-development-run-1.jsonl
```

Open **maintainerlens / pr-review-development** in Argilla. Score change
accuracy, author intent, and actionable review checks from 0 to 2. Enter a
replacement checklist if you would change the generated one, or use notes for
summary corrections. Import uses only the captured PR data and generated
briefs, so benchmark grades stay out of the annotation interface. Running the
same import again keeps the existing records and responses.
Use a different `--dataset` name when importing a new benchmark run.

Export submitted reviews to a fresh filename:

```bash
python -m app.argilla_feedback export \
  --output data/evaluation/snapshots/pr-review-human-grades.csv
```

The CSV contains one row per reviewer and PR. When multiple people annotate,
use `--reviewer-id` to export one reviewer for `app.pr_benchmark score`.
Compare those scores with the development grade sheet after the blind review.

A [second assistant review](data/evaluation/pr-review-assistant-second-pass.csv)
of the same six briefs matched all 18 initial ratings and supplied two replacement
checklists. This pass used the original benchmark context and outputs. The local
Argilla dataset `pr-review-assistant-second-pass` holds those submissions, and
`pr-review-development` remains available for independent human feedback.

### Background semantic matches

To enable hybrid related-issue search in the Vue dashboard, install the optional
dependencies and start the local API with semantic search enabled:

```bash
python -m pip install -r requirements-semantic.txt
MAINTAINERLENS_SEMANTIC_SEARCH=1 python -m uvicorn app.api:app \
  --host 127.0.0.1 --port 8000
```

Use `npm run dev` from `frontend/` as usual. The inbox and text matches load
first. If an open issue has no text matches, its Related issues panel shows
search progress and updates when the semantic results arrive. Existing text
matches stay visible. The first semantic lookup can take longer while the
model downloads or embeds the candidate issues. Later lookups reuse embeddings
for unchanged issue text within the same API process. Run a single API worker
for this local workflow so both requests can access the same candidate batch.

### AI summaries and category suggestions

Select an issue and click **Generate AI suggestion** to request a concise
summary and suggested category from Hugging Face Inference Providers.
The app sends only the selected issue's title and description, and only after
you click the button. The request is routed to a model provider, so use this
only for content you are comfortable sharing. Inference usage may incur charges.
The existing text-based category and similarity features continue to work
independently.
AI summaries are limited to 500 characters for review. If the provider returns
a longer summary, MaintainerLens shortens it at a word boundary and indicates
that in the interface.

After generating an AI suggestion, edit the summary or category in the review
panel and save it locally. Reviews are kept in the ignored
`data/maintainer_reviews.sqlite3` database; the issue body is not stored, and
feedback is not sent to Hugging Face. Use **Export saved reviews** to export
the issue link/title, AI suggestion, reviewed summary/category, and timestamp
to the ignored `data/maintainer_reviews.csv`. Saving another review for the
same issue updates its latest saved review.

Create a fine-grained Hugging Face token with **Make calls to Inference
Providers** permission, then add it to the project-root `.env` file:

```text
HF_TOKEN=your_hugging_face_token_here
```

The default model is `deepseek-ai/DeepSeek-V4.1-Flash:cheapest`. To choose
another model available through an Inference Provider, set `HF_MODEL` in `.env`.
Free Hugging Face accounts currently have no included Inference Providers
credits; check your account billing before using it. Restart the app after
changing environment settings. Never commit or share the token.

The Category column first checks recognized GitHub labels, then uses title
signals and common keywords in the issue title and body to suggest Bug,
Question, Feature request, or Other. This is a rule-based baseline, not a
trained classifier.

Use Bug for clearly broken existing behavior, Question when the author is
primarily seeking help or information without establishing a project defect,
and Feature request for a new software capability. Use Other for issues
outside those cases, such as automated CI/status notices without a concrete
product defect, credential or account maintenance, and promotional or
documentation-only requests. An error message or failed CI check alone does
not make an issue a Bug; a reported expected result or reproduction alone
does not prove a project defect. For troubleshooting questions where the
behavior may come from setup, configuration, or an incorrect expectation, use
Question unless a project defect is established.

### Draft and review maintainer replies

Select an issue and choose **Generate reply draft** or **Write from scratch**.
Edit the reply and the reproduction checklist, then choose **Save reply review**
to record them locally. Leave the checklist empty when reproduction does not
apply. **Copy reply** copies the reply for manual use. MaintainerLens sends the
selected issue text and up to three candidate issue titles and numbers to
Hugging Face only when you request a draft. It adds links from those candidates
when the model selects them. Replies are never posted automatically.

**Export reply reviews** downloads the original draft, the edited text, and the
elapsed time from starting either mode to clicking save. Assisted time includes
provider latency. Reviews are stored in the local SQLite database alongside
summary reviews. An issue can have more than one reply trial.

### Compare reply drafting time

1. Choose public issues of similar complexity and assign each issue to manual
   or assisted mode before participants see it. Give both groups access to the
   same issue descriptions and related issues. Alternate the mode order across
   participants and give each participant each issue only once.
2. Start the assigned mode at the same point in the review, then save when the
   reply and checklist are ready. Record generation failures and abandoned
   trials separately. The CSV contains completed trials.
3. Export reply reviews. Have a reviewer check the final reply and checklist
   against the issue, ideally without seeing the mode. Set `factual_error` to
   `yes` or `no` for each reviewed row and leave unchecked rows blank.
4. Run the report on the export for the trial cohort:

   ```bash
   python -m app.reply_benchmark ~/Downloads/maintainer_reply_trials.csv
   ```

The report shows median completion time per mode, the difference between
medians, factual errors among checked trials, and assisted drafts accepted
without edits. Collect human trials before reporting a time-savings result.

## Evaluate the baseline

Create a CSV of recent issues to label:

```bash
python -m app.evaluate export psf/requests --limit 20 \
  --output data/evaluation/psf-requests.csv
```

In the CSV, fill `expected_category` with `Bug`, `Question`, `Feature request`,
or `Other` (use Bug for clearly broken behavior, Question for help requests
without an established project defect, Feature request for new software
capabilities, and Other for the rest, including CI/status-only,
credential/account-maintenance, promotional, or documentation-only issues).
An error message or failed CI check alone does not make an issue a Bug, and a
reported expected result or reproduction alone does not prove a defect. Use
Question for troubleshooting where configuration or an incorrect expectation
may explain the behavior. Use the same
`duplicate_group` value for issues you confirm are duplicates; leave it blank
for issues that are not duplicates. The scorer fetches issue text from GitHub
by number and does not store issue bodies in the CSV. It ignores existing
GitHub labels when scoring categories so the text baseline is evaluated
independently.

Run the evaluation after annotating the rows:

```bash
python -m app.evaluate score data/evaluation/psf-requests.csv
```

### Evaluate similar-issue suggestions

The similarity-only CSV uses `repository`, `number`, `title`, `url`, and
`duplicate_group`; it does not require category labels. Issues in the same
duplicate group are treated as duplicate pairs. All other issue pairs within
each repository are treated as negatives, so include deliberately similar
non-duplicates as hard negatives.
Recommendations weight title overlap more heavily than body overlap and
downweight terms that appear in many issues in the comparison set.

Score the development set with:

```bash
python -m app.evaluate score-similarity \
  data/evaluation/similarity-development.csv
```

The development set contains maintainer-confirmed duplicate reports and
manually reviewed hard negatives. Keep it separate from the sealed validation
sets; do not use those validation results to tune similarity behavior.
The similarity holdout CSVs are sealed validation sets: score each only once,
and do not use their results to tune similarity behavior.

### Optional GitHub authentication

GitHub limits unauthenticated API requests. To avoid rate limits during
evaluation, create a GitHub token with read-only access to the public
repositories you evaluate, then add it to a `.env` file in the project root:

```text
GITHUB_TOKEN=your_token_here
```

The `.env` file is ignored by Git. Do not commit the token or share it in chat.
MaintainerLens uses it for API requests when present and continues to work
without a token otherwise.

The report includes category accuracy, per-category precision/recall/F1,
macro F1 across categories present in the reference labels, and similar-issue
pair precision/recall/F1. It also reports top-3 precision and recall across
directed query-to-candidate links. Precision uses the suggestions actually
returned and recall uses all annotated links in the evaluated pools.

### Reproduce the development baseline

The [dataset card](data/evaluation/README.md) documents the development and
test splits for Hugging Face Datasets. Capture the development issue text once,
then reuse the same snapshots for later comparisons:

```bash
python -m app.evaluate score data/evaluation/psf-requests.csv \
  --snapshot data/evaluation/snapshots/psf-requests.json
python -m app.evaluate score-similarity data/evaluation/similarity-development.csv \
  --snapshot data/evaluation/snapshots/similarity-development.json
```

The first run fetches public issue text from GitHub. Rerunning with the same
snapshot uses the saved text offline. The `snapshots/` directory is ignored by
Git to keep complete issue bodies out of the repository.

| Development baseline (Nov 26, 2026) | Result |
| --- | --- |
| Rule-based category classification, 27 issues | 26/27 correct, 95% macro F1 |
| Weighted text overlap, 40 issues | 93% top-3 precision, 67% top-3 recall, 78% pair F1 |

These curated development results provide a comparison point for future
models.

### Compare semantic duplicate retrieval

Install the optional dependencies and reuse the development snapshot:

```bash
python -m pip install -r requirements-semantic.txt
python -m app.evaluate score-similarity data/evaluation/similarity-development.csv \
  --snapshot data/evaluation/snapshots/similarity-development.json \
  --compare-semantic
```

[BGE-small](https://huggingface.co/BAAI/bge-small-en-v1.5) embeds each issue's
title and description locally. [FAISS](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances)
ranks candidates within the same repository by cosine similarity. Both methods
return up to three suggestions per issue. The semantic score floor defaults to
0.8 and can be changed with `--semantic-threshold` for development comparisons.

The first semantic run downloads the model into `.cache/fastembed/`. With the
model and snapshot available locally, set `HF_HUB_OFFLINE=1` to run offline.
Retrieval time is the median of three passes over all candidate pools. It includes
text processing or embedding, ranking, and filtering. Model loading and issue
fetching happen before timing begins.

| Method on the 40-issue development snapshot | Top-3 precision | Top-3 recall | Median retrieval time |
| --- | ---: | ---: | ---: |
| Weighted text overlap | 93% | 67% | 10.62 ms |
| BGE-small and FAISS, cosine floor 0.8 | 72% | 100% | 14.52 s |

The embedding method surfaced all 21 labeled duplicate pairs on this curated
sample and returned more false positives.

### Compare hybrid duplicate retrieval

With the same optional dependencies and snapshot, run:

```bash
HF_HUB_OFFLINE=1 python -m app.evaluate score-similarity \
  data/evaluation/similarity-development.csv \
  --snapshot data/evaluation/snapshots/similarity-development.json \
  --compare-hybrid
```

Run the semantic comparison once to cache the model before using offline mode.
The hybrid method keeps text-overlap results when available and uses FAISS for
queries with an empty result. Its default cosine cutoff is 0.85, selected on
the development set. A bounded in-memory cache reuses vectors by issue text,
so unchanged issues skip embedding on repeat runs and edits get fresh vectors.

Cold retrieval starts with an empty embedding cache and a loaded model. Warm
retrieval is the median of three repeat passes using the same cache.

| Method on the 40-issue development snapshot | Top-3 precision | Top-3 recall | Pair F1 | Retrieval time |
| --- | ---: | ---: | ---: | --- |
| Weighted text overlap | 93% | 67% | 78% | 11.15 ms median |
| Hybrid, cosine cutoff 0.85 | 90% | 90% | 93% | 11.18 s cold, 11.91 ms warm median |

The hybrid recovered 20 of 21 labeled duplicate pairs, compared with 14 for
text overlap on the development set.

### Similarity holdout result

The 40-issue `similarity-holdout-4.csv` split was scored once at the 0.85 cutoff
selected on development data. Both methods used the same candidate pools.

| Method | Labeled pairs recovered | Top-3 precision | Top-3 recall | Pair F1 | Retrieval time |
| --- | ---: | ---: | ---: | ---: | --- |
| Weighted text overlap | 10 / 20 | 83% | 50% | 62% | 17.26 ms median |
| Hybrid, cosine cutoff 0.85 | 17 / 20 | 89% | 85% | 87% | 11.94 s cold, 18.37 ms warm median |

Timings are from one local machine and exclude GitHub fetching and model
loading. The other holdout splits were left unscored in this run.

## Run tests

```bash
python -m unittest discover -s tests
```
