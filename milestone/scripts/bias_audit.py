"""Run an AIF360 fairness audit on the trainer-provided loan decision data.

The column names vary between classroom exports, so this script requires the
true label, model prediction, protected attribute, and privileged value. It
writes disparate impact, statistical parity difference, and equal opportunity
difference plus a plain-language interpretation to JSON.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _binary(series: pd.Series, positive_value: str) -> pd.Series:
    return (series.astype(str).str.strip().str.casefold() == positive_value.strip().casefold()).astype(float)


def audit(
    csv_path: Path,
    label_column: str,
    prediction_column: str,
    protected_column: str,
    privileged_value: str,
) -> dict[str, object]:
    try:
        from aif360.datasets import BinaryLabelDataset
        from aif360.metrics import BinaryLabelDatasetMetric, ClassificationMetric
    except ImportError as error:
        raise RuntimeError("Install M6 dependencies first: pip install -r requirements-milestone6.txt") from error

    frame = pd.read_csv(csv_path)
    required = [label_column, prediction_column, protected_column]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns {missing}. Available columns: {list(frame.columns)}")

    # AIF360 receives numeric 0/1 labels and a binary privileged indicator.
    # The positive class is inferred as 1/true/yes/approved when present;
    # otherwise the caller should provide a pre-binarized class-lab CSV.
    def label_to_binary(series: pd.Series) -> pd.Series:
        values = {str(value).strip().casefold() for value in series.dropna().unique()}
        for candidate in ("1", "true", "yes", "approved", "approve"):
            if candidate in values:
                return _binary(series, candidate)
        if values <= {"0", "1"}:
            return pd.to_numeric(series, errors="raise").astype(float)
        raise ValueError(f"Cannot infer positive label from values {sorted(values)}. Supply a binary classroom CSV.")

    prepared = pd.DataFrame(
        {
            "label": label_to_binary(frame[label_column]),
            "prediction": label_to_binary(frame[prediction_column]),
            "protected": _binary(frame[protected_column], privileged_value),
        }
    ).dropna()
    true_dataset = BinaryLabelDataset(
        df=prepared[["label", "protected"]],
        label_names=["label"],
        protected_attribute_names=["protected"],
        favorable_label=1.0,
        unfavorable_label=0.0,
    )
    predicted_dataset = true_dataset.copy(deepcopy=True)
    predicted_dataset.labels = prepared[["prediction"]].to_numpy()
    privileged_groups = [{"protected": 1.0}]
    unprivileged_groups = [{"protected": 0.0}]
    group_metric = BinaryLabelDatasetMetric(predicted_dataset, unprivileged_groups, privileged_groups)
    classification_metric = ClassificationMetric(true_dataset, predicted_dataset, unprivileged_groups, privileged_groups)

    disparate_impact = float(group_metric.disparate_impact())
    statistical_parity_difference = float(group_metric.mean_difference())
    equal_opportunity_difference = float(classification_metric.equal_opportunity_difference())
    interpretation = {
        "disparate_impact": "Near 1.0 indicates similar selection rates; values below 0.80 require investigation.",
        "statistical_parity_difference": "Near 0.0 indicates similar selection rates; negative values disadvantage the unprivileged group.",
        "equal_opportunity_difference": "Near 0.0 indicates similar true-positive rates; negative values disadvantage the unprivileged group.",
        "judgment": (
            "Investigate before release: at least one fairness signal exceeds the classroom screening threshold."
            if disparate_impact < 0.80 or abs(statistical_parity_difference) > 0.10 or abs(equal_opportunity_difference) > 0.10
            else "No screening threshold was exceeded in this synthetic audit; continue monitoring because this is not proof of fairness."
        ),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(csv_path),
        "rows_audited": len(prepared),
        "configuration": {
            "label_column": label_column,
            "prediction_column": prediction_column,
            "protected_column": protected_column,
            "privileged_value": privileged_value,
        },
        "metrics": {
            "disparate_impact": disparate_impact,
            "statistical_parity_difference": statistical_parity_difference,
            "equal_opportunity_difference": equal_opportunity_difference,
        },
        "interpretation": interpretation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--label-column", required=True)
    parser.add_argument("--prediction-column", required=True)
    parser.add_argument("--protected-column", required=True)
    parser.add_argument("--privileged-value", required=True)
    parser.add_argument("--output", type=Path, default=Path("evidence/bias_audit_results.json"))
    args = parser.parse_args()
    report = audit(args.csv, args.label_column, args.prediction_column, args.protected_column, args.privileged_value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved AIF360 audit to {args.output}")


if __name__ == "__main__":
    main()