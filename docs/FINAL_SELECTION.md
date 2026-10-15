# Bản chọn cuối của giai đoạn phát triển Gemini

**Chọn v64 / `parallel8`, dừng tối ưu theo tiêu chí thực dụng mới của người dùng.** Đây là phương án đã đo đạt public 20/20 ở cả ba lượt, 254/254 câu hồi quy mở rộng và 18/18 câu kiểm định độc lập mới. Không khẳng định tối ưu toàn cục hoặc bảo đảm điểm tập ẩn BTC. Các lần sinh dùng `ag/gemini-3-flash`; không dùng replay để cộng điểm.

## Kết quả sinh mới của bản chọn

Nguồn: `reports/optimization/v64_projection_proof/summary.json`, các checkpoint, CSV và trace cùng thư mục; thông số tổng hợp trong `reports/optimization/final_selection_v64.json`.

| Bộ / phương án | Exact Match | Tổng giây | Token API |
| --- | --- | --- | --- |
| Baseline public, một lượt | 20/20 | 25,886 | 216.864 |
| Candidate public 1 | 20/20 | 9,549 | 83.060 |
| Candidate public 2 | 20/20 | 6,474 | 73.166 |
| Candidate public 3 | 20/20 | 17,028 | 124.994 |
| **Candidate public trung bình** | **20/20** | **11,017** | **93.740** |
| Hồi quy mở rộng đã biết | **254/254** | 165,367 | 555.687 |
| Kiểm định mới — baseline | 17/18 | 40,952 | 171.497 |
| Kiểm định mới — candidate | **18/18** | **61,070** | **105.102** |

Public giảm **57,44% thời gian và 56,77% token so với baseline cùng đợt**. Tương ứng khoảng 0,551 giây và 4.687 token mỗi câu, tính tổng thời gian chia số câu; không dùng thời gian riêng một request để thay cho thời gian cả lượt. Baseline chỉ chạy một lượt; gateway/model có biến động, nên đây không phải bảo đảm thống kê về độ trễ.

Kiểm định mới tăng một câu đúng; token giảm **38,71%**, nhưng thời gian **tăng 49,12%**. Không đạt giảm 50% trên bộ này. Chọn candidate theo thứ tự đề thi: độ đúng trước thời gian, rồi token. Baseline xử lý đủ 18 ID, một câu thất bại vì code gọi `hasattr` không được hỗ trợ, không phải lỗi API. Cờ `complete=false` của baseline biểu thị có câu lỗi; cả 18 câu đều được thực hiện, không có HTTP lỗi hoặc thiếu usage. Candidate hoàn tất đủ 18/18, không lỗi.

RAM local đỉnh toàn tiến trình giải bài và worker trong đợt: **130,06 MiB**. Tất cả usage có số liệu; đợt v64 dùng 174 HTTP attempts, 1.330.370 token, dưới trần 30 phút / 200 attempts / 2 triệu token. Chi phí gateway được xem là miễn phí **theo xác nhận của người dùng**, không phải đo hóa đơn bằng 0. Sổ ngân sách phát triển giữ mức dự trù bảo thủ khoảng 0,318927 USD / 0,50 USD; không gọi Qwen trả phí trong giai đoạn này.

## So với các mốc lịch sử

V17 public trung bình 9,904 giây / 102.380,67 token: v64 chậm hơn khoảng **11,23%**, dùng ít hơn **8,44% token**. Vì vậy **không tuyên bố cải thiện 50% so với mốc lịch sử này**. V52 nhanh hơn (6,543 giây / 83.712 token, public đủ điểm ba lượt) nhưng chỉ đạt 249/254 trên bộ mở rộng. V46 đạt public đủ điểm ba lượt, 253/254 mở rộng, public 13,588 giây / 140.608,33 token. V64 có bằng chứng độ đúng mạnh hơn các phương án đó.

Mục tiêu giảm 50% so với cấu hình nhanh nhất lịch sử chưa đạt. Việc dừng áp dụng điều kiện bổ sung của người dùng: chọn phương án tốt nhất đã đo, giữ public 100% và ưu tiên tổng quát hóa, khi các thử nghiệm tối ưu tiếp theo không giữ được độ đúng hoặc không cải thiện hiệu suất. Không coi một lượt public nhanh riêng lẻ là bản thắng.

## Cách cải thiện và các phương án bị loại

- Giữ workbook đầy đủ, tọa độ/kiểu/merge/đơn vị; model chọn nguồn, Python tính trên dữ liệu thật. Dùng kế hoạch chung tối đa tám câu với backend và chương trình độc lập cho từng workbook/câu; kiểm tra nguồn và giới hạn mỗi câu vẫn riêng.
- Sửa hợp đồng helper/ngày tháng/phạm vi và hỗ trợ deque có giới hạn. Các bản replay sau sửa được ghi riêng; số điểm trên là lần Gemini sinh mới sau các sửa đó.
- Bổ sung kiểm tra cột được chiếu trong mã Python. Chỉ thu hẹp bằng chứng khi chứng minh được một vùng `cells()`, một vòng lặp ở cấp module, chỉ số cố định, không alias/biến đổi/nguồn bổ sung. Trường hợp không chắc giữ kiểm tra cũ. Toàn bộ read audit gốc và kiểm tra selection vẫn giữ nguyên.
- Khi một phép xếp hạng dùng trực tiếp một cột số nhưng câu hỏi nêu rõ nhánh tiêu đề khác, kiểm tra ô caption/vùng gộp thật và ancestry. Không tự chọn đáp án hoặc sửa số. Tránh áp dụng vào metric suy ra bằng phép toán, tiêu đề mơ hồ hoặc các miền header xung đột. Kiểm thử có đổi tên, dịch sau dòng 300, đảo cột và dữ liệu tổng hợp độc lập.
- Audit offline nguyên chương trình sai v60 chứng minh cách đọc cả vùng có thể che việc dùng nhầm cột: 390 ô đọc, chỉ 78 ô thuộc các cột được chiếu. Kiểm tra mới phát hiện nhánh sai; đây là kiểm chứng guard, không cộng vào điểm LLM.

V62 thử ngôn ngữ biểu thức JSON: 88/92 so với control 91/92, bị loại. Đợt này còn thay cách đóng gói nên không suy diễn nguyên nhân từ riêng compiler. V63 sửa hợp đồng rồi so sánh cùng cách đóng gói trên 40 câu một sheet đã biết: cả hai 40/40, nhưng JSON tăng khoảng 79,74% thời gian và 91,90% token. `expressions8` chỉ là thử nghiệm, không phải bản chọn.

V65 là thử nghiệm cuối: cho các lượt sửa độc lập chạy song song, dùng chung semaphore giới hạn cả planner/API/worker. Unit test chứng minh không vượt bốn tác vụ, không trộn workbook hoặc tính token hai lần; không thay prompt/thuật toán. Lượt sinh mới vẫn bị loại: public đủ điểm ba lượt nhưng trung bình **13,231 giây / 120.341,67 token**, hồi quy 60 chỉ **59/60**, hồi quy 32 **31/32** trước khi yêu cầu dừng. Dừng thêm request, giữ các lượt đang chạy được quyết toán; các phần sau dừng được ghi chưa đánh giá. Không dùng câu trống do lệnh dừng làm bằng chứng chất lượng model. Mã lập lịch bị loại được giữ trong evidence, **đã khôi phục chính xác source v64**; không chỉnh tiếp theo lỗi của kiểm định mới.

## Chống overfitting và phạm vi kết luận

Các 254 câu hồi quy đã được dùng trong phát triển, không gọi là private hoặc kiểm định độc lập mới. Bộ 18 câu được đóng băng trước v51, gồm sáu workbook với ba họ mới (so sánh chênh lệch kép theo nhóm, tối ưu phân bổ tài nguyên liên tục, thời hạn theo lịch làm việc), giá trị và bố cục được ngẫu nhiên hóa; oracle độc lập. Chỉ mở lần đầu sau khi v64 vượt public và mọi bộ hồi quy. Không sửa prompt hoặc code theo lỗi của bộ này; từ đó bộ đã tiêu thụ. V65 bị dừng trước lượt hồi quy bộ 18 đó.

Không dùng ID, tên file hay đáp án chuẩn để chọn đáp án trong inference. ID chỉ liên kết đầu ra, tên file chỉ định workbook; qN chỉ định vị câu trong request chung. Oracle chỉ được dùng sau sinh kết quả. Không thể bảo đảm điểm private BTC từ số mẫu hiện có. Chưa xác nhận kết quả bằng Qwen3.7 Flash hoặc dữ liệu công khai đợt 2.

## Chạy đúng cấu hình đã chọn

Cấu hình gateway lấy từ `DEV_LLM_BASE_URL`, `DEV_LLM_API_KEY`, `DEV_LLM_MODEL=ag/gemini-3-flash` trong môi trường hoặc `.env`. Không đưa khóa/endpoint cá nhân vào mã hoặc gói nộp. Không tự đổi model.

```bash
python -m benchmarks.batched_cli \
  --input-dir /path/to/xlsx_files \
  --queries /path/to/queries.json \
  --output /path/to/submission.csv \
  --planning-profile parallel8 \
  --concurrency 4
```

Đường dẫn mới không cần CSV đáp án. Profile này dùng requested thinking low, adaptive high ở lượt HTTP thứ ba, temperature 1.0, tối đa 4.096 output cho kế hoạch chung và 2.048 cho lượt thường, tối đa ba lượt suy luận / năm HTTP attempts mỗi câu. Review candidate bật cho profile này; kiểm chứng nguồn mơ hồ vẫn có thể yêu cầu chọn lại độc lập. Gateway chấp nhận tham số không chứng minh cách nội bộ áp dụng chúng.

`run.py` giữ mặc định thi **Qwen3.7 Flash / OpenRouter** và giao diện hiện có. Benchmark Gemini không chứng minh tốc độ/độ đúng Qwen. CLI Qwen batching hiện chỉ có transport cùng workbook; **không giả vờ profile Gemini `parallel8` đã được xác nhận hoặc triển khai tương đương trên Qwen**. Không thay mặc định thi theo điểm Gemini. Đây là kết thúc tối ưu phát triển theo phạm vi Gemini và tiêu chí dừng mới, không phải xác nhận điểm chấm chính thức.

Gói source không chứa `.env`, khóa, workbook/đáp án thi, model, GPU/Colab dependencies, venv hoặc cache. Gói evidence riêng chứa dữ liệu/oracle để tái lập đánh giá; không dùng nó làm inference. Các test, lint/format và kiểm tra gói giải nén được ghi trong receipt bàn giao cuối.
