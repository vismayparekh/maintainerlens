import argparse
import json
from html.parser import HTMLParser
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class DashboardAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "module" and attrs.get("src"):
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href"):
            self.assets.append(attrs["href"])


def verify_demo(base_url, repository=None):
    base_url = base_url.rstrip("/")
    deadline = monotonic() + 30
    while True:
        try:
            with urlopen(f"{base_url}/api/health", timeout=3) as response:
                if json.load(response) != {"status": "ok"}:
                    raise ValueError("Unexpected health response.")
            break
        except (URLError, ConnectionError, TimeoutError):
            if monotonic() >= deadline:
                raise
            sleep(1)

    with urlopen(f"{base_url}/", timeout=5) as response:
        index = response.read().decode("utf-8")
    assets = DashboardAssets()
    assets.feed(index)
    if "MaintainerLens" not in index or not assets.assets:
        raise ValueError("The root page did not contain the built MaintainerLens dashboard.")
    for asset in assets.assets:
        parsed = urlsplit(asset)
        if parsed.netloc or parsed.scheme or not parsed.path.startswith("/assets/"):
            raise ValueError(f"Unexpected dashboard asset URL: {asset}")
        with urlopen(f"{base_url}{asset}", timeout=5) as response:
            if not response.read(1):
                raise ValueError(f"Dashboard asset is empty: {asset}")

    for route in ("issues", "pull-requests", "discussions"):
        invalid = urlencode({"repository": "invalid"})
        try:
            urlopen(f"{base_url}/api/{route}?{invalid}", timeout=5).close()
        except HTTPError as exc:
            with exc:
                if exc.code != 400 or not json.load(exc).get("detail"):
                    raise ValueError(f"Unexpected validation response from /api/{route}.") from exc
        else:
            raise ValueError(f"/api/{route} accepted an invalid repository.")

    suspected_report = json.dumps({
        "title": "Possible security vulnerability",
        "body": "Synthetic smoke-test report.",
    }).encode("utf-8")
    request = Request(
        f"{base_url}/api/issues/draft-reply",
        data=suspected_report,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        guidance = json.load(response)
    if guidance["checklist"] or "private reporting" not in guidance["reply"].casefold():
        raise ValueError("Suspected security reports must receive the local private-reporting reply.")

    print(
        f"Health, dashboard assets ({len(assets.assets)}), issue/PR/discussion routes, "
        "and private-reporting fallback passed."
    )
    if repository:
        query = urlencode({"repository": repository, "limit": 1})
        with urlopen(f"{base_url}/api/issues?{query}", timeout=60) as response:
            issues = json.load(response)["issues"]
        with urlopen(f"{base_url}/api/pull-requests?{query}", timeout=30) as response:
            pulls = json.load(response)["pull_requests"]
        if not issues or not pulls:
            raise ValueError("Choose a public repository with open issues and pull requests.")
        with urlopen(f"{base_url}/api/pull-requests/{pulls[0]['number']}?{query}", timeout=40) as response:
            detail = json.load(response)
        if detail["pull_request"]["number"] != pulls[0]["number"] or "files" not in detail:
            raise ValueError("Pull request details did not match the selected PR.")
        print(f"Loaded live issues, pull requests, and selected PR details from {repository}.")


def main():
    parser = argparse.ArgumentParser(description="Smoke-test the packaged MaintainerLens demo.")
    parser.add_argument("base_url")
    parser.add_argument("--repository", help="also exercise live GitHub loading for this public repository")
    args = parser.parse_args()
    try:
        verify_demo(args.base_url, args.repository)
    except (KeyError, OSError, ValueError) as exc:
        parser.exit(1, f"Demo smoke test failed: {exc}\n")


if __name__ == "__main__":
    main()
