"""Happy path (b): SPLADE / SPLADE-v2 on SEISMIC — tune a hyperparameter to
optimize search speed while holding recall@10 within 1 percentage point.

Treatment variable: `seismic.heap_factor` (block-skipping aggressiveness).
Lower heap_factor skips more blocks -> faster search, but can drop recall. We
sweep it downward from the safe baseline and pick the fastest point that still
clears the recall floor. The index is built once and reused across the sweep.
"""

from __future__ import annotations

from pathlib import Path

from clusterbench_core.discipline.manifest import autofill_from_manifest, load_manifest
from clusterbench_core.lifecycle import run_lifecycle
from clusterbench_core.model import (
    BenchmarkConfig,
    ControlledVar,
    ResourceBudget,
    TreatmentVariable,
)
from clusterbench_core.tuning import TuneDim, Tuner
from clusterbench_domains.seismic import SeismicDomain

_MANIFEST = Path(__file__).parents[1] / "clusterbench_domains" / "seismic" / "required_params.yaml"


def build_base_config(n_docs=50_000, n_queries=500, vocab=30_000, avg_nnz=50,
                      splade_model="naver/splade-v2", baseline_heap=0.3) -> BenchmarkConfig:
    cfg = BenchmarkConfig(
        domain="seismic",
        hypothesis="Raising SEISMIC heap_factor (more block-skipping) speeds up search "
                   "while keeping recall@10 within 1pp of the conservative baseline.",
        treatment_variable=TreatmentVariable(
            name="seismic.heap_factor", baseline_value=baseline_heap, value=baseline_heap
        ),
    )
    cfg.set_param("corpus.n_docs", n_docs, source="default")
    cfg.set_param("corpus.n_queries", n_queries, source="default")
    cfg.set_param("corpus.vocab_size", vocab, source="default")
    cfg.set_param("corpus.avg_nnz", avg_nnz, source="default")
    cfg.set_param("corpus.seed", 0, source="default")
    cfg.set_param("splade.model", splade_model, source="default")
    cfg.set_param("seismic.n_postings", 4000, source="inherited")
    cfg.set_param("seismic.centroid_fraction", 0.1, source="inherited")
    cfg.set_param("seismic.summary_energy", 0.5, source="inherited")
    cfg.set_param("seismic.min_cluster_size", 2, source="inherited")
    cfg.set_param("seismic.query_cut", 10, source="inherited")
    cfg.set_param("seismic.heap_factor", baseline_heap, source="treatment")
    cfg.set_param("seismic.k", 10, source="inherited")
    cfg.set_param("seismic.n_knn", 0, source="default")

    # Declare any manifest params not set above (defensive; keeps the gate green).
    autofill_from_manifest(cfg, load_manifest(_MANIFEST))

    cfg.controlled_variables = [
        ControlledVar("corpus.n_docs", n_docs, verify="len(dataset)"),
        ControlledVar("seismic.n_postings", 4000, verify="build_config.n_postings"),
    ]
    # 246 GB box; SEISMIC is in-memory and small here.
    cfg.resource_budget = ResourceBudget(total_ram_kb=240 * 1024 * 1024, estimated_peak_kb=8 * 1024 * 1024)
    return cfg


def run(workdir, recall_tolerance_pp=0.01, points=4, rounds=3, **base_kw):
    """Tune seismic.heap_factor by iterative refinement (coarse grid -> zoom),
    maximizing speed subject to recall@10 within 1pp of the conservative
    baseline. Returns (TuningResult, info)."""
    base = build_base_config(**base_kw)
    domain = SeismicDomain()
    baseline_heap = base.treatment_variable.baseline_value

    # Evaluate the baseline point once to derive the recall floor (builds+caches
    # the index, which every subsequent trial reuses).
    start_cfg = BenchmarkConfig.from_dict(base.to_dict())
    start_cfg.set_param("seismic.heap_factor", baseline_heap, source="treatment")
    start_cfg.treatment_variable.value = baseline_heap
    lr0 = run_lifecycle(start_cfg, domain, workdir=workdir, baseline=start_cfg)
    baseline_recall = lr0.result.functional_validation["recall@10"]
    floor = round(baseline_recall - recall_tolerance_pp, 4)

    tuner = Tuner(base, domain, workdir, primary_metric="p50_ms", minimize=True,
                  quality_metric="recall@10", quality_floor=floor)
    res = tuner.refine(TuneDim("seismic.heap_factor", bounds=(baseline_heap, 1.0)),
                       points=points, rounds=rounds)
    return res, {"baseline_recall": baseline_recall, "recall_floor": floor}


if __name__ == "__main__":
    import sys

    wd = sys.argv[1] if len(sys.argv) > 1 else "./clusterbench_data/seismic"
    res, info = run(wd)
    from clusterbench_core.report_index import update_index
    print(res.render())
    print("index:", update_index(wd))
    print(f"\nbaseline recall@10={info['baseline_recall']}  floor={info['recall_floor']:.4f}")
    if res.best:
        print(f"RECOMMENDED: heap_factor={res.best.params['seismic.heap_factor']}  "
              f"p50={res.best.primary}ms  recall@10={res.best.quality}  "
              f"improvement={res.improvement:.2f}x vs baseline")
