from __future__ import annotations

from collections import OrderedDict
from collections.abc import Collection, Sequence
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from app.github_client import GitHubIssue
from app.processor import MAX_SIMILAR_ISSUES, SimilarityMatch, find_similar_issues

if TYPE_CHECKING:
    import numpy as np
    from fastembed import TextEmbedding

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_SEMANTIC_THRESHOLD = 0.8
DEFAULT_HYBRID_THRESHOLD = 0.85
_MODEL_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "fastembed"


@lru_cache(maxsize=1)
def load_embedding_model() -> TextEmbedding:
    from fastembed import TextEmbedding

    return TextEmbedding(EMBEDDING_MODEL, cache_dir=str(_MODEL_CACHE), threads=2)


class EmbeddingCache:
    def __init__(self, max_entries: int = 2048) -> None:
        if max_entries < 1:
            raise ValueError("The embedding cache must have room for at least one entry.")
        self._max_entries = max_entries
        self._vectors: OrderedDict[bytes, np.ndarray] = OrderedDict()
        self._lock = Lock()

    def embed(self, documents: Sequence[str]) -> list[np.ndarray]:
        keys = [sha256(document.encode("utf-8")).digest() for document in documents]
        with self._lock:
            missing = {
                key: document
                for key, document in zip(keys, documents, strict=True)
                if key not in self._vectors
            }
            if missing:
                vectors = {
                    key: vector.copy()
                    for key, vector in zip(
                        missing, load_embedding_model().embed(list(missing.values())), strict=True
                    )
                }
                self._vectors.update(vectors)
            result = [self._vectors[key] for key in keys]
            for key in keys:
                self._vectors.move_to_end(key)
            while len(self._vectors) > self._max_entries:
                self._vectors.popitem(last=False)
            return result


def find_semantic_issues(
    issues: Sequence[GitHubIssue], *, threshold: float = DEFAULT_SEMANTIC_THRESHOLD
) -> dict[int, list[SimilarityMatch]]:
    return _rank_semantic_matches(issues, range(len(issues)), threshold=threshold)


def find_hybrid_issues(
    issues: Sequence[GitHubIssue],
    *,
    cache: EmbeddingCache,
    threshold: float = DEFAULT_HYBRID_THRESHOLD,
) -> dict[int, list[SimilarityMatch]]:
    matches = find_similar_issues(issues)
    matches.update(find_semantic_fallbacks(
        issues,
        issue_numbers={number for number, candidates in matches.items() if not candidates},
        threshold=threshold,
        cache=cache,
    ))
    return matches


def find_semantic_fallbacks(
    issues: Sequence[GitHubIssue],
    *,
    issue_numbers: Collection[int],
    cache: EmbeddingCache,
    threshold: float = DEFAULT_HYBRID_THRESHOLD,
) -> dict[int, list[SimilarityMatch]]:
    queries = [
        position for position, issue in enumerate(issues) if issue.number in issue_numbers
    ]
    return _rank_semantic_matches(issues, queries, threshold=threshold, cache=cache)


def _rank_semantic_matches(
    issues: Sequence[GitHubIssue],
    queries: Sequence[int],
    *,
    threshold: float,
    cache: EmbeddingCache | None = None,
) -> dict[int, list[SimilarityMatch]]:
    if not 0 <= threshold <= 1:
        raise ValueError("Semantic similarity threshold must be between 0 and 1.")
    if len(issues) < 2 or not queries:
        return {issues[position].number: [] for position in queries}

    import faiss
    import numpy as np

    documents = [f"{issue.title}\n\n{issue.body}" for issue in issues]
    embed = cache.embed if cache is not None else load_embedding_model().embed
    vectors = np.array(list(embed(documents)), dtype=np.float32)
    faiss.normalize_L2(vectors)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    # These small candidate pools can be ranked in full for stable tie-breaking.
    scores, positions = index.search(vectors[list(queries)], len(issues))

    matches = {}
    for row, query in enumerate(queries):
        candidates = [
            SimilarityMatch(issues[position], min(float(score), 1.0))
            for score, position in zip(scores[row], positions[row])
            if position != query and score >= threshold
        ]
        candidates.sort(key=lambda match: (-match.score, match.issue.number))
        matches[issues[query].number] = candidates[:MAX_SIMILAR_ISSUES]
    return matches
