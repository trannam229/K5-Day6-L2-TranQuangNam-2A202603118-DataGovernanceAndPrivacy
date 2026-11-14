"""T14 Baseline Pipeline — Fixed confidence threshold (conf >= 0.25), no human review.

Owned by: Member 1 (Lead / Integrator) — Phase 2.
Contract command:
    python -m src.main --track t14 --pipeline src.baseline_t14 --output out/baseline --run-name baseline --offline --seed 42

Evaluate against internal GT:
    python -m src.evaluate --track t14 --gt fixtures/t14_auto_annotation/internal_gt_boxes.csv \
        --pred out/baseline/predictions.csv --run-name baseline --out reports/metrics_baseline.json
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.review import make_review_queue, write_review_queue
from .metrics.tracks import get_track
from .pipeline import load

# Mapping from COCO-style model_card_fixture.yaml class_id to project taxonomy.yaml class names
MODEL_TO_TAXONOMY: dict[int, str] = {
    0: "pedestrian",   # person -> pedestrian
    2: "car",          # car -> car
    3: "motorbike",    # motorcycle -> motorbike
    11: "sign",        # stop sign -> sign
}


# ---------------------------------------------------------------- 02 process (Baseline)
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    """Baseline: fixed confidence threshold (default 0.25), raw coordinates (no clipping), no FP filtering."""
    preds = data["predictions"].copy()
    conf_thr = float(ctx.param("conf_threshold", 0.25))

    # Map model class_id to taxonomy class string
    preds["class"] = preds["class_id"].map(lambda cid: MODEL_TO_TAXONOMY.get(int(cid), f"unknown_{cid}"))

    # Fixed threshold across all classes (loses very low-conf small objects, keeps high-conf FPs)
    filtered = preds[preds["conf"] >= conf_thr].copy().reset_index(drop=True)

    # Assign stable item_id and uncertainty score = 1 - conf for ranking
    filtered["item_id"] = [f"base_{i:03d}_{r.image_id}" for i, r in enumerate(filtered.itertuples())]
    filtered["score"] = (1.0 - filtered["conf"]).round(4)
    filtered["reason"] = filtered["conf"].map(lambda c: f"baseline_fixed_thr(conf={c:.3f})")

    ctx.stats["baseline_conf_threshold"] = conf_thr
    ctx.stats["n_baseline_kept"] = len(filtered)
    ctx.stats["n_baseline_dropped"] = len(preds) - len(filtered)

    if ctx.audit is not None:
        ctx.audit.log(
            actor="baseline_t14",
            action="process_fixed_threshold",
            item_id=str(ctx.input_dir),
            after={
                "conf_threshold": conf_thr,
                "n_raw": len(preds),
                "n_kept": len(filtered),
                "n_dropped": len(preds) - len(filtered),
            },
        )

    return filtered


# ---------------------------------------------------------------- 03 rank (Baseline)
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Rank top-B lowest-confidence predictions for inspection (not applied in baseline)."""
    budget = int(ctx.param("budget", 30))
    q = make_review_queue(
        scored,
        id_col="item_id",
        score_col="score",
        budget=budget,
        reason_col="reason",
    )
    write_review_queue(q, ctx.out("review_queue.csv"))
    return q


# ---------------------------------------------------------------- 04 review (Baseline)
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Baseline exports predictions directly without human review overrides."""
    ctx.stats["n_reviewed"] = 0
    if ctx.audit is not None:
        ctx.audit.log(
            actor="baseline_t14",
            action="skip_human_review",
            item_id="review_queue.csv",
            after={"n_queue": len(queue), "n_reviewed": 0},
        )
    return scored


# ---------------------------------------------------------------- 05 decide (Baseline)
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    """Baseline always returns HOLD because boxes are unclipped and unreviewed."""
    return Decision(
        status="HOLD",
        reason_code="BASELINE_NO_HUMAN_QC",
        reason="Baseline uses a single fixed conf_threshold=0.25 without bbox clipping or human review overrides.",
        owner=ctx.config.get("owner", "Trần Quang Nam (Lead / Integrator)"),
        scope=ctx.track,
        evidence=[str(ctx.out("predictions.csv")), str(ctx.out("review_queue.csv"))],
    )


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    cols = spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]
    final[cols].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
