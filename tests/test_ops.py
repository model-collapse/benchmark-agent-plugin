from clusterbench_ops.splade import (
    SyntheticSpladeEncoder,
    avg_nnz,
    brute_force_topk,
    dot,
    mean_recall,
    recall_at_k,
)


def test_encoder_is_deterministic():
    a = SyntheticSpladeEncoder(seed=1).encode_docs(100)
    b = SyntheticSpladeEncoder(seed=1).encode_docs(100)
    assert a == b
    c = SyntheticSpladeEncoder(seed=2).encode_docs(100)
    assert a != c


def test_corpus_statistics_reasonable():
    docs = SyntheticSpladeEncoder(avg_nnz=50, vocab_size=5000).encode_docs(300)
    assert 30 < avg_nnz(docs) < 70
    assert all(all(w > 0 for w in d.values()) for d in docs)


def test_dot_and_recall_basics():
    assert dot({"1": 2.0, "2": 3.0}, {"2": 4.0}) == 12.0
    assert recall_at_k([1, 2, 3], [1, 2, 3], 3) == 1.0
    assert recall_at_k([9, 8, 7], [1, 2, 3], 3) == 0.0
    assert recall_at_k([1, 9, 9], [1, 2, 3], 3) == 1 / 3


def test_queries_have_signal_against_corpus():
    enc = SyntheticSpladeEncoder(seed=0, vocab_size=4000, avg_nnz=40)
    docs = enc.encode_docs(400)
    queries = enc.encode_queries(50, from_docs=docs)
    exact = [brute_force_topk(q, docs, 10) for q in queries]
    # self-recall against itself is trivially 1.0; this guards the harness wiring
    assert mean_recall(exact, exact, 10) == 1.0
    # queries are derived from docs, so top-1 scores should be strongly positive
    top_scores = [max(dot(q, d) for d in docs) for q in queries[:10]]
    assert all(s > 0 for s in top_scores)
