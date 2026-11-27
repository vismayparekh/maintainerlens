import requests
import gradio as gr
from html import escape

from app.github_client import (
    GitHubIssue,
    MAX_HISTORICAL_ISSUES,
    MAX_ISSUES,
    fetch_closed_issues,
    fetch_issues,
)
from app.llm_client import (
    IssueAnalysisError,
    IssueAnalysisNotConfiguredError,
    analyze_issue,
)
from app.processor import (
    ISSUE_CATEGORIES,
    classify_issue,
    find_similar_issues,
    summarize_issue,
)
from app.review_store import ReviewStoreError, export_reviews_csv, save_review
from app.security_guidance import security_guidance


_APP_CSS = """
.gradio-container { max-width: 100% !important; }
.issue-details-section { max-width: 1100px; }
.selected-issue-title {
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--background-fill-primary, white);
    border-bottom: 1px solid var(--border-color-primary, #ddd);
    padding: 0.25rem 0;
}
"""


def _escape_markdown_link_text(text: str) -> str:
    escaped = " ".join(text.split()).replace("\\", "\\\\")
    for character in ("`", "*", "_", "[", "]", "~"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _issue_table() -> gr.Dataset:
    return gr.Dataset(
        components=[
            gr.Number(render=False),
            gr.Textbox(render=False),
            gr.Textbox(render=False),
        ],
        samples=[],
        headers=["#", "Category", "Issue"],
        type="index",
        layout="table",
        samples_per_page=MAX_ISSUES,
        label="Select an issue",
    )


def load_issues(
    repository: str,
    issue_limit: int,
) -> tuple[
    dict[str, object],
    str,
    list[tuple[str, str, GitHubIssue]],
    str,
    str,
    GitHubIssue | None,
    str,
    dict[str, object],
    str,
    str | None,
    dict[str, str] | None,
    dict[str, object],
    str,
]:
    try:
        issues = fetch_issues(repository, issue_limit)
        if not issues:
            return (
                gr.update(samples=[]),
                "No open issues found for this repository.",
                [],
                "",
                "No open issues found for this repository.",
                None,
                "Fetch issues to begin AI-assisted review.",
                gr.update(interactive=False),
                "",
                None,
                None,
                gr.update(interactive=False),
                "",
            )
        closed_issues = fetch_closed_issues(repository)
    except (ValueError, requests.RequestException) as exc:
        raise gr.Error(str(exc)) from exc

    candidate_issues = list(issues)
    seen_numbers = {issue.number for issue in issues}
    closed_numbers = {issue.number for issue in closed_issues}
    for issue in closed_issues:
        if issue.number not in seen_numbers:
            candidate_issues.append(issue)
            seen_numbers.add(issue.number)

    similar_issues = find_similar_issues(candidate_issues)
    closed_numbers.difference_update(issue.number for issue in issues)
    rows = [
        [
            issue.number,
            classify_issue(issue),
            issue.title,
        ]
        for issue in issues
    ]
    issue_details: list[tuple[str, str]] = []
    for issue in issues:
        matches = similar_issues[issue.number]
        issue_heading = (
            f"### [#{issue.number} {_escape_markdown_link_text(issue.title)}]"
            f"({issue.url})"
        )
        details = [
            f"**Rule-based category:** {classify_issue(issue)} | **Status:** Open",
            f"**Labels:** {', '.join(issue.labels) or 'None'}",
            "",
            "#### Full description",
            issue.body.strip() or "_No description provided._",
            "",
            "#### Ranked similar issues",
            "_Scores are text similarity, not confidence._",
        ]
        if not matches:
            details.append("No suggestions passed the similarity filters.")
        else:
            for rank, match in enumerate(matches, start=1):
                match_title = _escape_markdown_link_text(match.issue.title)
                state = (
                    "Closed history"
                    if match.issue.number in closed_numbers
                    else "Open"
                )
                details.append(
                    f"{rank}. [#{match.issue.number} {match_title}]({match.issue.url}) "
                    f"- {match.score:.0%} text similarity ({state})"
                )
        issue_details.append((issue_heading, "\n\n".join(details), issue))

    return (
        gr.update(samples=rows),
        (
            f"Loaded {len(issues)} open issue(s); compared against "
            f"{len(candidate_issues) - len(issues)} historical issue(s)."
        ),
        issue_details,
        issue_details[0][0],
        issue_details[0][1],
        issue_details[0][2],
        "Click **Generate AI summary + category** to analyze the selected issue. "
        "The issue title and body are sent to Hugging Face only when you click.",
        gr.update(interactive=True),
        "",
        None,
        None,
        gr.update(interactive=False),
        "",
    )


def render_selected_issue(
    issue_details: list[tuple[str, str, GitHubIssue]],
    event: gr.SelectData,
) -> tuple[
    str,
    str,
    GitHubIssue | None,
    str,
    dict[str, object],
    str,
    str | None,
    dict[str, str] | None,
    dict[str, object],
    str,
]:
    empty_selection = (
        "",
        "Select an issue from the list to see its details.",
        None,
        "Select an issue before requesting AI analysis.",
        gr.update(interactive=False),
        "",
        None,
        None,
        gr.update(interactive=False),
        "",
    )
    row_index = event.index
    if isinstance(row_index, (tuple, list)):
        row_index = row_index[0] if row_index else None
    if not event.selected or not isinstance(row_index, int):
        return empty_selection
    if not 0 <= row_index < len(issue_details):
        return empty_selection
    title, details, issue = issue_details[row_index]
    return (
        title,
        details,
        issue,
        "Click **Generate AI summary + category** to analyze the selected issue. "
        "The issue title and body are sent to Hugging Face only when you click.",
        gr.update(interactive=True),
        "",
        None,
        None,
        gr.update(interactive=False),
        "",
    )


def generate_ai_analysis(
    issue: GitHubIssue | None,
) -> tuple[str, str, str | None, dict[str, str] | None, dict[str, object], str]:
    if issue is None:
        return (
            "Select an issue before requesting AI analysis.",
            "",
            None,
            None,
            gr.update(interactive=False),
            "",
        )

    guidance = security_guidance(issue)
    if guidance:
        return (guidance.reply, "", None, None, gr.update(interactive=False), "")
    try:
        analysis = analyze_issue(issue.title, issue.body)
    except IssueAnalysisNotConfiguredError as exc:
        return (
            f"**AI analysis is not configured.** {escape(str(exc))}\n\n"
            f"**Rule-based summary:** {escape(summarize_issue(issue.body))}",
            "",
            None,
            None,
            gr.update(interactive=False),
            "",
        )
    except IssueAnalysisError as exc:
        return (
            f"**AI analysis failed.** {escape(str(exc))}\n\n"
            f"**Rule-based summary:** {escape(summarize_issue(issue.body))}",
            "",
            None,
            None,
            gr.update(interactive=False),
            "",
        )

    return (
        "### AI-generated summary\n\n"
        f"{escape(analysis.summary)}\n\n"
        f"**AI-suggested category:** {analysis.category}\n\n"
        f"**Why:** {escape(analysis.rationale)}",
        analysis.summary,
        analysis.category,
        {"summary": analysis.summary, "category": analysis.category},
        gr.update(interactive=True),
        "",
    )


def save_issue_review(
    issue: GitHubIssue | None,
    ai_suggestion: dict[str, str] | None,
    reviewed_summary: str | None,
    reviewed_category: str | None,
) -> str:
    if issue is None or ai_suggestion is None:
        raise gr.Error("Generate an AI analysis before saving a review.")
    if not reviewed_summary or not reviewed_summary.strip():
        raise gr.Error("The reviewed summary must not be empty.")
    if reviewed_category not in ISSUE_CATEGORIES:
        raise gr.Error("Select a valid reviewed category.")

    ai_summary = ai_suggestion.get("summary", "")
    ai_category = ai_suggestion.get("category", "")
    if not ai_summary.strip() or ai_category not in ISSUE_CATEGORIES:
        raise gr.Error("The original AI suggestion is incomplete.")

    try:
        save_review(
            issue,
            ai_summary,
            ai_category,
            reviewed_summary.strip(),
            reviewed_category,
        )
    except ReviewStoreError as exc:
        raise gr.Error(str(exc)) from exc

    return (
        f"Saved review for issue #{issue.number} locally. "
        "Saving again updates this issue's latest review."
    )


def download_local_reviews() -> str:
    try:
        return str(export_reviews_csv())
    except ReviewStoreError as exc:
        raise gr.Error(str(exc)) from exc


def create_app() -> gr.Blocks:
    with gr.Blocks(
        title="MaintainerLens",
        fill_height=True,
        fill_width=True,
    ) as demo:
        gr.Markdown(
            "# MaintainerLens\n"
            "Review recent open issues from a public GitHub repository. "
            f"Similarity suggestions compare this batch against up to "
            f"{MAX_HISTORICAL_ISSUES} recently updated closed issues. "
            "Select an issue to see its full details below the list."
        )
        with gr.Row():
            repository = gr.Textbox(
                label="GitHub repository",
                placeholder="owner/repo or https://github.com/owner/repo",
                scale=4,
            )
            issue_limit = gr.Slider(
                minimum=1,
                maximum=MAX_ISSUES,
                value=10,
                step=1,
                label="Issues",
                scale=1,
            )
            fetch_button = gr.Button(
                "Fetch issues",
                variant="primary",
                scale=1,
                min_width=120,
            )
        status = gr.Markdown()
        issue_details_state = gr.State([])
        selected_issue_state = gr.State(None)
        ai_suggestion_state = gr.State(None)
        gr.Markdown("### Open issues\nClick any row to view its details below.")
        issues_table = _issue_table()
        with gr.Column(elem_classes="issue-details-section"):
            gr.Markdown("### Selected issue")
            selected_issue_title = gr.Markdown(
                "Select an issue from the list.",
                elem_classes="selected-issue-title",
            )
            ai_analysis = gr.Markdown(
                "Select an issue, then generate an AI summary and category suggestion."
            )
            gr.Markdown(
                "AI analysis sends the selected issue's title and description to "
                "Hugging Face Inference Providers. Use this only for content you "
                "are comfortable sharing; "
                "API usage may incur charges."
            )
            analyze_button = gr.Button(
                "Generate AI summary + category",
                interactive=False,
            )
            with gr.Accordion("Review and save locally", open=False):
                gr.Markdown(
                    "Edit the AI suggestion, then save your reviewed summary and "
                    "category on this machine. The issue description is not saved."
                )
                review_summary = gr.Textbox(
                    label="Reviewed summary",
                    lines=4,
                )
                review_category = gr.Dropdown(
                    choices=ISSUE_CATEGORIES,
                    label="Reviewed category",
                )
                save_review_button = gr.Button(
                    "Save review locally",
                    interactive=False,
                )
                review_status = gr.Markdown()
                download_reviews_button = gr.DownloadButton(
                    "Download saved reviews as CSV"
                )
            issue_details = gr.Markdown(
                "The description and suggestions will appear here.",
            )
        fetch_button.click(
            fn=load_issues,
            inputs=[repository, issue_limit],
            outputs=[
                issues_table,
                status,
                issue_details_state,
                selected_issue_title,
                issue_details,
                selected_issue_state,
                ai_analysis,
                analyze_button,
                review_summary,
                review_category,
                ai_suggestion_state,
                save_review_button,
                review_status,
            ],
        )
        issues_table.select(
            fn=render_selected_issue,
            inputs=[issue_details_state],
            outputs=[
                selected_issue_title,
                issue_details,
                selected_issue_state,
                ai_analysis,
                analyze_button,
                review_summary,
                review_category,
                ai_suggestion_state,
                save_review_button,
                review_status,
            ],
            queue=False,
            scroll_to_output=True,
        )
        analyze_button.click(
            fn=generate_ai_analysis,
            inputs=[selected_issue_state],
            outputs=[
                ai_analysis,
                review_summary,
                review_category,
                ai_suggestion_state,
                save_review_button,
                review_status,
            ],
        )
        save_review_button.click(
            fn=save_issue_review,
            inputs=[
                selected_issue_state,
                ai_suggestion_state,
                review_summary,
                review_category,
            ],
            outputs=[review_status],
        )
        download_reviews_button.click(
            fn=download_local_reviews,
            outputs=[download_reviews_button],
        )
    return demo


if __name__ == "__main__":
    create_app().launch(css=_APP_CSS)
