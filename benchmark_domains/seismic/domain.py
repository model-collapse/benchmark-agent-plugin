"""SEISMIC domain: build a SEISMIC sparse index from SPLADE vectors and measure
search latency + recall@10 vs an exact brute-force baseline.

The index build (deterministic, expensive) is cached by its build-parameter
signature, so a sweep over a *search* parameter (query_cut, heap_factor) reuses
one index — the concrete realization of ClusterBench's cache-vs-reproduction
split. Search is always re-run.
"""

from __future__ import annotations

import resource
import time
from pathlib import Path
from statistics import quantiles

from benchmark_engine.domain import MeasureOutcome, PrepArtifact
from benchmark_engine.discipline.manifest import load_manifest
from benchmark_engine.model import BenchmarkConfig
from benchmark_ops.splade import SyntheticSpladeEncoder, brute_force_topk, recall_at_k

_MANIFEST = Path(__file__).with_name("required_params.yaml")


def _pct(latencies_ms, p):
    if len(latencies_ms) < 2:
        return latencies_ms[0] if latencies_ms else 0.0
    # quantiles(n=100) gives 99 cut points; index p-1 is the p-th percentile
    qs = quantiles(latencies_ms, n=100)
    return qs[min(p, 99) - 1]


class SeismicDomain:
    name = "seismic"
    measure_import = "benchmark_domains.seismic:SeismicDomain"  # no-arg → subprocess-measurable

    def __init__(self):
        self._build_cache: dict[tuple, dict] = {}

    def required_params(self):
        return load_manifest(_MANIFEST)

    # library domain: nothing live to mutate / verify before build
    def apply_config(self, cfg: BenchmarkConfig, ctx) -> dict:
        return {"note": "seismic is a library domain; build params applied at index build time"}

    def verify_config(self, cfg: BenchmarkConfig, ctx):
        return {}

    # --- prep-persistence hooks (engine cross-session cache) ---
    def build_key(self, cfg: BenchmarkConfig) -> tuple:
        return self._build_key(cfg)

    def prep_descriptor(self, artifact) -> dict:
        m = artifact.meta
        return {"index_len": m.get("index_len"), "index_nnz": m.get("index_nnz")}

    def save_prep(self, artifact, path) -> None:
        import json
        from pathlib import Path

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        e = artifact.handle
        e["index"].save(str(path / "idx"))  # writes idx.index.seismic
        (path / "aux.json").write_text(json.dumps({
            "queries": e["queries"], "ground_truth": e["ground_truth"],
            "seismic_string": e["seismic_string"], "meta": e["meta"],
        }))

    def load_prep(self, path):
        import json
        from pathlib import Path

        import seismic

        path = Path(path)
        idx = seismic.SeismicIndex.load(str(path / "idx.index.seismic"))
        aux = json.loads((path / "aux.json").read_text())
        entry = {"index": idx, "queries": aux["queries"], "ground_truth": aux["ground_truth"],
                 "seismic_string": aux["seismic_string"], "meta": aux["meta"]}
        return PrepArtifact(kind="seismic-index", handle=entry, meta={"cached": True, **aux["meta"]})

    def _build_key(self, cfg: BenchmarkConfig) -> tuple:
        return (
            cfg.get("corpus.n_docs"), cfg.get("corpus.vocab_size"),
            cfg.get("corpus.avg_nnz"), cfg.get("corpus.seed", 0),
            cfg.get("corpus.n_queries", 200), cfg.get("splade.model"),
            cfg.get("seismic.n_postings"), cfg.get("seismic.centroid_fraction"),
            cfg.get("seismic.summary_energy"), cfg.get("seismic.min_cluster_size"),
        )

    def prep(self, cfg: BenchmarkConfig, ctx) -> PrepArtifact:
        import numpy as np
        import seismic

        key = self._build_key(cfg)
        if key in self._build_cache:
            e = self._build_cache[key]
            return PrepArtifact(kind="seismic-index", handle=e, meta={"cached": True, **e["meta"]})

        S = seismic.get_seismic_string()  # 'U30'
        enc = SyntheticSpladeEncoder(
            model_name=str(cfg.get("splade.model")),
            vocab_size=int(cfg.get("corpus.vocab_size")),
            avg_nnz=int(cfg.get("corpus.avg_nnz")),
            seed=int(cfg.get("corpus.seed", 0)),
        )
        n_docs = int(cfg.get("corpus.n_docs"))
        n_queries = int(cfg.get("corpus.n_queries", 200))
        docs = enc.encode_docs(n_docs)
        queries = enc.encode_queries(n_queries, from_docs=docs)

        dset = seismic.SeismicDataset()
        for i, d in enumerate(docs):
            toks = np.array(list(d.keys()), dtype=S)
            vals = np.array(list(d.values()), dtype=np.float32)
            dset.add_document(str(i), toks, vals)

        t0 = time.time()
        idx = seismic.SeismicIndex.build_from_dataset(
            dset,
            n_postings=int(cfg.get("seismic.n_postings")),
            centroid_fraction=float(cfg.get("seismic.centroid_fraction")),
            min_cluster_size=int(cfg.get("seismic.min_cluster_size")),
            summary_energy=float(cfg.get("seismic.summary_energy")),
        )
        build_time = time.time() - t0

        # exact ground truth for recall@10 (depends only on corpus; cached with build)
        ground_truth = [brute_force_topk(q, docs, 10) for q in queries]

        entry = {
            "index": idx,
            "queries": queries,
            "ground_truth": ground_truth,
            "seismic_string": S,
            "meta": {
                "build_time_s": round(build_time, 4),
                "index_len": idx.len,
                "index_nnz": idx.nnz,
                "index_dim": idx.dim,
                "n_queries": n_queries,
            },
        }
        self._build_cache[key] = entry
        return PrepArtifact(kind="seismic-index", handle=entry, meta={"cached": False, **entry["meta"]})

    def measure(self, cfg: BenchmarkConfig, prep: PrepArtifact, ctx) -> MeasureOutcome:
        import numpy as np

        e = prep.handle
        idx = e["index"]
        queries = e["queries"]
        gt = e["ground_truth"]
        S = e["seismic_string"]

        eff = getattr(ctx, "effective", lambda n, v: v)  # point-of-use capture (Gate 1)
        k = eff("seismic.k", int(cfg.get("seismic.k", 10)))
        query_cut = eff("seismic.query_cut", int(cfg.get("seismic.query_cut")))
        heap_factor = eff("seismic.heap_factor", float(cfg.get("seismic.heap_factor")))
        n_knn = eff("seismic.n_knn", int(cfg.get("seismic.n_knn", 0)))

        def comps_vals(q):
            return (np.array(list(q.keys()), dtype=S), np.array(list(q.values()), dtype=np.float32))

        # Warm-up (untimed) for fair cross-point comparison. warmup is a controlled
        # identity param (captured at point of use) so clamping it trips Gate 1.
        warm = eff("seismic.warmup", int(cfg.get("seismic.warmup", max(5, len(queries) // 10))))
        for qi, q in enumerate(queries[:warm]):
            c, v = comps_vals(q)
            idx.search(str(qi), c, v, k, query_cut, heap_factor, n_knn)

        latencies_ms: list[float] = []
        approx_ids: list[list[int]] = []
        t_all = time.time()
        for qi, q in enumerate(queries):
            comps = np.array(list(q.keys()), dtype=S)
            vals = np.array(list(q.values()), dtype=np.float32)
            t0 = time.perf_counter()
            res = idx.search(str(qi), comps, vals, k, query_cut, heap_factor, n_knn)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            approx_ids.append([int(doc_id) for (_qid, _score, doc_id) in res])
        total_s = time.time() - t_all

        recall = sum(recall_at_k(a, g, 10) for a, g in zip(approx_ids, gt)) / max(1, len(gt))
        peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KB on Linux

        latencies_ms.sort()
        metrics = {
            "p50_ms": round(_pct(latencies_ms, 50), 4),
            "p95_ms": round(_pct(latencies_ms, 95), 4),
            "p99_ms": round(_pct(latencies_ms, 99), 4),
            "qps": round(len(queries) / total_s, 1) if total_s else 0.0,
            "search_time_s": round(total_s, 4),
            "build_time_s": e["meta"]["build_time_s"],
            "peak_rss_kb": peak_rss_kb,
            "index_nnz": e["meta"]["index_nnz"],
        }
        from benchmark_engine.model import PhaseMetrics

        phases = [
            PhaseMetrics(name="build", duration_s=e["meta"]["build_time_s"], peak_rss_kb=peak_rss_kb),
            PhaseMetrics(name="search", duration_s=total_s, peak_rss_kb=peak_rss_kb,
                         extra={"n_queries": len(queries)}),
        ]
        # Data integrity: the index must hold exactly the expected docs and every
        # query must return results — else the comparison is on broken data.
        expected_docs = int(cfg.get("corpus.n_docs"))
        actual_docs = idx.len
        hits_ok = all(len(a) > 0 for a in approx_ids)
        passed = (actual_docs == expected_docs) and hits_ok
        from benchmark_ops.splade import recall_validation
        return MeasureOutcome(
            metrics=metrics,
            phases=phases,
            functional_validation=recall_validation(
                recall, k, passed, doc_count=actual_docs, expected_docs=expected_docs),
        )
