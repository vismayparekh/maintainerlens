import os
from datetime import date, datetime, time, timedelta, timezone
from hmac import compare_digest
from threading import Lock

from fastapi import HTTPException, Request


PUBLIC_GENERATION_DAILY_LIMIT = 10


class _DailyGenerationQuota:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._lock = Lock()
        self._day: date | None = None
        self._used = 0

    def take(self, now: datetime) -> None:
        with self._lock:
            today = now.date()
            if today != self._day:
                self._day = today
                self._used = 0
            if self._used >= self.limit:
                tomorrow = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)
                raise HTTPException(
                    status_code=429,
                    detail="The public AI demo has reached its shared daily limit. Please try again tomorrow.",
                    headers={"Retry-After": str(max(1, int((tomorrow - now).total_seconds())))},
                )
            self._used += 1


_public_generation_quota = _DailyGenerationQuota(PUBLIC_GENERATION_DAILY_LIMIT)


def public_demo_enabled() -> bool:
    return os.getenv("MAINTAINERLENS_PUBLIC_DEMO") == "1"


def public_generation_enabled() -> bool:
    return public_demo_enabled() and os.getenv("MAINTAINERLENS_PUBLIC_GENERATION") == "1"


def demo_generation_configured() -> bool:
    return bool(
        os.getenv("HF_TOKEN", "").strip()
        and (public_generation_enabled() or os.getenv("MAINTAINERLENS_DEMO_ACCESS_KEY", "").strip())
    )


def require_generation_access(request: Request) -> None:
    if not public_demo_enabled():
        return
    if not demo_generation_configured():
        raise HTTPException(status_code=503, detail="AI generation is unavailable in this hosted demo.")
    if public_generation_enabled():
        return
    supplied = request.headers.get("X-MaintainerLens-Access-Key", "")
    expected = os.environ["MAINTAINERLENS_DEMO_ACCESS_KEY"].strip()
    if not compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Enter a valid demo access key to use AI generation.")


def reserve_generation() -> None:
    if public_generation_enabled():
        _public_generation_quota.take(datetime.now(timezone.utc))


def require_local_reviews() -> None:
    if public_demo_enabled():
        raise HTTPException(status_code=404, detail="Review storage is available in the local workspace.")
