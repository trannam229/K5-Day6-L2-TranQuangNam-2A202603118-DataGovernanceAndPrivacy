"""T14 human-in-the-loop review + decision gate (owner: Member 3).

Called from src/pipeline.py:
    review(ctx, scored, queue) : apply out/<run>/review_queue_reviewed.csv onto the candidate table
    decide(ctx, final)         : GO / HOLD / REWORK

Reviewed file = review_queue.csv with the reviewer columns filled (Tab 2 of index.html exports it).
    approve  -> keep the box (restores a box that was below the confidence threshold)
    reject   -> drop the box
    edit     -> keep the box and apply `override_value`, e.g. "class=motorbike" or "x=10; y=20; w=30; h=40"
    escalate / skip -> no change, the item still counts as NOT reviewed
Every applied decision is appended to the audit log (reviewer, before, after, note).
"""
from __future__ import annotations

import pandas as pd

from .common.decision import Decision
from .common.review import load_review_decisions
from .t14_processor import invalid_mask, load_taxonomy

REVIEWED_FILE = "review_queue_reviewed.csv"
EDITABLE = {"class": str, "x": float, "y": float, "w": float, "h": float}
FINAL_DECISIONS = {"approve", "reject", "edit"}


def parse_override(value: str, taxonomy_names: set[str]) -> dict:
    """'class=motorbike; x=10' -> {'class': 'motorbike', 'x': 10.0}. Fails loudly on anything else."""
    out = {}
    for part in str(value).replace(",", ";").split(";"):
        if not part.strip():
            continue
        key, sep, val = part.partition("=")
        key, val = key.strip().lower(), val.strip()
        if not sep or key not in EDITABLE:
            raise ValueError(f"bad override {value!r}: use key=value with keys {sorted(EDITABLE)}")
        out[key] = EDITABLE[key](val)
    if "class" in out and out["class"] not in taxonomy_names:
        raise ValueError(f"bad override {value!r}: class must be one of {sorted(taxonomy_names)}")
    return out


def review(ctx, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Return the candidate table with reviewer decisions applied (`keep`, class, box)."""
    out = scored.copy()
    queue_ids = set(queue["item_id"])
    ctx.stats.update({"t14_queue_size": len(queue_ids), "t14_queue_reviewed": 0, "n_reviewed": 0})
    path = ctx.output_dir / REVIEWED_FILE
    if not path.exists():
        return out

    taxonomy_names = set(load_taxonomy(ctx.input_dir / "taxonomy.yaml").values())
    decisions = load_review_decisions(path)          # validates decision values + reviewer is filled
    done, counts, unknown = set(), {}, []
    for r in decisions.itertuples():
        mask = out["box_id"] == r.item_id
        if not mask.any():                           # reviewed file comes from another (stale) queue
            unknown.append(r.item_id)
            continue
        if r.reviewer_decision not in FINAL_DECISIONS:
            continue
        fields = ["class", "x", "y", "w", "h", "keep"]
        before = out.loc[mask, fields].iloc[0].to_dict()
        if r.reviewer_decision == "edit":
            changes = parse_override(r.override_value, taxonomy_names)
            if not changes:
                raise ValueError(f"{r.item_id}: decision 'edit' needs an override_value, e.g. class=motorbike")
            for col, val in changes.items():
                out.loc[mask, col] = val
        out.loc[mask, "keep"] = r.reviewer_decision != "reject"
        counts[r.reviewer_decision] = counts.get(r.reviewer_decision, 0) + 1
        done.add(r.item_id)
        if ctx.audit is not None:
            ctx.audit.log(actor=r.reviewer, action=f"review:{r.reviewer_decision}", item_id=r.item_id,
                          before=before, after=out.loc[mask, fields].iloc[0].to_dict(), reason=r.review_note)

    ctx.stats.update({"n_reviewed": len(done), "t14_queue_reviewed": len(done & queue_ids),
                      "t14_review_counts": counts, "t14_review_unknown_ids": unknown})
    return out


def decide(ctx, final: pd.DataFrame) -> Decision:
    """GO only when every queued box has a final human decision, no label is invalid and the export QA passed."""
    images = pd.read_csv(ctx.input_dir / "images.csv")
    taxonomy_names = set(load_taxonomy(ctx.input_dir / "taxonomy.yaml").values())
    n_invalid = int(invalid_mask(final, images, taxonomy_names).sum())
    n_queue = int(ctx.stats.get("t14_queue_size", 0))
    n_done = int(ctx.stats.get("t14_queue_reviewed", 0))
    unknown = ctx.stats.get("t14_review_unknown_ids", [])
    export_ok = bool(ctx.stats.get("t14_export_qa", {}).get("pass", False))

    if n_invalid or not export_ok:
        status, code = "REWORK", "INVALID_LABELS" if n_invalid else "EXPORT_QA_FAILED"
        reason = f"{n_invalid} invalid labels in the export; export QA pass={export_ok}"
    elif unknown:
        status, code = "HOLD", "REVIEW_FILE_STALE"
        reason = f"{len(unknown)} reviewed ids are not in this run (e.g. {unknown[:3]}); re-export the review from the current queue"
    elif n_done < n_queue or n_queue == 0:
        status, code = "HOLD", "REVIEW_INCOMPLETE"
        reason = f"{n_done}/{n_queue} queued boxes have a final human decision (approve/reject/edit)"
    else:
        status, code = "GO", "REVIEW_COMPLETE_LABELS_VALID"
        reason = f"all {n_queue} queued boxes reviewed, invalid-label rate = 0, export QA passed"

    return Decision(
        status=status, reason_code=code, reason=reason,
        owner=ctx.config.get("owner") or "TODO-owner", scope=ctx.track,
        evidence=[str(ctx.out(f)) for f in ("predictions.csv", "review_queue.csv", "audit_log.jsonl", "export/qa_report.json")],
        metrics={"n_exported": int(len(final)), "invalid_label_rate": n_invalid / max(len(final), 1),
                 "queue_size": n_queue, "queue_reviewed": n_done, "review_counts": ctx.stats.get("t14_review_counts", {})},
    )
