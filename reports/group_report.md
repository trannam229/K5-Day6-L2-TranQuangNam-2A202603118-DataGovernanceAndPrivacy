# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Mọi con số lấy từ file do script sinh ra (`reports/metrics_*.json`, `reports/slices_*.csv`,
> `reports/table1_baseline_vs_poc.md`, `out/poc/run_info.json`). Khoảng tin cậy Wilson 95% do nhóm tính từ
> tử số / mẫu số trong các file đó.

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | G01 |
| Challenge | T14 · Auto-Annotation + Human QC Exporter |
| Thành viên (4) + vai trò | 1. Trần Quang Nam (Lead / Data & Baseline) · 2. Võ Duy Thành (Core Algorithm & Exporter) · 3. Bùi Anh Dũng (Human-in-the-Loop & Decision Gate) · 4. Nguyễn Minh Hiếu (QA / Metric, Unit Tests & Report) |
| Git URL | https://github.com/trannam229/K5-Day6-L2-TranQuangNam-2A202603118-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | Gắn trên commit chứa báo cáo này — `git rev-list -n 1 demo-180m` |
| Tag `final-24h` (commit) | Chưa gắn |
| Deadline (giờ VN) | Nhóm bổ sung |

## 01 · Problem statement

- **Ai chịu hậu quả khi hệ thống sai?** Đội gán nhãn và đội huấn luyện model dùng bộ nhãn xuất ra. Nhãn sai class hoặc thiếu
  object nhỏ (người đi bộ, biển báo ở xa) đi thẳng vào dữ liệu huấn luyện và làm model đời sau kém đúng ở các đối tượng đó.
- **Điểm nghẽn:** người duyệt không thể xem hết mọi box. Với 234 box model sinh ra trên 60 ảnh, nhóm chỉ có ngân sách duyệt
  B = 30 box, nên phải chọn đúng box đáng xem.
- **Đầu vào → đầu ra:** `model_predictions_fixture.csv` (box + `class_id` theo label map của model) →
  `out/poc/predictions.csv` (`image_id, class, x, y, w, h, conf`, class theo tên taxonomy) + export YOLO / COCO.
- **Tiêu chí quyết định** (`src/t14_reviewer.py::decide`): **GO** khi đủ 30/30 box trong hàng đợi có quyết định cuối
  (approve / reject / edit), Invalid-label rate = 0 và QA export đạt. **HOLD** khi chưa duyệt đủ hoặc file duyệt không khớp
  hàng đợi. **REWORK** khi còn nhãn không hợp lệ hoặc QA export không đạt.
- **Giả định:** ảnh là dữ liệu tổng hợp nên không có dữ liệu cá nhân. Nếu áp dụng cho ảnh đường phố thật thì khuôn mặt và
  biển số là dữ liệu cá nhân, cần DPO / pháp chế xác nhận trước khi dùng.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev | 40 ảnh · 143 box GT nội bộ | `synthetic:tools/make_fixtures.py (seed 42)` — `fixtures/t14_auto_annotation/` | CC0-1.0 (synthetic, generated for AI20K Day06) | Có |
| eval | 20 ảnh · 83 box GT nội bộ | như trên | như trên | Có |

- **Schema & class mapping:** model dùng label map kiểu COCO (`0: person, 2: car, 3: motorcycle, 11: stop sign`), taxonomy dự án
  là `0: car, 1: pedestrian, 2: motorbike, 3: sign`. Nhóm ánh xạ **theo tên** (`person→pedestrian`, `motorcycle→motorbike`,
  `stop sign→sign`), không theo id, vì id 0 của model là người còn id 0 của taxonomy là xe.
- **Seed:** 42 · **Split:** tách sẵn trong `images.csv` của fixture; nhóm không chia lại.
- **`manifest.csv` verified (sha256): có** — `python -m tools.verify_manifests` → `14 manifests, 0 failing`. Pipeline kiểm
  hash ở bước `load()` và dừng nếu lệch (`strict_provenance: true`).
- **Dữ liệu thật:** không dùng.
- **Ground truth để chấm:** GT chính thức (`gt/gt_boxes.csv`) không có trong repo. Nhóm tự làm
  `fixtures/t14_auto_annotation/internal_gt_boxes.csv` (226 box): 214/234 box của model được giữ nguyên toạ độ sau khi kiểm,
  17 box bị loại vì là box giả, 3 box tràn biên được cắt lại, 3 box sửa class, 9 box model bỏ sót được thêm tay.

## 03 · Research & design

- **Kỹ thuật và lý do:** (1) ánh xạ class theo tên + kiểm tra với taxonomy, để chặn bẫy "sai label map vẫn export hợp lệ";
  (2) ngưỡng confidence theo class, hạ ngưỡng cho box nhỏ của `sign` / `motorbike` vì model kém tự tin ở object nhỏ;
  (3) chấm điểm ưu tiên duyệt theo ba tín hiệu: conf sát ngưỡng, box chồng lấn, box nhỏ; (4) QA khứ hồi YOLO ↔ COCO trước khi
  cho xuất. Các hướng này lấy từ gợi ý trong `docs/tracks/T14.md`; tài liệu gốc liệt kê ở mục 11.
- **Data flow:** `load` (kiểm hash, đọc 4 file) → `process` (map class, cắt box vào ảnh, lọc ngưỡng, chấm điểm) →
  `rank` (top 30 + contact sheet) → `review` (áp `review_queue_reviewed.csv`, ghi audit log) → `finalize` + `export`
  (chặn nhãn không hợp lệ, xuất YOLO / COCO, QA) → `decide` (GO / HOLD / REWORK).
- **Thành phần offline:** không có model hay weights. Prediction là **fixture mô phỏng**
  (`simulated-detector-fixture`, version `fixture-1`, license `n/a (synthetic)`), không phải kết quả suy luận thật.
- **Trade-off:** ngưỡng 0.40 cho mọi class tăng precision nhưng loại nhiều người đi bộ nhỏ; nhóm dựa vào bước duyệt để khôi
  phục chúng thay vì hạ ngưỡng (xem mục 06 và 09).

## 04 · Baseline vs PoC

- **Baseline** (`src/baseline_t14.py`, commit `c4b1a58`): một ngưỡng cố định `conf >= 0.25` cho mọi class, không cắt box,
  không duyệt.
- **PoC** (`src/t14_processor.py` `6fa93c0` / `3419c89`, `src/t14_reviewer.py` `3c50544`; tham số trong `configs/lab.yaml`):
  ngưỡng 0.40 theo class, 0.25 cho box nhỏ (<150px²) của `sign` / `motorbike`, cắt box vào khung ảnh, hàng đợi 30 box, áp kết
  quả duyệt. Lần chạy báo cáo ở git `029f1cf`.
- **Cùng pool / budget / seed / split:** xác nhận — cùng 234 box đầu vào, B = 30, seed 42, split `eval` (20 ảnh).

**Bảng 1 · Baseline vs PoC** (`reports/table1_baseline_vs_poc.md`, split eval, 83 box GT):

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| Primary: Detection F1@IoU0.5 | 0.8944 | 0.9000 | +0.0056 (+0.6%); higher. Chênh đúng 1 box sai (78 → 77 box xuất, TP đều 72) |
| Precision | 0.9231 (72/78) | 0.9351 (72/77) | +0.0120 |
| Recall | 0.8675 (72/83) | 0.8675 (72/83) | 0 |
| Hard-slice: recall `small_objects(<150px²)` | 0.900 | 0.900 | 0; N = 10 |
| Invalid-label rate | 0.0128 (1/78) | 0.0000 (0/77) | −0.0128; lower |
| Review@B | không duyệt | 23 approve · 4 reject · 3 edit | B = 30 |
| Runtime / 100 items | 0.0084 s | 0.1001 s | CPU = Apple M4 |

**Tác động của bước duyệt** (`reports/metrics_poc_no_review.json` so với `reports/metrics_poc.json`): PoC chưa duyệt đạt
F1 0.8645 (recall 67/83 = 0.807), thấp hơn baseline. Sau khi duyệt 30 box, F1 lên 0.9000 (recall 72/83), tức correction gain
ΔF1 = +0.0355. Việc duyệt là thứ đưa PoC lên ngang rồi vượt nhẹ baseline.

## 05 · Evaluation protocol

- **Primary metric:** Detection F1@IoU0.5 = 2·TP / (2·TP + FP + FN), đơn vị là bounding box. Prediction được ghép tham lam
  theo từng ảnh, xếp theo `conf` giảm dần; TP khi IoU ≥ 0.5 với một GT chưa ghép và cùng tên class. Chi tiết trong
  `reports/metric_contract.md`.
- **Threshold / budget:** tham số ngưỡng như mục 04, B = 30. Contract được ghi lúc 16:42 ngày 2026-11-14 (giờ VN), muộn hơn
  mốc phút 30 (xem mục 09).
- **Độ bất định (Wilson 95%):** precision PoC 72/77 = 0.935 [0.857, 0.972]; baseline 72/78 = 0.923 [0.842, 0.964]; recall cả
  hai 72/83 = 0.867 [0.778, 0.924]. Hai khoảng precision chồng lên nhau gần hết, nên **chênh lệch F1 không có ý nghĩa thống
  kê**. Slice `small_objects` chỉ có N = 10: 9/10 = 0.900 [0.596, 0.982].
- **Lệnh evaluate:**
  `python -m src.evaluate --track t14 --gt fixtures/t14_auto_annotation/internal_gt_boxes.csv --pred out/poc/predictions.csv --run-name poc --out reports/metrics_poc.json --slices-out reports/slices_poc.csv`

## 06 · Result slices

Split eval, từ `reports/slices_baseline.csv` và `reports/slices_poc.csv` (giá trị F1; cột cuối là recall của PoC chưa duyệt):

| Slice | N | Baseline | PoC | Ghi chú |
|---|---|---|---|---|
| class=car | 39 | 0.933 | 0.946 | Precision 0.972 → 1.000: khác biệt duy nhất giữa hai bản |
| class=motorbike | 12 | 0.870 | 0.870 | Không đổi |
| class=pedestrian | 23 | 0.818 | 0.818 | Recall chưa duyệt chỉ 0.565; duyệt khôi phục về 0.783 |
| class=sign | 9 | 0.947 | 0.947 | N nhỏ |
| small_objects(<150px²) | 10 | recall 0.900 | recall 0.900 | Recall chưa duyệt 0.500 [0.237, 0.763] |

- **Failure case 1 — bỏ sót object (`aa_14`, eval):** ảnh cảnh đêm có một người đi bộ lớn bên phải (khoảng x=238, y=92,
  16×36) mà model không sinh box nào. Hàng đợi duyệt chỉ chứa box model đã sinh, nên quy trình hiện tại **không có cách thêm
  box bị sót**; lỗi này đi thẳng vào kết quả. GT nội bộ ghi nhận 9 trường hợp như vậy (`manual_fn_missed_by_model`).
  Root cause: thiết kế duyệt theo từng box thay vì theo từng ảnh.
- **Failure case 2 — box giả tự tin lọt qua duyệt (`aa_05#219`, eval):** model gán `pedestrian` với conf 0.573 lên một toà
  nhà. Box vượt ngưỡng 0.40 nên được giữ, và điểm ưu tiên duyệt của nó chỉ 0.06 (conf xa ngưỡng, box không nhỏ, không chồng
  lấn) nên không vào top 30. Có 7 box giả conf 0.50–0.59 và 3 box sai class nằm ngoài hàng đợi theo cách này. Root cause:
  điểm ưu tiên chỉ dùng conf và hình học, không có tín hiệu nào bắt được box sai mà model lại tự tin.
- **Hai bẫy đề nêu:** (a) *sai label map vẫn export hợp lệ* — đã chặn bằng ánh xạ theo tên và kiểm tra
  (`test_class_map_goes_through_names_not_ids`, `test_unknown_model_class_id_fails_loudly`); (b) *conf cao nhưng thiếu object
  nhỏ* — chỉ xử lý được một phần: ngưỡng 0.40 loại 5/10 object nhỏ trên eval trước khi duyệt.
- **Latency:** 0.1001 s / 100 box (PoC), 0.0084 s / 100 box (baseline), Apple M4, không dùng GPU.

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv` (bản đã duyệt: `reports/review_queue.csv`), B = 30, xếp theo
  `score = 0.45·margin + 0.30·overlap + 0.25·small`. Trong 30 box có 15 box đang bị loại (duyệt để khôi phục) và 15 box đang
  được giữ.
- **Phân công duyệt** (Tab 2 của `index.html`): rank 1–8 Trần Quang Nam (7 approve, 1 reject) · rank 9–15 Võ Duy Thành
  (6 approve, 1 reject) · rank 16–23 Bùi Anh Dũng (3 approve, 2 reject, 3 edit) · rank 24–30 Nguyễn Minh Hiếu (7 approve;
  file ghi tên mặc định "Member 4").
- **Override + audit log:** `src/t14_reviewer.py::review` áp từng dòng: `approve` giữ box (kể cả khôi phục box dưới ngưỡng),
  `reject` loại box, `edit` áp `override_value` (ví dụ `x=163; y=98; w=40; h=24`). Mỗi quyết định được ghi thêm vào
  `out/poc/audit_log.jsonl` với tên reviewer, trạng thái trước / sau và ghi chú. Log là chỉ-ghi-thêm nên chứa cả các lần chạy
  trước; lần chạy báo cáo là 30 dòng `review:*` lúc 10:35 UTC.
- **Decision:** `GO`, `reason_code = REVIEW_COMPLETE_LABELS_VALID`, owner Trần Quang Nam (Lead / Integrator). Lịch sử trong
  `reports/decision_log.csv`: các lần `HOLD` (chưa có policy, rồi 22/30 box) trước khi ra `GO`.
- **Khi nào không tự động release:** chưa duyệt đủ hàng đợi, file duyệt chứa id không thuộc lần chạy hiện tại, có nhãn không
  hợp lệ, hoặc QA export không đạt.
- **Chưa đo:** thời gian duyệt mỗi ảnh (review minute/image) không được ghi lại.

## 08 · Reproduce & tests

```bash
make setup
python -m src.main --track t14 --pipeline src.baseline_t14 --config configs/lab.yaml --output out/baseline --run-name baseline --offline --seed 42
make run TRACK=t14          # PoC; cần out/poc/review_queue_reviewed.csv (bản sao: reports/review_queue.csv) để ra GO
python -m src.evaluate --track t14 --gt fixtures/t14_auto_annotation/internal_gt_boxes.csv --pred out/poc/predictions.csv --run-name poc --out reports/metrics_poc.json
python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json --out reports/table1_baseline_vs_poc.md
pytest -q
```

- **Output của `pytest -q`:** `63 passed, 39 skipped` (39 test bị bỏ qua vì cần GT của giảng viên). `make preflight`:
  `0 FAIL, 2 WARN` (hai cảnh báo về thư mục tuỳ chọn `data/real` và `models_optional`).
- **Máy:** Apple M4 · macOS 26.6.2 (arm64) · Python 3.11.14 · git sha của lần chạy: `029f1cf`.

## 09 · Limitations & ethics

- **GT nội bộ thiên về model.** Phần lớn box GT chép toạ độ từ box của model, nên phép đo không thấy được box lệch vị trí và
  có lợi cho cấu hình giữ nhiều box. Số liệu trong báo cáo **không so sánh trực tiếp được** với kết quả chấm bằng GT của
  giảng viên. Ví dụ: 3 box được reviewer sửa cho ôm sát xe hơn lại khớp GT nội bộ kém hơn box gốc.
- **Cải thiện F1 rất nhỏ.** +0.0056 tương đương một box trên 83; khoảng tin cậy chồng nhau. Kết quả chắc chắn hơn là
  Invalid-label rate về 0 và recall được khôi phục nhờ duyệt.
- **Contract chốt muộn.** `metric_contract.md` được ghi lúc 16:42, sau khi nhóm đã chạy thử evaluate trên eval. Ngưỡng
  pedestrian từng được chỉnh xuống 0.33 (`271d0c9`) rồi hoàn về giá trị đã đóng băng (`3f2a341`); báo cáo dùng giá trị đã
  đóng băng.
- **Hỗ trợ của AI.** Nhóm dùng trợ lý AI (Claude) để viết / sửa một phần code và báo cáo, để đề xuất quyết định duyệt cho
  rank 1–8 và đo toạ độ cho 3 box `edit`. Reviewer đứng tên chịu trách nhiệm về các quyết định đó.
- **Dữ liệu audit chưa sạch.** Một số `review_note` bị cắt cụt và mất `reviewed_at` do lỗi gộp CSV (đã sửa ở `10fe14a`,
  nhưng file duyệt chưa được gộp lại).
- **Rủi ro pháp lý / PII / license:** dữ liệu tổng hợp, CC0-1.0, không có PII. Nếu thay fixture bằng model thật:
  Ultralytics YOLO26 dùng **AGPL-3.0** (hoặc Enterprise) — dùng học tập được, nhưng pipeline thương mại đóng cần bản
  Enterprise; phương án Apache-2.0 là RF-DETR cỡ N/S/M/L (các cỡ khác dùng Roboflow PML 1.0). Nhóm không tuyên bố tuân thủ
  GDPR hay luật Việt Nam; việc dùng ảnh thật cần DPO / pháp chế xác nhận.
- **Scale 10×:** hàng đợi cố định 30 box sẽ phủ tỷ lệ nhỏ hơn nhiều; cần ngân sách theo tỷ lệ và duyệt theo ảnh.
- **Kế hoạch cải tiến:** (1) cho phép reviewer thêm box bị sót; (2) thêm tín hiệu hình dạng theo class (tỷ lệ rộng/cao bất
  thường) để kéo box giả tự tin vào hàng đợi; (3) khử box trùng (còn 2 cặp box xe trùng nhau ở `aa_14`, `aa_49`);
  (4) chọn lại ngưỡng pedestrian trên dev; (5) làm GT độc lập với model.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (khớp `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author / email | Module / vai trò | Commit SHA chứng minh | Trình bày? |
|---|---|---|---|---|
| Trần Quang Nam | namtran / tranquangnam244@gmail.com | Lead / Data & Baseline: `configs/lab.yaml`, `load()`, `src/baseline_t14.py`, GT nội bộ, `index.html`, số liệu báo cáo | `9d0a2c1`, `c4b1a58`, `3c50544`, `eec0d04` | Có |
| Võ Duy Thành | VoDuyThanh / 11thanh2233@gmail.com | Core Algorithm & Exporter: `src/t14_processor.py`, tích hợp `src/pipeline.py` | `6fa93c0`, `3419c89` | Không |
| Bùi Anh Dũng | Bui Dung / 148409997+Bui1234@users.noreply.github.com | Human-in-the-Loop & Decision Gate: bản đầu `src/t14_reviewer.py`, duyệt rank 16–23, `team_contributions.csv` | `8073385`, `456a271` | Không |
| Nguyễn Minh Hiếu | harutoryuoma / harutoryuoma@gmail.com | QA / Metric, Unit Tests & Report: `reports/metric_contract.md`, `tests/test_t14_pipeline.py` | `c39fa88`, `79e05ad` | Có |

Ghi chú minh bạch: bản đầu của `src/t14_reviewer.py` (`8073385`) không khớp giao diện pipeline và được viết lại ở `3c50544`.

## 11 · References

| Nguồn | Ngày xem | Ý nghĩa |
|---|---|---|
| `docs/tracks/T14.md` (trong repo) | 2026-11-14 | Đề bài, metric, failure mode bắt buộc và ghi chú license |
| Tài liệu Ultralytics YOLO26 (theo Research Shelf của handout) | Nhóm bổ sung | Model phát hiện vật thể tham chiếu và điều khoản AGPL-3.0 |
| Tài liệu CVAT SDK auto-annotation và CVAT QA (theo Research Shelf của handout) | Nhóm bổ sung | Quy trình pre-annotate rồi người sửa, và kiểm tra chất lượng nhãn |

---

**Bảng 3 · Checklist chốt khi nộp**

- [x] Link repo trong báo cáo; input mẫu là dữ liệu tổng hợp, không chứa PII thật. (Tag cuối `final-24h` chưa gắn.)
- [x] Đúng 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy.
- [x] Có baseline / PoC metrics, 2 failure case, reviewer evidence, decision log.
- [x] Có license / source provenance, data splits, seed, offline environment, GT / eval N.
- [x] Mỗi thành viên có ≥1 commit và được nêu minh bạch trong bảng trên.
