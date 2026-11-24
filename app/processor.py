import re

MAX_SUMMARY_LENGTH = 240


def summarize_issue(body: str) -> str:
    if not isinstance(body, str):
        raise TypeError("Issue body must be text.")

    text = re.sub(r"\s+", " ", body).strip()
    if not text:
        return "No description provided."

    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentences[:2])
    if len(summary) <= MAX_SUMMARY_LENGTH:
        return summary

    shortened = summary[: MAX_SUMMARY_LENGTH - 3]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened.rstrip(" ,;:-") + "..."