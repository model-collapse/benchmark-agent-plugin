"""OpenSearch SPLADE domain.

SPLADE sparse vectors are stored in a `rank_features` field; a query is a
bool-should of `rank_feature` clauses (one per kept query term, boosted by the
term weight) which sums to the sparse dot product. The index (ingest +
force-merge) is built once per build-signature and reused across a sweep of the
query-time pruning knob; search is always re-run.

This domain exercises real OpenSearch Phase B/C: apply_config creates the index
with the declared settings, verify_config reads them back from the live cluster.
"""

from __future__ import annotations

import hashlib
import resource
import time
from pathlib import Path
from statistics import quantiles

from clusterbench_core.domain import MeasureOutcome, PrepArtifact
from clusterbench_core.discipline.manifest import load_manifest
from clusterbench_core.model import BenchmarkConfig, PhaseMetrics
from clusterbench_ops.splade import SyntheticSpladeEncoder, brute_force_topk, recall_at_k

_MANIFEST = Path(__file__).with_name("required_params.yaml")


def _pct(xs, p):
    if len(xs) < 2:
        return xs[0] if xs else 0.0
    return quantiles(xs, n=100)[min(p, 99) - 1]


class OpenSearchDomain:
    name = "opensearch"

    def __init__(self, cluster):
        self.cluster = cluster
        self.client = cluster.client()
        self._cache: dict[tuple, dict] = {}

    def required_params(self):
        return load_manifest(_MANIFEST)

    # --- prep-persistence hooks (engine cross-session cache) ---
    def build_key(self, cfg: BenchmarkConfig) -> tuple:
        return self._build_key(cfg)

    def prep_descriptor(self, artifact) -> dict:
        e = artifact.handle
        m = e.get("meta", {})
        return {"index": e.get("index"), "n_docs": m.get("n_docs"),
                "segments_after": m.get("segments_after")}

    def save_prep(self, artifact, path) -> None:
        import json
        from pathlib import Path

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        e = artifact.handle
        # The index data lives in the container; persist the pointer + eval data.
        (path / "os_prep.json").write_text(json.dumps({
            "index": e["index"], "queries": e["queries"],
            "ground_truth": e["ground_truth"], "meta": e["meta"],
        }))

    def load_prep(self, path):
        import json
        from pathlib import Path

        d = json.loads((Path(path) / "os_prep.json").read_text())
        entry = {"index": d["index"], "populated": True, "queries": d["queries"],
                 "ground_truth": d["ground_truth"], "meta": d["meta"]}
        # Artifact-descriptor verify: the live index must still exist with the
        # expected doc count — a torn-down/rebuilt container is a StaleArtifact,
        # not a silent reuse.
        from clusterbench_core.engine.cache import StaleArtifact
        expected_docs = int(d["meta"].get("n_docs", 0))
        try:
            live = self.client.count(index=d["index"])["count"]
        except Exception as e:  # noqa: BLE001
            raise StaleArtifact(f"cached OpenSearch index {d['index']} not reachable: {e}")
        if live != expected_docs:
            raise StaleArtifact(
                f"cached OpenSearch index {d['index']} has {live} docs, expected {expected_docs}")
        self._cache[tuple()] = entry
        return PrepArtifact(kind="os-index", handle=entry, meta={"cached": True, **d["meta"]})

    def _build_key(self, cfg: BenchmarkConfig) -> tuple:
        return (
            cfg.get("corpus.n_docs"), cfg.get("corpus.vocab_size", 30000),
            cfg.get("corpus.avg_nnz", 50), cfg.get("corpus.seed", 0),
            cfg.get("corpus.n_queries", 200), cfg.get("splade.model"),
            cfg.get("index.number_of_shards"), cfg.get("index.number_of_replicas"),
            cfg.get("index.refresh_interval"), cfg.get("index.codec"),
            cfg.get("index.ingest_chunks", 1), cfg.get("forcemerge.max_num_segments"),
        )

    def _segment_count(self, index: str) -> int:
        try:
            seg = self.client.indices.segments(index=index)
            shards = seg["indices"][index]["shards"]
            return sum(len(s[0]["segments"]) for s in shards.values())
        except Exception:  # noqa: BLE001
            return -1

    def _index_name(self, cfg: BenchmarkConfig) -> str:
        h = hashlib.sha1(str(self._build_key(cfg)).encode()).hexdigest()[:10]
        return f"cb_splade_{h}"

    # ---- Phase B ----
    def apply_config(self, cfg: BenchmarkConfig, ctx) -> dict:
        key = self._build_key(cfg)
        index = self._index_name(cfg)
        if key in self._cache:
            return {"index": index, "reused": True}
        if self.client.indices.exists(index=index):
            self.client.indices.delete(index=index)
        body = {
            "settings": {
                "index": {
                    "number_of_shards": int(cfg.get("index.number_of_shards")),
                    "number_of_replicas": int(cfg.get("index.number_of_replicas")),
                    "refresh_interval": str(cfg.get("index.refresh_interval")),
                    "codec": str(cfg.get("index.codec")),
                }
            },
            "mappings": {"properties": {"splade": {"type": "rank_features"}}},
        }
        self.client.indices.create(index=index, body=body)
        self._cache[key] = {"index": index, "populated": False}
        return {"index": index, "created": True}

    # ---- Phase C ----
    def verify_config(self, cfg: BenchmarkConfig, ctx):
        index = self._index_name(cfg)
        live = self.client.indices.get_settings(index=index, include_defaults=True)
        s = live[index]["settings"]["index"]
        defaults = live[index].get("defaults", {}).get("index", {})

        def live_val(key, parts):
            node = s
            dnode = defaults
            for p in parts[:-1]:
                node = node.get(p, {}) if isinstance(node, dict) else {}
                dnode = dnode.get(p, {}) if isinstance(dnode, dict) else {}
            return node.get(parts[-1], dnode.get(parts[-1]))

        checks = {
            "index.number_of_shards": ("number_of_shards",),
            "index.number_of_replicas": ("number_of_replicas",),
            "index.refresh_interval": ("refresh_interval",),
            "index.codec": ("codec",),
        }
        rows = {}
        for param, parts in checks.items():
            declared = cfg.get(param)
            observed = live_val(param, parts)
            rows[param] = (declared, observed, str(declared) == str(observed))

        # Wider Phase C: capture undeclared treatment surface (JVM heap, segments).
        # Verified against the config only when declared; otherwise recorded so a
        # silent change between baseline and trials is visible (red-team rank 8).
        rows.update(self._verify_jvm_and_segments(cfg, index))
        return rows

    def _verify_jvm_and_segments(self, cfg: BenchmarkConfig, index: str) -> dict:
        out = {}
        try:
            jvm = self.client.nodes.stats(metric="jvm")["nodes"]
            heap_max = max(n["jvm"]["mem"]["heap_max_in_bytes"] for n in jvm.values())
            declared = cfg.get("jvm.heap_max_bytes")
            out["jvm.heap_max_bytes"] = (declared, heap_max,
                                         declared is None or str(declared) == str(heap_max))
        except Exception:  # noqa: BLE001
            pass
        declared_seg = cfg.get("forcemerge.max_num_segments")
        observed_seg = self._segment_count(index)
        # observed segments should be <= the declared target (force-merge reduces)
        ok = declared_seg is None or observed_seg < 0 or observed_seg <= int(declared_seg)
        out["forcemerge.segments_observed"] = (declared_seg, observed_seg, ok)
        return out

    # ---- prep (cacheable): ingest + force-merge ----
    def prep(self, cfg: BenchmarkConfig, ctx) -> PrepArtifact:
        key = self._build_key(cfg)
        entry = self._cache.setdefault(key, {"index": self._index_name(cfg), "populated": False})
        if entry.get("populated"):
            return PrepArtifact(kind="os-index", handle=entry, meta={"cached": True, **entry["meta"]})

        index = entry["index"]
        enc = SyntheticSpladeEncoder(
            model_name=str(cfg.get("splade.model")),
            vocab_size=int(cfg.get("corpus.vocab_size", 30000)),
            avg_nnz=int(cfg.get("corpus.avg_nnz", 50)),
            seed=int(cfg.get("corpus.seed", 0)),
        )
        n_docs = int(cfg.get("corpus.n_docs"))
        n_queries = int(cfg.get("corpus.n_queries", 200))
        docs = enc.encode_docs(n_docs)
        queries = enc.encode_queries(n_queries, from_docs=docs)

        # bulk ingest
        from opensearchpy import helpers

        # Ingest in `chunks` refresh cycles so multiple segments form; this makes
        # force-merge a meaningful (search-speed) treatment.
        chunks = max(1, int(cfg.get("index.ingest_chunks", 1)))
        per = (len(docs) + chunks - 1) // chunks
        t0 = time.time()
        for c0 in range(0, len(docs), per):
            batch = [{"_index": index, "_id": str(i), "_source": {"splade": docs[i]}}
                     for i in range(c0, min(c0 + per, len(docs)))]
            helpers.bulk(self.client, batch, request_timeout=120)
            self.client.indices.refresh(index=index)
        ingest_s = time.time() - t0
        segs_before = self._segment_count(index)

        # force-merge
        t1 = time.time()
        self.client.indices.forcemerge(
            index=index, max_num_segments=int(cfg.get("forcemerge.max_num_segments")),
            request_timeout=600,
        )
        self.client.indices.refresh(index=index)
        forcemerge_s = time.time() - t1
        segs_after = self._segment_count(index)

        ground_truth = [brute_force_topk(q, docs, 10) for q in queries]
        entry.update({
            "populated": True, "queries": queries, "ground_truth": ground_truth,
            "meta": {"ingest_s": round(ingest_s, 3), "forcemerge_s": round(forcemerge_s, 3),
                     "n_docs": n_docs, "n_queries": n_queries,
                     "segments_before": segs_before, "segments_after": segs_after},
        })
        return PrepArtifact(kind="os-index", handle=entry, meta={"cached": False, **entry["meta"]})

    # ---- measure (always-run): query latency + recall ----
    def measure(self, cfg: BenchmarkConfig, prep: PrepArtifact, ctx) -> MeasureOutcome:
        entry = prep.handle
        index = entry["index"]
        queries = entry["queries"]
        gt = entry["ground_truth"]
        eff = getattr(ctx, "effective", lambda n, v: v)  # point-of-use capture (Gate 1)
        k = eff("query.k", int(cfg.get("query.k", 10)))
        prune = eff("query.prune_terms", int(cfg.get("query.prune_terms")))

        def body_for(q):
            terms = sorted(q.items(), key=lambda kv: -kv[1])[:prune]
            should = [{"rank_feature": {"field": f"splade.{t}", "linear": {}, "boost": float(w)}}
                      for t, w in terms]
            return {"size": k, "query": {"bool": {"should": should}}, "_source": False}

        # Warm-up pass (untimed): fill page/query caches so the first *measured*
        # point is not penalized for cold caches — a fair-comparison fix for the
        # ordering confound that otherwise makes aggressive pruning look slower.
        warm = eff("query.warmup", int(cfg.get("query.warmup", max(10, len(queries) // 5))))
        for q in queries[:warm]:
            self.client.search(index=index, body=body_for(q), request_timeout=60)

        latencies_ms, approx = [], []
        t_all = time.time()
        for q in queries:
            t0 = time.perf_counter()
            res = self.client.search(index=index, body=body_for(q), request_timeout=60)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            approx.append([int(h["_id"]) for h in res["hits"]["hits"]])
        total_s = time.time() - t_all

        recall = sum(recall_at_k(a, g, 10) for a, g in zip(approx, gt)) / max(1, len(gt))
        peak_rss_kb = max(self.cluster.mem_usage_kb(),
                          resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

        latencies_ms.sort()
        metrics = {
            "p50_ms": round(_pct(latencies_ms, 50), 3),
            "p95_ms": round(_pct(latencies_ms, 95), 3),
            "p99_ms": round(_pct(latencies_ms, 99), 3),
            "qps": round(len(queries) / total_s, 1) if total_s else 0.0,
            "search_time_s": round(total_s, 3),
            "ingest_s": entry["meta"]["ingest_s"],
            "forcemerge_s": entry["meta"]["forcemerge_s"],
            "segments_before": entry["meta"]["segments_before"],
            "segments_after": entry["meta"]["segments_after"],
            "peak_rss_kb": peak_rss_kb,
        }
        phases = [
            PhaseMetrics(name="ingest", duration_s=entry["meta"]["ingest_s"], peak_rss_kb=peak_rss_kb),
            PhaseMetrics(name="forcemerge", duration_s=entry["meta"]["forcemerge_s"], peak_rss_kb=peak_rss_kb),
            PhaseMetrics(name="search", duration_s=total_s, peak_rss_kb=peak_rss_kb,
                         extra={"n_queries": len(queries), "prune_terms": prune}),
        ]
        # Data integrity: doc count must match and every query must return hits.
        expected_docs = int(entry["meta"].get("n_docs", 0))
        actual_docs = self.client.count(index=index)["count"]
        hits_ok = all(len(a) > 0 for a in approx)
        passed = (actual_docs == expected_docs) and hits_ok
        from clusterbench_core.discipline.metrics import recall_validation
        return MeasureOutcome(metrics=metrics, phases=phases,
                              functional_validation=recall_validation(
                                  recall, k, passed, doc_count=actual_docs, expected_docs=expected_docs))
