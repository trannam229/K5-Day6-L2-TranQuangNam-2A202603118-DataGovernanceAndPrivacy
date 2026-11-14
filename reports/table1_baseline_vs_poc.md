Baseline: `baseline` (git 029f1cf, seed 42) · PoC: `poc` (git 029f1cf, seed 42)

| Metric (unit) | Slice | Baseline | PoC | Δ abs | Δ rel | Better | N |
|---|---|---|---|---|---|---|---|
| **Detection F1@IoU0.5** (class-aware greedy match) | all | 0.8944 | 0.9000 | 0.0056 | +0.6% | higher | 83 |
| Precision (TP/(TP+FP)) | all | 0.9231 | 0.9351 | 0.0120 | +1.3% | higher | None |
| Recall (TP/(TP+FN)) | all | 0.8675 | 0.8675 | 0.0000 | +0.0% | higher | None |
| Invalid-label rate (exported boxes with unknown class or out-of-bounds / exported boxes) | all | 0.0128 | 0.0000 | -0.0128 | -100.0% | lower | None |
| Runtime / 100 items (s) | all | 0.0084 | 0.1001 | | | lower | |
