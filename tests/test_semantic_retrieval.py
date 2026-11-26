import unittest
from importlib.util import find_spec
from unittest.mock import patch

from app.github_client import GitHubIssue
from app.processor import SimilarityMatch
from app.semantic_retrieval import EmbeddingCache, find_hybrid_issues, find_semantic_issues


class SemanticRetrievalTests(unittest.TestCase):
    @patch("app.semantic_retrieval.load_embedding_model")
    def test_reembeds_only_changed_text(self, load_model):
        embed = load_model.return_value.embed
        embed.side_effect = [[[1.0], [2.0]], [[3.0]]]
        cache = EmbeddingCache()

        self.assertEqual(cache.embed(["Issue one", "Issue two"]), [[1.0], [2.0]])
        self.assertEqual(cache.embed(["Issue two", "Issue one edited"]), [[2.0], [3.0]])
        self.assertEqual(cache.embed(["Issue one edited", "Issue one"]), [[3.0], [1.0]])
        self.assertEqual(embed.call_count, 2)
        embed.assert_called_with(["Issue one edited"])

    @unittest.skipUnless(find_spec("faiss"), "Install requirements-semantic.txt")
    @patch("app.semantic_retrieval.find_similar_issues")
    @patch("app.semantic_retrieval.load_embedding_model")
    def test_hybrid_only_fills_empty_results_and_reuses_vectors(self, load_model, find_text):
        first, second, third = [
            GitHubIssue(number, f"Title {number}", "Description", (), "")
            for number in (1, 2, 3)
        ]
        find_text.side_effect = lambda _: {1: [SimilarityMatch(third, 0.65)], 2: [], 3: []}
        load_model.return_value.embed.return_value = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        cache = EmbeddingCache()

        for _ in range(2):
            matches = find_hybrid_issues([first, second, third], cache=cache)
            self.assertEqual(matches[1], [SimilarityMatch(third, 0.65)])
            self.assertEqual(matches[2], [SimilarityMatch(first, 1.0)])
            self.assertEqual(matches[3], [])
        load_model.return_value.embed.assert_called_once()

    @unittest.skipUnless(find_spec("faiss"), "Install requirements-semantic.txt")
    @patch("app.semantic_retrieval.load_embedding_model")
    def test_ranks_by_cosine_and_filters_self_and_unrelated_issues(self, load_model):
        load_model.return_value.embed.return_value = [
            [2.0, 0.0],
            [10.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
        ]
        issues = [
            GitHubIssue(number, f"Title {number}", "Description", (), "")
            for number in (1, 2, 3, 4)
        ]

        matches = find_semantic_issues(issues, threshold=0.7)

        self.assertEqual([match.issue.number for match in matches[1]], [2, 3])
        self.assertAlmostEqual(matches[1][0].score, 1.0)
        self.assertEqual([match.issue.number for match in matches[4]], [3])
        load_model.return_value.embed.assert_called_once_with([
            f"Title {issue.number}\n\nDescription" for issue in issues
        ])
