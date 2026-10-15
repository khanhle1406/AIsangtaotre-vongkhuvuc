# Kiểm tra độ ổn định và chuyển giao sang Qwen

Các kết quả dưới đây là Gemini 3 Flash sinh mới trên gateway phát triển. Chưa có phép đo Qwen mới; chưa thể xác nhận độ đúng trên private của BTC. Báo cáo lịch sử v3/v4 vẫn ở `EFFICIENCY.md`, không dùng điểm của source cũ thay cho source hiện tại.

## Đối chiếu v6

Source đã khóa tại `reports/optimization/efficiency_v6_qualification/source_lock.json`. Cùng dữ liệu, máy và gateway; baseline concurrency 2, candidate concurrency 4 và lập chương trình chung tối đa bốn câu/workbook.

| Bộ | Exact Match | Tổng giây | Token |
| --- | --- | --- | --- |
| Baseline public | 19/20 | 24,365 | 200.378 |
| Candidate public 1 | 20/20 | 9,345 | 113.964 |
| Candidate public 2 | 20/20 | 10,430 | 112.942 |
| Candidate public 3 | 20/20 | 8,599 | 105.606 |
| Regression 60 | 60/60 | 31,785 | 240.371 |
| Regression 32 | 32/32 | 19,192 | 121.013 |
| Validation đã biết | 17/18 | 13,334 | 108.427 |
| Synthetic đã biết | 24/24 | Xem report | Xem report |

Public trung bình giảm **61,18% tổng thời gian / 44,69% token**, chưa đạt giảm token 50%. Một lỗi còn lại là đọc nhầm trường ngày của cùng bản ghi. Không chấp nhận v6 làm cấu hình hoàn tất. Bộ 24 câu độc lập mới vẫn chưa được mở. Synthetic đã sinh xong nhưng harness trỏ nhầm tên CSV đáp án; điểm được phục hồi từ checkpoint với HTTP bị chặn, không gọi model lại.

## Thay đổi tổng quát tiếp theo

- Dùng cùng biểu diễn lossless dạng dãy ô cho lượt lập chương trình và lượt sửa/kiểm chứng. Trước đây lượt sửa gửi biểu diễn dài hơn, làm tăng token khi có lỗi. Vẫn giữ đầy đủ tọa độ, kiểu và metadata; workbook lớn tiếp tục dùng view có công bố phần chưa hiển thị.
- `data_rows` hỗ trợ cận hàng có kiểm tra, bao gồm dòng đầu/cuối. Không tự coi chọn nhầm cột thành bảng rỗng.
- `age_order`/`age_days` hỗ trợ ngày typed và chuỗi ISO; định dạng khác cần `date_format` tường minh. Thứ hạng giữ độ chính xác trong ngày. Không đoán ngày/tháng theo locale.
- Kiểm tra trường ngày được hỏi khi tên cột xác định duy nhất; phát hiện dùng cột ngày khác mà chưa đọc cột yêu cầu. Không tự thay đáp án.
- Bổ sung kiểm tra đơn vị, đếm nhầm header, cực trị có dấu và trả số đo thay cho nhãn. Các kiểm tra dựa trên câu hỏi, code và workbook; không có lookup ID/đáp án.
- JSON chung được kiểm tra khóa trùng, chỉ số/nhắc lại câu hỏi và metadata; retry giữ hợp đồng khóa. Phản hồi HTTP hỏng được chuyển về luồng xử lý lỗi và hạch toán hiện có.
- Chỉ bổ sung dấu đóng object/array bị thiếu ở cuối JSON khi mọi chuỗi/giá trị đã hoàn tất. Decoder nghiêm ngặt vẫn từ chối khóa trùng, giá trị thiếu hoặc chuỗi chưa đóng; raw response được lưu. Không thêm code, khóa hay giá trị.
- Phân biệt các bản ghi có cùng dimension trong một ledger với các section khác nhau khi cộng gộp. Các điều kiện năm/nhóm tường minh vẫn được kiểm tra; không bỏ kiểm chứng chỉ để giảm số request.
- Khi lỗi thực thi thuộc kiểu/cú pháp, gửi lại đoạn chương trình bị lỗi cạnh thông báo để sửa đúng API; các lỗi chọn nguồn vẫn yêu cầu chọn lại từ dữ liệu. Không gửi đáp án chuẩn vào prompt.

## Các lượt không đạt được giữ nguyên

| Source | Ba lượt public | Regression 60 / 32 | Validation 18 | Synthetic 24 |
| --- | --- | --- | --- | --- |
| v6 | 20, 20, 20 /20 | 60/60; 32/32 | 17/18 | 24/24 |
| v7 | 20, 20, 19 /20 | 60/60; 32/32 | 17/18 | 24/24 |
| v8 | 20, 20, 19 /20 | 60/60; 32/32 | 18/18 | 24/24 |

Các source này chưa được chấp nhận, chưa mở bộ độc lập mới. v8 regression 60 có một HTTP attempt thiếu usage khi retry; báo cáo giữ dự trù token cho lượt đó, không coi usage bằng 0 và không dùng tổng token đã biết để kết luận tiết kiệm trên bộ này. Không chọn riêng lượt 20/20 để che lượt 19/20.

## Cách tái lập và điều kiện chấp nhận

### Phép kiểm định độc lập v10: không chấp nhận candidate

v10 đạt public **20/20 ở cả ba lượt** và regression **60/60, 32/32, 18/18, 24/24**. Trên bộ 24 câu mới đã khóa, baseline **24/24**, candidate **23/24**. Candidate đảo `ordered - shipped` thành `shipped - ordered` khi xếp hạng lượng chưa giao, dù code chạy thành công. Gate chặn Qwen trước mọi inference trả phí: `qwen_batch_signoff.json` có `status=blocked_qualification`, `new_generations=0`, `promoted=false`.

| v10 | Baseline | Candidate |
| --- | --- | --- |
| Public Exact Match | 20/20 | 20/20, 20/20, 20/20 |
| Public tổng giây | 26,249 | 132,472; 7,436; 7,684 |
| Public token | 187.920 | 137.891; 93.014; 92.770 |
| Độc lập 24 câu Exact Match | 24/24 | 23/24 |
| Độc lập tổng giây | 91,804 | 6,464 |
| Độc lập token đã biết | 114.902 | 32.768 |
| Request thiếu usage | 1 | 0 |
| Độc lập token bảo thủ | 134.821 | 32.768 |

Không bỏ response public kéo dài khoảng 129 giây: trung bình ba lượt candidate **49,197 giây / 107.891,67 token**, chậm hơn baseline 87,42% và chỉ giảm token 42,59%. Baseline độc lập cũng có response chậm khoảng 82,65 giây; chênh lệch thời gian lớn có ảnh hưởng của gateway. Giảm 71,48% token đã biết trên độc lập không phải tổng token chính xác vì baseline có một request thiếu usage. RAM đỉnh các stage v10 không quá **124,30 MiB**. Độ đúng giảm một câu nên mọi lợi ích tài nguyên đều không đủ để chấp nhận phiên bản này.

### Sau kiểm định

Bộ 24 câu này đã tiêu thụ. Những lượt tiếp theo chỉ gọi là regression. Bổ sung một lượt kiểm chứng độc lập khi xếp hạng theo hiệu số lấy từ nhiều sheet; tín hiệu dựa trên câu hỏi, AST phép trừ và nguồn số thực sự đọc, không dựa trên ID/đáp án hay riêng lĩnh vực đơn hàng. Không tự sửa dấu của kết quả. Gateway cũng kiểm tra deadline của từng HTTP attempt khi đọc SSE, thay vì chỉ deadline cả batch; heartbeat không gia hạn đồng hồ. Socket read timeout vẫn áp dụng cho thao tác đọc đang chặn, không cam kết đóng mạng đúng tại từng mili giây. Request thiếu usage giữ dự trù token cả trong tổng theo câu và tổng toàn lượt.

237 test, Ruff check và format đã đạt trước lần đo regression v11. Source mới cần kiểm định độc lập mới và xác nhận Qwen; không chuyển điểm v10 sang phiên bản này.

### Regression v11 và giới hạn còn lại

| Bộ v11 | Exact Match | Tổng giây | Token đã biết |
| --- | --- | --- | --- |
| Baseline public | 19/20 | 28,824 | 204.377 |
| Public 1 | 20/20 | 7,185 | 92.698 |
| Public 2 | 20/20 | 8,767 | 95.386 |
| Public 3 | 20/20 | 8,895 | 110.276 |
| Regression 60 | 60/60 | 20,551 | 167.313 |
| Regression 32 | 30/32 | 80,064 | 145.109 |
| Validation 18 | 18/18 | 12,779 | 70.923 |
| Synthetic 24 | 24/24 | 9,548 | 67.118 |
| Bộ 24 đã tiêu thụ | 24/24 | 12,206 | 62.650 |

Public trung bình **8,282 giây / 99.453,33 token**, giảm **71,27% thời gian / 51,34% token** so với baseline cùng đợt, usage đầy đủ cho cả bốn lượt public. Đây là cải thiện so với baseline đối chiếu, không phải giảm 50% so với lượt nhanh nhất lịch sử. Bộ 32 có một request thiếu usage nên không khẳng định tổng token thực tế của bộ này. Không chấp nhận v11 vì còn hai lỗi trên regression 32, dù bộ 24 đã biết tăng lên đủ điểm; 24/24 đó không phải kiểm định độc lập mới.

Hai nguyên nhân tiếp tục được sửa bằng hợp đồng tổng quát: `rows()` phải ghi nhận bằng chứng cấu trúc và được công nhận là phụ thuộc vào workbook khi đếm hàng; gọi `rows()` không liên quan rồi trả literal vẫn bị từ chối. So sánh `str(datetime)` có dấu cách với timestamp ISO chứa `T` có thể phân loại sai giờ trong cùng ngày; ứng dụng yêu cầu so sánh datetime hoặc chuẩn hóa định dạng, giữ nguyên các yêu cầu xếp thứ tự chuỗi tường minh. 239 test và Ruff check/format đã đạt trước phép đo regression v12.

`python -m benchmarks.transfer_qualification --root reports/optimization/<new-run>` thực hiện đúng một lịch cố định: baseline public, ba lượt candidate public, các regression 60/32/18/24, rồi mới đánh giá baseline/candidate trên bộ 24 câu độc lập nếu mọi prerequisite đều đạt. Mỗi phiên dùng chung trần 30 phút, 200 HTTP attempts và hai triệu token. Không ghi đè report hoặc tái dùng holdout đã tiêu thụ như holdout mới. Source/hash cấu hình và snapshot được lưu trước inference; đáp án chuẩn chỉ đi vào evaluator.

Sau khi một bộ đã tiêu thụ, thêm `--regression-only` để chạy lại dữ liệu đã biết; chế độ này không thay receipt kiểm định độc lập và ghi rõ `independent_validation=false`. Nó không tạo báo cáo `heldout_proof` để vượt gate Qwen.

Các họ mới gồm chính sách thuế lũy tiến, đối soát Orders/Shipments và hợp khoảng thời gian. Oracle tính riêng, vị trí bảng/nhãn/file khác public. Một bộ synthetic nhỏ không đại diện đầy đủ cho phân phối private của BTC.

CLI tùy chọn cho Qwen đã có:

```bash
python -m benchmarks.batched_submission --input-dir /new/xlsx_files --queries /new/queries.json --output /new/submission.csv
```

CLI này chỉ nhận model thi qua OpenRouter, không dùng khóa hoặc endpoint phát triển; vẫn kiểm tra chi phí, thời gian, RAM và ghi CSV/trace. `run.py` chưa đổi mặc định. Mock test của transport không chứng minh độ chính xác của Qwen.

Khi candidate vượt qualification và kiểm định đã khóa, chạy `python -m benchmarks.qwen_batch_signoff --root reports/optimization/<qualified-run>`. Gate kiểm tra source/dataset, số dư trước inference và ngân sách tối đa 0,05 USD từ sổ tổng 0,50 USD. Không tự chuyển model hoặc nâng cấu hình thi nếu thiếu credit. Thứ tự chọn vẫn Exact Match → thời gian → token, không chấp nhận giảm Exact Match trên một bộ để bù bằng tốc độ.

Thời gian tổng/số câu thể hiện throughput; độ trễ từng câu và RAM tổng RSS chính+worker được lưu riêng trong report. Giảm wall time khi tăng concurrency không đồng nghĩa từng request nhanh hơn. Phải xác nhận lại trên máy và model chấm thi.
