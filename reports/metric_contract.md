# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | T14 · Auto-Annotation + Human QC Exporter |
| Primary metric (tên đúng như evaluator in ra) | Detection F1@IoU0.5 |
| Tăng tốt hay giảm tốt? | higher |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | bounding box (20 eval images) |
| Công thức + numerator / denominator | 2 * TP / (2 * TP + FP + FN) tại IoU >= 0.5 và khớp tên class |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | Ghép tham lam theo từng ảnh, prediction xếp theo `conf` giảm dần; TP khi IoU ≥ 0.5 với một GT chưa ghép và cùng tên class (`src/metrics/detection.py::match_detections`). GT nhóm tự chấm: `fixtures/t14_auto_annotation/internal_gt_boxes.csv` (nhãn nội bộ, phần lớn dựa trên box của model nên không đo được sai lệch vị trí box) |
| Candidate pool cố định | Toàn bộ box trong `fixtures/t14_auto_annotation/model_predictions_fixture.csv` (60 ảnh: 40 dev, 20 eval) |
| Review budget B / K | B = 30 box |
| Seed | 42 |
| Threshold policy (chọn trên dev như thế nào) | Chọn trên split `dev`, đóng băng trong `configs/lab.yaml` (`params`) trước khi chạy eval: `class_conf_threshold` theo từng class, `small_conf_threshold` cho box nhỏ (<150px²) thuộc `small_classes` |
| Eval split (không dùng để tune) | `eval` (20 ảnh) |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | Miss: recall của slice `small_objects(<150px²)`; kèm Invalid-label rate (phải = 0) |
| Slices sẽ báo cáo (≥2) | class=car, class=pedestrian, class=motorbike, class=sign, small_objects(<150px²) |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | Wilson 95% CI cho precision / recall trên từng slice; ghi rõ N khi N < 30 |
| Ngày giờ chốt + người chốt | 2026-11-14 16:42 (giờ VN) · harrutoryuoma (G01) |

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.
