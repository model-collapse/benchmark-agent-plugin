"""SPLADE sparse vectors + exact (brute-force) ground truth for recall.

SPLADE produces sparse term->weight vectors; retrieval scores by sparse dot
product. For a *speed* benchmark the index fidelity is what matters, so by
default we use a deterministic SyntheticSpladeEncoder (realistic vocab/nnz
statistics, no GPU needed). A RealSpladeEncoder (naver/splade-* via
transformers) is available when torch is installed — same interface.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Protocol

SparseVec = dict[str, float]


class SpladeEncoder(Protocol):
    model_name: str

    def encode_docs(self, n: int) -> list[SparseVec]:
        ...

    def encode_queries(self, n: int) -> list[SparseVec]:
        ...


@dataclass
class SyntheticSpladeEncoder:
    """Deterministic SPLADE-like encoder. `model_name` records which SPLADE this
    stands in for (e.g. 'naver/splade-v3'), so configs/reports are honest about
    the represented model."""

    model_name: str = "synthetic-splade"
    vocab_size: int = 5000
    avg_nnz: int = 50
    seed: int = 0
    # queries are drawn as noisy sub-samples of random docs so there is real
    # signal for recall to measure (not uniform noise).
    _docs: list[SparseVec] | None = None

    def _rng(self, salt: int) -> random.Random:
        return random.Random(self.seed * 1_000_003 + salt)

    def encode_docs(self, n: int) -> list[SparseVec]:
        docs: list[SparseVec] = []
        for i in range(n):
            rng = self._rng(i)
            nnz = max(1, int(rng.gauss(self.avg_nnz, self.avg_nnz * 0.25)))
            terms = rng.sample(range(self.vocab_size), min(nnz, self.vocab_size))
            # zipf-ish weights
            docs.append({str(t): round(abs(rng.gauss(1.0, 0.6)) + 0.05, 4) for t in terms})
        self._docs = docs
        return docs

    def encode_queries(self, n: int, from_docs: list[SparseVec] | None = None,
                       keep_frac: float = 0.9, noise_terms: int = 10) -> list[SparseVec]:
        """SPLADE queries are themselves expansions with many weighted terms. We
        retain most of a source doc's terms (so there is real signal) plus
        lower-weight expansion/noise terms, giving long queries where term
        pruning is a meaningful speed/recall knob."""
        docs = from_docs or self._docs
        queries: list[SparseVec] = []
        for i in range(n):
            rng = self._rng(10_000_000 + i)
            q: SparseVec = {}
            if docs:
                base = docs[rng.randrange(len(docs))]
                keep = max(2, int(len(base) * keep_frac))
                for t in rng.sample(list(base), min(keep, len(base))):
                    q[t] = round(base[t] * rng.uniform(0.7, 1.3), 4)
            # low-weight expansion/noise terms (realistic SPLADE tail)
            for _ in range(rng.randint(noise_terms // 2, noise_terms)):
                q.setdefault(str(rng.randrange(self.vocab_size)), round(rng.uniform(0.05, 0.4), 4))
            queries.append(q)
        return queries


def dot(a: SparseVec, b: SparseVec) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


def brute_force_topk(query: SparseVec, docs: list[SparseVec], k: int) -> list[int]:
    scored = ((dot(query, d), i) for i, d in enumerate(docs))
    return [i for _, i in sorted(scored, key=lambda x: (-x[0], x[1]))[:k]]


def recall_at_k(approx_ids: list[int], exact_ids: list[int], k: int) -> float:
    if not exact_ids:
        return 1.0
    gold = set(exact_ids[:k])
    hit = len(gold & set(approx_ids[:k]))
    return hit / min(k, len(gold))


def mean_recall(approx: list[list[int]], exact: list[list[int]], k: int) -> float:
    if not approx:
        return 0.0
    return sum(recall_at_k(a, e, k) for a, e in zip(approx, exact)) / len(approx)


def avg_nnz(docs: list[SparseVec]) -> float:
    return (sum(len(d) for d in docs) / len(docs)) if docs else 0.0


def recall_validation(recall: float, k: int, integrity_passed: bool, **extra) -> dict:
    """SPLADE/IR functional-validation dict with the recall@10 fixed-k rule.
    Lives here (not in the metric-agnostic engine core): k!=10 → recall@10 is
    undefined for the comparison, so the run is marked skipped (passed=None)."""
    base = {"recall@10": round(recall, 4), "k": k, **extra}
    if k != 10:
        return {"passed": None, "reason": "recall@10 requires k==10", **base}
    return {"passed": integrity_passed, **base}
