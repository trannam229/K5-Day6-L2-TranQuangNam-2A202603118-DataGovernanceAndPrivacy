from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def review(
    predictions_path,
    review_path,
    output_path,
    audit_path,
):
    pred_df = pd.read_csv(predictions_path)
    review_df = pd.read_csv(review_path)

    reviewed = pred_df.copy()

    audit_file = Path(audit_path)
    audit_file.parent.mkdir(parents=True, exist_ok=True)

    with open(audit_file, "w", encoding="utf-8") as f:

        for _, row in review_df.iterrows():

            prediction_id = row["prediction_id"]
            decision = str(row["decision"]).lower().strip()

            mask = reviewed["prediction_id"] == prediction_id

            if not mask.any():
                continue

            old_data = reviewed.loc[mask].iloc[0].to_dict()

            if decision == "reject":
                reviewed = reviewed.loc[~mask]

                f.write(
                    json.dumps({
                        "prediction_id": prediction_id,
                        "action": "reject",
                        "before": old_data
                    })
                    + "\n"
                )

            elif decision == "edit":

                new_data = old_data.copy()

                for col in ["class", "x", "y", "w", "h"]:
                    review_col = f"new_{col}"

                    if review_col in review_df.columns:
                        value = row[review_col]

                        if pd.notna(value):
                            new_data[col] = value

                for k, v in new_data.items():
                    reviewed.loc[mask, k] = v

                f.write(
                    json.dumps({
                        "prediction_id": prediction_id,
                        "action": "edit",
                        "before": old_data,
                        "after": new_data
                    })
                    + "\n"
                )

    reviewed.to_csv(output_path, index=False)
    return reviewed


def decide(review_path, predictions_path):

    review_df = pd.read_csv(review_path)
    pred_df = pd.read_csv(predictions_path)

    reviewed_count = (
        review_df["decision"]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
        .sum()
    )

    total_queue = len(review_df)

    queue_complete = reviewed_count == total_queue

    valid_classes = [
        "car",
        "pedestrian",
        "motorbike",
        "sign",
    ]

    invalid_count = (
        ~pred_df["class"].isin(valid_classes)
    ).sum()

    invalid_rate = invalid_count / max(len(pred_df), 1)

    if queue_complete and invalid_rate == 0:
        status = "GO"
    elif queue_complete:
        status = "REWORK"
    else:
        status = "HOLD"

    return {
        "decision": status,
        "invalid_rate": invalid_rate,
        "reviewed_count": reviewed_count,
        "total_queue": total_queue,
    }