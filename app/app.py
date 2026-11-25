import requests
import gradio as gr

from app.github_client import MAX_ISSUES, fetch_issues
from app.processor import classify_issue, find_similar_issues, summarize_issue


def load_issues(repository: str, issue_limit: int) -> tuple[list[list[object]], str]:
    try:
        issues = fetch_issues(repository, issue_limit)
    except (ValueError, requests.RequestException) as exc:
        raise gr.Error(str(exc)) from exc

    similar_issues = find_similar_issues(issues)
    rows = [
        [
            issue.number,
            classify_issue(issue),
            issue.title,
            summarize_issue(issue.body),
            "; ".join(
                f"#{match.issue.number} {match.issue.title} ({match.score:.0%})"
                for match in similar_issues[issue.number]
            )
            or "No matches above 20% token overlap",
            issue.body,
            ", ".join(issue.labels),
            issue.url,
        ]
        for issue in issues
    ]
    if not issues:
        return rows, "No open issues found for this repository."
    return rows, f"Loaded {len(issues)} open issue(s)."


def create_app() -> gr.Blocks:
    with gr.Blocks(title="MaintainerLens") as demo:
        gr.Markdown(
            "# MaintainerLens\n"
            "Review recent open issues from a public GitHub repository. "
            "Similarity suggestions compare only the issues fetched in this batch."
        )
        with gr.Row():
            repository = gr.Textbox(
                label="GitHub repository",
                placeholder="owner/repo or https://github.com/owner/repo",
            )
            issue_limit = gr.Slider(
                minimum=1,
                maximum=MAX_ISSUES,
                value=10,
                step=1,
                label="Maximum issues",
            )
        fetch_button = gr.Button("Fetch issues", variant="primary")
        status = gr.Markdown()
        issues_table = gr.Dataframe(
            headers=[
                "#",
                "Category",
                "Title",
                "Summary",
                "Potential matches",
                "Body",
                "Labels",
                "URL",
            ],
            datatype=[
                "number",
                "str",
                "str",
                "str",
                "str",
                "str",
                "str",
                "str",
            ],
            interactive=False,
            wrap=True,
            label="Open issues",
        )
        fetch_button.click(
            fn=load_issues,
            inputs=[repository, issue_limit],
            outputs=[issues_table, status],
        )
    return demo


if __name__ == "__main__":
    create_app().launch()
