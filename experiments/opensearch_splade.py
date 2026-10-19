"""Happy path (a): SPLADE / SPLADE-v3 on a local OpenSearch cluster — tune a
hyperparameter to optimize search speed while holding recall@10 within 1pp.

The corpus is ingested into a `rank_features` field across several refresh
cycles (so multiple segments form). Treatment variable:
`forcemerge.max_num_segments`. Searching fewer segments is faster at identical
recall (exact rank_feature scoring), so we sweep the merge target down and pick
the fastest point; the recall floor is held (and trivially met, since merging
does not change results). Each segment target rebuilds its own index.
"""

from __future__ import annotations

from pathlib import Path

from clusterbench_core.discipline.manifest import autofill_from_manifest, load_manifest
from clusterbench_core.model import (
    BenchmarkConfig,
    ControlledVar,
    ResourceBudget,
    RunStatus,
    TreatmentVariable,
)
from clusterbench_core.lifecycle import run_lifecycle
from clusterbench_core.tuning import TuneDim, Tuner
from clusterbench_domains.opensearch import OpenSearchCluster, OpenSearchDomain

_MANIFEST = Path(__file__).parents[1] / "clusterbench_domains" / "opensearch" / "required_params.yaml"


def build_base_config(n_docs=20_000, n_queries=500, vocab=30_000, avg_nnz=50,
                      splade_model="naver/splade-v3", ingest_chunks=16,
                      baseline_segments=16) -> BenchmarkConfig:
    cfg = BenchmarkConfig(
        domain="opensearch",
        hypothesis="Force-merging the SPLADE index to fewer segments speeds up OpenSearch "
                   "search at identical recall@10.",
        treatment_variable=TreatmentVariable(
            name="forcemerge.max_num_segments",
            baseline_value=baseline_segments, value=baseline_segments,
        ),
    )
    cfg.set_param("corpus.n_docs", n_docs, source="default")
    cfg.set_param("corpus.n_queries", n_queries, source="default")
    cfg.set_param("corpus.vocab_size", vocab, source="default")
    cfg.set_param("corpus.avg_nnz", avg_nnz, source="default")
    cfg.set_param("corpus.seed", 0, source="default")
    cfg.set_param("splade.model", splade_model, source="default")
    cfg.set_param("index.number_of_shards", 1, source="inherited")
    cfg.set_param("index.number_of_replicas", 0, source="inherited")
    cfg.set_param("index.refresh_interval", "-1", source="inherited")
    cfg.set_param("index.codec", "default", source="inherited")
    cfg.set_param("index.ingest_chunks", ingest_chunks, source="inherited")
    cfg.set_param("forcemerge.max_num_segments", baseline_segments, source="treatment")
    cfg.set_param("query.prune_terms", 128, source="inherited")  # keep all query terms
    cfg.set_param("query.k", 10, source="inherited")
    autofill_from_manifest(cfg, load_manifest(_MANIFEST))

    cfg.controlled_variables = [
        ControlledVar("index.number_of_shards", 1, verify="GET /<index>/_settings"),
        ControlledVar("index.refresh_interval", "-1", verify="GET /<index>/_settings"),
        ControlledVar("index.codec", "default", verify="GET /<index>/_settings"),
    ]
    cfg.resource_budget = ResourceBudget(total_ram_kb=240 * 1024 * 1024, estimated_peak_kb=16 * 1024 * 1024)
    cfg.reproduction_tolerances = {"recall@10": {"tol": 0.005, "absolute": True},
                                   "ingest_s": 0.30, "forcemerge_s": 0.30}
    return cfg


def run(workdir, cluster, segment_values=(16, 8, 4, 1), recall_tolerance_pp=0.01, **base_kw):
    """Tune forcemerge.max_num_segments over a grid, maximizing search speed
    subject to recall@10 within 1pp of the baseline. Returns (TuningResult, info)."""
    base = build_base_config(**base_kw)
    domain = OpenSearchDomain(cluster)
    baseline_segments = base.treatment_variable.baseline_value

    start_cfg = BenchmarkConfig.from_dict(base.to_dict())
    start_cfg.set_param("forcemerge.max_num_segments", baseline_segments, source="treatment")
    start_cfg.treatment_variable.value = baseline_segments
    lr0 = run_lifecycle(start_cfg, domain, workdir=workdir, baseline=start_cfg)
    baseline_recall = lr0.result.functional_validation["recall@10"]
    floor = round(baseline_recall - recall_tolerance_pp, 4)

    tuner = Tuner(base, domain, workdir, primary_metric="p50_ms", minimize=True,
                  quality_metric="recall@10", quality_floor=floor)
    res = tuner.grid(TuneDim("forcemerge.max_num_segments", values=list(segment_values)))
    return res, {"baseline_recall": baseline_recall, "recall_floor": floor}


if __name__ == "__main__":
    import sys

    wd = sys.argv[1] if len(sys.argv) > 1 else "./clusterbench_data/opensearch"
    cluster = OpenSearchCluster(heap="8g").start()
    try:
        res, info = run(wd, cluster)
        from clusterbench_core.report_index import update_index
        print(res.render())
        print("index:", update_index(wd))
        print(f"\nbaseline recall@10={info['baseline_recall']}  floor={info['recall_floor']}")
        if res.best:
            print(f"RECOMMENDED: max_num_segments={res.best.params['forcemerge.max_num_segments']}  "
                  f"p50={res.best.primary}ms  recall@10={res.best.quality}  "
                  f"improvement={res.improvement:.2f}x vs baseline")
    finally:
        cluster.stop()
