import os
from hmac import compare_digest

from fastapi import HTTPException, Request


def public_demo_enabled() -> bool:
    return os.getenv("MAINTAINERLENS_PUBLIC_DEMO") == "1"


def demo_generation_configured() -> bool:
    return bool(os.getenv("HF_TOKEN", "").strip() and os.getenv("MAINTAINERLENS_DEMO_ACCESS_KEY", "").strip())


def require_generation_access(request: Request) -> None:
    if not public_demo_enabled():
        return
    if not demo_generation_configured():
        raise HTTPException(status_code=503, detail="AI generation is unavailable in this hosted demo.")
    supplied = request.headers.get("X-MaintainerLens-Access-Key", "")
    expected = os.environ["MAINTAINERLENS_DEMO_ACCESS_KEY"].strip()
    if not compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Enter a valid demo access key to use AI generation.")


def require_local_reviews() -> None:
    if public_demo_enabled():
        raise HTTPException(status_code=404, detail="Review storage is available in the local workspace.")
