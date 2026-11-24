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

## Run tests

```bash
python -m unittest discover -s tests
```
