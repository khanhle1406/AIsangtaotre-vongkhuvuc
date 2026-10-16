# Báo cáo triển khai và benchmark

**Cập nhật 15/10:** Có đợt tối ưu tiếp theo và ZIP mới. Bảng dưới là kết quả live lịch sử; xem [báo cáo tối ưu](optimization/REPORT.md) cho sửa đổi mới, 109 test, regression offline 4/16 → 16/16, OpenRouter HTTP 402 và quota miễn phí của API tạm. Không coi điểm replay hoặc lượt dở do quota là benchmark LLM trước/sau hoàn chỉnh.

Giải pháp hiện đọc dữ liệu thật qua helper có kiểu và bộ thông dịch AST; không tra đáp án theo ID/tên file, không đọc sample_submission.csv trong luồng chạy. Mặc định Qwen3.7 Flash, reasoning 256/output 2048, concurrency 2.

## Kết quả thực tế

Baseline là tệp submission lưu sẵn trước sửa: **17/20**, không phải baseline LLM được chạy lại cùng thời điểm. Đánh giá dưới đây dùng Exact Match nguyên văn, kiểm tra ID và cột CSV.

| Bộ kiểm tra | Exact Match | Giây toàn lượt | USD toàn lượt | RSS tổng đỉnh (MiB) |
| --- | ---: | ---: | ---: | ---: |
| Public native | 20/20 | 103.06 | 0.00630687 | 80.55 |
| ZIP relocated | 20/20 | 89.24 | 0.00557741 | 84.61 |
| Synthetic seed 94049 | 24/24 | 66.30 | 0.00208188 | 78.28 |

62 test trước lỗi tài khoản và **63 test cuối** đạt; Ruff check và format check đạt. Replay các chương trình được model sinh trong lượt ZIP trên mã hiện tại đạt **20/20**, không gọi API. Các lượt trực tiếp trong bảng đo phiên bản trước thay đổi cuối về ưu tiên ngày tham chiếu và dừng khi tài khoản API lỗi; thay đổi cuối được kiểm thử và replay, không gọi LLM lại thành công.

Lượt ZIP đã giải nén vào thư mục mới, chạy từ cwd khác, đổi tên mọi workbook và ID, dùng đường dẫn dữ liệu ngoài thư mục code và trả exit code 0. RSS lấy mẫu mỗi 20 ms, cộng tiến trình chính và workers. Số liệu này đo trên macOS/Python 3.13, chưa chứng minh tài nguyên trên máy Linux của BTC. Docker daemon không khả dụng.

## Thay đổi chính

- Không còn cắt 200 dòng hoặc tạo grid theo vùng định dạng. Giữ tọa độ, kiểu, merged ranges, formula/cache, number format, sheet, indent/bold, hidden rows/columns, title/unit/footnote.
- Header hints và kiểm tra scope dựa trên dữ liệu. Ngày tham chiếu được nêu rõ trong câu hỏi ưu tiên hơn Admission; chỉ dùng Admission làm mặc định khi thích hợp. Không ép string dates thành datetime.
- Helper typed đọc/lọc/sắp xếp dữ liệu; chỉ nhận biến kết quả được khai báo. Kết quả phải phụ thuộc vào workbook; không nhận scratch tùy ý. Quy tắc ALL rõ ràng được hoàn thiện từ tọa độ trên metric row đã chọn, hoặc parent total duy nhất, và ghi contract_repair.
- Worker riêng, môi trường sạch, không exec/eval, AST/method allowlist, timeout 5 giây, RSS 256 MiB; Linux có thêm CPU/address-space limits. Không truyền khóa API vào worker.
- Ngân sách giữ trước mỗi request, tối đa ba lượt suy luận/năm HTTP attempts, retry/backoff, fatal account errors dừng request mới, deadline toàn lượt, CSV atomic/checkpoint và trace/metrics.
- Formatter không lấy số từ chuỗi lỗi, giữ dấu câu trong tên, xác minh cardinality/precision/options. SyntaxError được sửa thay vì thoát khỏi toàn lượt.

## Ngân sách và giới hạn bằng chứng

Ngân sách phát triển được cho phép: **0.50 USD**. Tổng accounting bảo thủ: **0.233573 USD**. Số này là cận trên, không phải tổng billing thực: có **0.05 USD** giữ cho lượt debug bị gián đoạn và cận trên cho các request lỗi/thiếu usage. Lượt cuối trả **HTTP 402**; không suy diễn số dư tài khoản từ mã lỗi và đã dừng mọi thử API tiếp theo. Không cần thay khóa API trong source; cấu hình ở môi trường hoặc .env.

Cấu hình 256/2048 được chọn theo tuning rồi khóa trước vòng validation. Các vòng cũ phát hiện lỗi và đã được dùng để sửa, nên cả public lẫn các họ synthetic đã được quan sát. Bộ seed mới kiểm tra thay số, đổi tên/cột, dịch bảng quá dòng 300, bảng nhiễu, hai bảng/sheet, parent total, percent/date/formula; **24/24 không phải cam kết độ chính xác private**. Public đợt 2 chưa có trong workspace; phải đánh giá ngoài mẫu khi BTC cung cấp.

Formula cached được ưu tiên; recalculation chỉ hỗ trợ một tập con số học/cùng-sheet/common range aggregates. Vượt bộ nhớ/context hoặc công thức ngoài tập hỗ trợ được báo rõ, không biến thành 0 hay cắt dữ liệu âm thầm. Không có chứng nhận sandbox OS hoặc bảo đảm tuyệt đối ngữ nghĩa từ kiểm tra AST.

## Bàn giao

ZIP: `dist/table_qa_submission.zip`, **52,193 bytes**, 16 file. Kiểm tra toàn bộ nội dung ZIP khớp workspace và không chứa .env, dữ liệu, đáp án, reports, venv/cache. README có lệnh cài/chạy/test/benchmark, hỗ trợ input paths mới. submission.csv ở root là đầu ra public 20/20 của lượt release_candidate; giữ baseline riêng tại reports/baseline_submission.csv.

Source SHA-256: `cd23a2f12c9430d2124d4c34f2f379ab2bb6b563bbf865c7224db5a97bf52b1b`

ZIP SHA-256: `53f1a067d539adfbb9a45234741de56d48b3b70c2a21a9622e82b358f4200320`
