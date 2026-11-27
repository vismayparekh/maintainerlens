# MaintainerLens

AI assistant for triaging GitHub issues and preparing pull request reviews.

## Project links

| Resource | What you can explore |
| --- | --- |
| [Live app on Render](https://maintainerlens-live.onrender.com/) | Load public GitHub repositories, triage issues, and generate replies and PR review briefs. |
| [GitHub source code](https://github.com/vismayparekh/maintainerlens) | Browse the Vue frontend, FastAPI backend, setup instructions, and tests. |
| [Hugging Face Space](https://huggingface.co/spaces/vismayparekh/maintainerlens-demo) | Walk through saved examples and benchmark results. |
| [Hugging Face benchmark dataset](https://huggingface.co/datasets/vismayparekh/maintainerlens-benchmark) | Explore the issue-classification and duplicate-retrieval benchmarks. |
| [Hugging Face classifier and model card](https://huggingface.co/vismayparekh/maintainerlens-issue-classifier) | Download the trained issue classifier and read its holdout results. |
| [Live FastAPI docs](https://maintainerlens-live.onrender.com/docs) | Explore the API endpoints in Swagger UI. |
| [Evaluation report](data/evaluation/2026-11-27-results.md) | See live response times, classifier comparisons, and the LoRA experiment. |
| [Assistant quality review](data/evaluation/assistant-quality-review.md) | Review findings on reply accuracy, PR checklists, and issue labels. |

## Portfolio demo

The static Vue build shows curated issues, pull requests, and discussions from
scikit-learn and pandas. It includes saved severity and label suggestions, a
related-issue match, PR review briefs, an edited reply, and a discussion with
an accepted answer. It also shows the classification, duplicate-retrieval, and
PR checklist benchmark results. Descriptions are paraphrased and link to the
original public GitHub records.

Build and preview the portfolio version locally without starting FastAPI:

```bash
cd frontend
npm ci
npm run build:demo
npm run preview -- --outDir dist-demo
```

The portfolio build runs in the browser with bundled examples. The Docker
app below provides live GitHub loading, private-reporting guidance, new AI
suggestions, and review storage.

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
repository API routing, and public hosting restrictions without GitHub or
Hugging Face credentials.

## Host the live demo on Render

The [Render blueprint](render.yaml) builds the existing Dockerfile as one
Free web service with `/api/health` as its health check. Connect this repository
in the Render dashboard and create a Blueprint from the branch containing
`render.yaml`. Use a workspace without a payment method for a preview that
suspends when included usage runs out. The service can take about a minute
to wake after inactivity. [Render Free limits](https://render.com/docs/free)

Hosted mode lets visitors browse current public issues and pull requests
using GitHub REST. Set `GITHUB_TOKEN` in Render's environment settings with
read access to public repositories. Hosted REST calls authenticate only after
verifying the repository is public. Discussions also uses this token.
Hosted review storage and export are disabled. The local Docker run keeps
them available.

To enable fresh AI generation, add an inference credential as `HF_TOKEN`
and optionally set `HF_MODEL` in the Render environment. The Blueprint
enables `MAINTAINERLENS_PUBLIC_GENERATION=1`, so visitors can generate issue
summaries, replies, and PR briefs without an access key. All visitors share
10 generation attempts per UTC day on the running service. An instance
restart resets the counter. Track actual provider charges in
[Hugging Face inference usage](https://huggingface.co/settings/inference-providers/overview).

Set `MAINTAINERLENS_PUBLIC_GENERATION=0` to require the generated
`MAINTAINERLENS_DEMO_ACCESS_KEY` for generation again. API clients pass that
key in the `X-MaintainerLens-Access-Key` request header. Keep provider
credentials in Render's environment settings.

For a deployment created without a provider key, run the credential-free
smoke test against its HTTPS URL:

```bash
python tests/smoke_demo.py https://<service>.onrender.com --public-demo
```

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

### Review suggested GitHub labels

After fetching an issue inbox, open an issue to see **Suggested GitHub labels**
below its description. MaintainerLens reads the repository's label catalog
once per inbox and uses the exact GitHub label names. It can suggest one
category label and up to two topics supported by the title. It skips existing
labels, archived labels, and extra category labels when a category is already
present. Use the issue link to apply any suggestions you agree with on GitHub.

API callers can request suggestions with
`GET /api/issues?repository=owner/repo&include_label_suggestions=true`.
Suggestions are returned as `suggested_labels` on each issue. A catalog
failure sets `label_suggestions_status` to `unavailable` and still returns the
issues and their related context. The portfolio build uses bundled examples.

### Review issue severity

The live Issues inbox suggests **High** for reported startup blockers or
data loss, **Moderate** for a concrete failure in a workflow, and **Low**
for an explicitly cosmetic or wording issue. It shows **Needs review** when
the reported impact is unclear or the issue is a question or feature request.
Each suggestion includes its reason. The inbox keeps its existing order.

Use **Severity decision** to save your choice in the current browser, or
choose **Use suggestion** to clear your override. The issue API returns the
original suggestion under `severity` with a `level` and `reason`. The browser
choice is local to the issue and device.

### Route possible security reports

When an issue has a security-related label or its visible text contains a
vulnerability signal, the issue view offers the repository's GitHub security
page and security policy. Use **Report a vulnerability** on GitHub when the
repository enables it. The policy may provide a private contact instead.
**Copy private-reporting reply** copies a short message that keeps further
technical details out of the public thread.

Flagged issues use the local reporting guidance and stay out of related-issue
results and AI requests. The API returns the guidance as `security_guidance`.
Its reply endpoint returns a local message and an empty checklist when it
detects a possible security report in the submitted text.

### Read public GitHub Discussions

Set `GITHUB_TOKEN` in the backend environment using a token with read access to
the public repository's Discussions, then restart FastAPI. Choose
**Discussions**, enter a repository such as `pandas-dev/pandas`, and select
**Fetch discussions**. Open a thread to read its post, existing labels, accepted
answer when available, and a preview of up to five recent comments.

The API exposes `GET /api/discussions?repository=owner/repo&limit=10` and
`GET /api/discussions/{number}?repository=owner/repo`. A repository with
Discussions disabled has a separate empty state. Use the thread link for the
full conversation.

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
Reply generation can make one additional provider call when the output is
incomplete or fails schema validation. See the [reply reliability benchmark](data/evaluation/reply-generation-reliability.md) for the measured comparison.

**Export reply reviews** downloads the original draft, the edited text, and the
elapsed time from starting either mode to clicking save. Assisted time includes
provider latency. Reviews are stored in the local SQLite database alongside
summary reviews. An issue can have more than one reply trial.

### Compare reply drafting time

The [reply pilot](data/evaluation/reply-pilot.csv) uses eight public GitHub
issues from pandas and Pydantic. Recruit at least two reviewers and assign
sequences A and B in turn. Each reviewer sees all eight issues once, with four
manual and four assisted replies. Sequence B swaps the assigned mode for every
issue, so each case can be compared across reviewers. The study covers reply
drafting with the issue description as context. It leaves related-issue search
and AI summaries out of both conditions.

1. Install the dependencies from **Run locally** and configure the Hugging
   Face provider. Build the dashboard once, then serve it with a separate
   SQLite file per participant so each export only contains their study trials.
   Stop and restart the pilot server with a fresh path between participants.

   ```bash
   (cd frontend && npm ci && npm run build)
   MAINTAINERLENS_REVIEW_DB=.cache/reply-pilot/reviewer-01.sqlite3 \
     python -m uvicorn app.web:app --host 127.0.0.1 --port 7872
   ```

2. Print the assigned sequence from another terminal and give that reviewer only
   their assigned list. Use `plan B` for the second reviewer.

   ```bash
   python -m app.reply_pilot plan A --base-url http://127.0.0.1:7872
   ```

3. For each link in order, read the issue in MaintainerLens and then click
   **Write from scratch** (manual) or **Generate reply draft** (assisted).
   Draft a reply you would send as a maintainer and add a reproduction checklist
   only where it applies. Use the same instructions in both modes. Use only the
   supplied issue description and the assigned mode. Click **Save reply review**
   once when the reply is ready. If a draft fails or a case is abandoned, log the
   reason and move on. The timer includes generation latency and records
   completed trials. Use **Export reply reviews** and keep a separate CSV for
   each participant, even if it only contains the header.

4. Create a shuffled quality-review sheet that hides modes, times, and original
   drafts. Ask an independent reviewer to compare the final reply and checklist
   with the issue description. Mark `factual_error` as `yes` for any factual
   error or unsupported claim and `no` otherwise. Leave unchecked rows blank.
   Keep exports and grades local unless participants agree to share them.

   ```bash
   python -m app.reply_pilot blind --group-a reviewer-01.csv \
     --group-b reviewer-02.csv --output blinded-replies.csv
   python -m app.reply_pilot score --group-a reviewer-01.csv \
     --group-b reviewer-02.csv --grades blinded-replies.csv
   ```

Repeat `--group-a` and `--group-b` as more participants join. Report completion
counts, factual errors among checked replies, unchanged assisted drafts, and the
case-matched drafting-time difference. The last metric compares median manual
and assisted times within each issue completed in both modes, then takes the
median of those differences. Use the same model and collect participant runs
close together because the public issue descriptions can change. Describe the
findings as an exploratory pilot with the exact participant count. The
`python -m app.reply_benchmark <export.csv>` command still summarizes one
standalone export.

## Evaluate the baseline

The [evaluation report](data/evaluation/2026-11-27-results.md) records live
response times, the classifier holdout, and the LoRA experiment. The
[assistant quality review](data/evaluation/assistant-quality-review.md)
covers PR checklists, issue labels, and reply accuracy. The
[expanded holdouts](data/evaluation/expanded-holdout-results.md) add
39 issues for classification, 28 for duplicate retrieval, and 12 PR briefs. The
[published classifier](https://huggingface.co/vismayparekh/maintainerlens-issue-classifier)
includes its model card and holdout manifest.

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

The [published Hugging Face benchmark](https://huggingface.co/datasets/vismayparekh/maintainerlens-benchmark)
contains the category and duplicate-retrieval development and test splits.
Use the [initial release revision](https://huggingface.co/datasets/vismayparekh/maintainerlens-benchmark/tree/b8921856888c18153275eea26ec254b85f7ee7f2)
to pin benchmark membership. The [dataset card](data/evaluation/README.md)
documents the schema and intended use. Capture the development issue text
once, then reuse the same snapshots for later comparisons:

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

### Compare a trained issue classifier

The first trained baseline uses word TF-IDF and logistic regression. It was
trained locally on 594 public issues from VS Code, JupyterLab, Sphinx, and
HTTPX. Those repositories are outside the published benchmark. GitHub labels
provided weak supervision for 160 bugs, 160 questions, 160 feature requests,
and 114 documentation issues mapped to Other. The model uses titles and
descriptions at inference time.

Both methods received the same frozen issue text, with GitHub labels
excluded, on the published 40-issue category test split.

| Method | Macro F1 | Accuracy | Bug recall |
| --- | ---: | ---: | ---: |
| Text rules | 74.5% | 30 / 40 | 9 / 10 |
| Trained classifier | 78.8% | 32 / 40 | 4 / 10 |

The trained classifier correctly predicted all 10 feature requests and all
10 Other cases on this sample. It misclassified six bugs as questions.
The application continues to use the rules for live triage. Use separate
development data to improve the bug/question distinction and a fresh test set
to assess that revision.

From the project root with the virtual environment active:

```bash
python -m pip install -r requirements-training.txt
python -m app.train_classifier collect .cache/issue-classifier/training.json
python -m app.train_classifier train .cache/issue-classifier/training.json \
  .cache/issue-classifier/model-v1
python -m app.train_classifier compare .cache/issue-classifier/model-v1 \
  data/evaluation/fresh-holdout-40.csv \
  --snapshot .cache/issue-classifier/holdout.json \
  --output .cache/issue-classifier/holdout-results.json
```

The commands use new output paths. Reuse existing text snapshots to reproduce
a run, since GitHub issue text and labels can change. Issue bodies, the saved
model, per-class scores, and per-issue predictions stay in the ignored cache.

#### Bug versus support-question follow-up

Codex reviewed the reports and recorded a rationale for each label in
[16 curated Poetry examples](data/evaluation/bug-question-curated.csv) and a
[24-issue holdout](data/evaluation/bug-question-holdout.csv). The holdout has
four bugs and four support questions each from Textual, Ruff, and Pyright.
These repositories are outside both models' training data and the earlier
benchmarks. The labels were fixed before scoring and would benefit from
independent review.

The revision trained on the original 594 examples plus the 16 curated cases.
It weighted curated examples six times as much as weakly labeled examples
and multiplied the balanced Bug class weight by 1.35. All three methods
could predict any of the four original categories. Macro F1 averages the two
categories represented in this holdout.

| Method | Bugs caught | Questions correct | Correct overall | Macro F1 |
| --- | ---: | ---: | ---: | ---: |
| Text rules | 7 / 12 | 3 / 12 | 10 / 24 | 50.4% |
| First trained model | 8 / 12 | 6 / 12 | 14 / 24 | 68.6% |
| Revised model | 9 / 12 | 3 / 12 | 12 / 24 | 56.8% |

The revision caught one additional bug and classified two questions as bugs.
It also sent more questions to Feature request. The first trained model
performed better overall on this follow-up. The live app still uses the rules.
This small, deliberately balanced holdout covers the bug/question distinction.
The earlier four-category test remains the source for the broader comparison.

```bash
python -m app.train_classifier train .cache/issue-classifier/training.json \
  .cache/issue-classifier/model-v2 --curated data/evaluation/bug-question-curated.csv \
  --curated-snapshot .cache/issue-classifier/bug-question-curated.json
python -m app.train_classifier compare .cache/issue-classifier/model-v1 \
  data/evaluation/bug-question-holdout.csv --candidate .cache/issue-classifier/model-v2 \
  --snapshot .cache/issue-classifier/bug-question-holdout.json \
  --output .cache/issue-classifier/bug-question-results.json
```

#### Collect independent issue labels in Argilla

The local workspace **maintainerlens-issue-review** has a 32-issue queue,
**bug-question-blind-01**, drawn from pre-commit, Black, aiohttp, and mypy.
GitHub labels were used to find candidates. Argilla shows the captured title
and description, leaving source labels and model suggestions out of the
review screen. The cases come from repositories outside the classifier's
existing training data and both scored classification holdouts.

Ask two reviewers to open the same queue with separate Argilla annotator
accounts. Each reviewer chooses a category and writes one detail from the
report that supports it. Ask them to use **Unclear** where the report leaves
the distinction open and to work independently from the captured text.

Export with the workspace owner's API credentials:

```bash
source .cache/argilla-local/credentials.env
python -m app.argilla_issue_review status
python -m app.argilla_issue_review export \
  --reviews .cache/issue-classifier/bug-question-blind-01-reviews.csv \
  --consensus .cache/issue-classifier/bug-question-blind-01-consensus.csv
```

The consensus CSV includes cases with at least two matching submitted labels
and excludes disagreements and **Unclear**. The individual review file
retains the evidence for adjudication. The consensus CSV and its captured
snapshot can be passed to `app.train_classifier train` with `--curated` and
`--curated-snapshot`. Use new output paths for each export.

To recreate the Argilla queue, import the existing snapshot with
`python -m app.argilla_issue_review import .cache/issue-classifier/bug-question-blind-01.json`.
The `collect` command samples a new snapshot from the then-current public
issues and should be used with a fresh dataset name.

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
