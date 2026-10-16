# Hỏi đáp trên workbook Excel

Giải pháp dùng `qwen/qwen3.7-flash` qua OpenRouter để chọn dữ liệu và sinh chương trình Python; phép tính chạy cục bộ trên giá trị thật trong workbook. Không đọc đáp án mẫu, không tra kết quả theo ID hoặc tên file.

## Cài đặt

Python **3.11 trở lên**, Linux hoặc macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Chỉ dùng `pip` trong venv. Các dependency trực tiếp được pin phiên bản. Để chạy kiểm thử:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
ruff check run.py evaluate.py src tests benchmarks
ruff format --check run.py evaluate.py src tests benchmarks
```

## Cấu hình và chạy

Đặt `OPENROUTER_API_KEY` trong môi trường hoặc `.env` cạnh `run.py`. Không đưa `.env` vào ZIP. Có thể sao chép `.env.example` rồi nhập khóa ở máy chạy.

```bash
export OPENROUTER_API_KEY="your-key"
python run.py --input-dir /path/to/xlsx_files --queries /path/to/queries.json --output /path/to/submission.csv
```

Các tham số cũ `--input-dir`, `--queries`, `--output`, `--api-key`, `--model` được giữ. Các giới hạn bổ sung:

| Tham số | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `--concurrency` | `2` | Tối đa hai câu đồng thời; có thể chọn `1` |
| `--deadline-seconds` | `2300` | Giới hạn toàn lượt chạy, kể cả retry; không cho tăng quá 2300 |
| `--total-budget` | `1.8` | Tổng ngân sách USD; nên giảm khi thử nghiệm |
| `--query-budget` | `0.09` | Trần mỗi câu, kể cả retry; không cho tăng quá 0.09 |
| `--reasoning-tokens` | `256` | Reasoning budget |
| `--max-tokens` | `2048` | Tổng output budget, bao gồm reasoning |
| `--trace` | cạnh CSV | Đường dẫn trace JSONL tùy chọn |

Chương trình lấy bảng giá công khai của model và dự trù theo giá cao nhất của các provider/tier. Mỗi request phải được giữ ngân sách trước khi gửi. Timeout hoặc thiếu usage giữ dự trù đó làm chi phí ước tính; không giả sử request lỗi miễn phí. Không tự chuyển model.

`submission.csv` luôn có hai cột `id,answer`, đúng thứ tự câu hỏi. Sau mỗi câu hoàn thành, CSV được ghi atomically. Cạnh CSV có `.trace.jsonl` và `.metrics.json` chứa code, ô đã đọc, kết quả thô, giả định, lỗi, token, chi phí, thời gian và RSS của tiến trình chính cùng workers. Trace không ghi khóa API. Nếu một câu thất bại, answer để trống, lỗi được ghi lại và CLI trả exit code 1; không invent đáp án để che lỗi. Không dùng lại câu trả lời cũ khi dữ liệu thay đổi.

## Cấu trúc và các quy tắc quan trọng

- Parser đọc XML workbook theo streaming, chỉ lưu ô có giá trị hoặc formula. Không cấp phát ma trận theo `max_row/max_column`, không cắt ở dòng 200. Giữ sheet, tọa độ, kiểu, format số, vùng gộp, indent/bold, hàng/cột ẩn, tiêu đề, đơn vị và footnote. Header hints là gợi ý có thể kiểm tra lại bằng ô gốc.
- `cell(sheet,address)` trả giá trị thật; ngày tháng là đối tượng datetime. `num` đọc số; `cells` đọc bảng hai chiều, `values` đọc vùng phẳng row-major, `age_days` tính ngày tuổi, `age_order` xếp dòng theo tuổi, `argmax` chọn tọa độ cực trị, `data_rows` lọc kiểu và `find_rows` tìm dòng theo nhãn; `label` kế thừa nhãn chuỗi trong vùng gộp; `rows` trả số dòng có dữ liệu. Ô số gộp chỉ có giá trị ở ô nguồn.
- LLM trả JSON được kiểm tra bằng Pydantic: code, result_variable, format, assumptions, needs_verification. Biến kết quả được khai báo rõ; chấp nhận result/answer và result_* ở câu lệnh cuối, không lấy biến trung gian tùy ý. Code phải đọc workbook và kết quả phải phụ thuộc vào phép đọc; không chấp nhận biến trung gian tùy ý làm đáp án. Các kiểm tra mâu thuẫn tiêu đề và ngày tham chiếu không dùng nhãn đáp án. Phạm vi trung bình across-all và tổng có parent được hoàn thiện bằng code sinh từ tọa độ thật khi chỉ có một cách chọn rõ ràng; trace ghi contract_repair.
- Worker dùng bộ thông dịch AST, không dùng `exec/eval`. Chỉ hỗ trợ một tập con Python cho tính toán; không import hệ thống, introspection, đọc file hay network. Môi trường worker không nhận API key. Timeout mặc định 5 giây, RSS tối đa 256 MiB; Linux có thêm RLIMIT_AS/CPU. Đây không phải một sandbox OS cho việc chạy Python tùy ý.
- Tối đa ba lượt sinh/kiểm chứng chương trình và năm lần thử HTTP mỗi câu. 429, timeout và 5xx có backoff. Kiểm chứng bổ sung khi có mâu thuẫn hoặc model đánh dấu mơ hồ; code chạy được không bảo đảm ngữ nghĩa đúng.
- Tuổi dùng ngày tham chiếu trong câu hỏi. Khi thiếu và chỉ có cặp Birth/Admission, dùng Admission. Với trung bình trên mọi cột được trình bày, bao gồm các cột Total được trình bày riêng; với cộng nhóm, không cộng cả parent và children. Ưu tiên tổng đã công bố khi có sai số làm tròn.
- Format tuân thủ số lượng, kiểu, precision và separator trong câu hỏi; không xóa dấu câu cuối tên riêng hoặc trích một số từ thông báo lỗi.

## Đánh giá và benchmark

```bash
python evaluate.py submission.csv /path/to/reference_answers.csv
```

Evaluator so khớp nguyên văn trường answer sau khi đọc CSV, không đổi hoa/thường hay strip đáp án. Thiếu/thừa/trùng ID hoặc sai cột là lỗi.

`python -m benchmarks.fixtures` tạo workbook tổng hợp cùng oracle độc lập trong `reports/holdout/`: sheet/file đổi tên, bảng dịch qua dòng 300, cột đảo vị trí, bảng nhiễu, tuổi theo ngày sự kiện, phần trăm, ngày ISO, subtotal và formula. Đây là dữ liệu kiểm thử, không được tải vào inference.

`python -m benchmarks.compare --report-dir reports/new_run --seed 51037` so sánh cấu hình 256/2048 và 1024/4096 trên tuning; khóa cấu hình trước khi đánh giá workbook công khai dành riêng và bộ tổng hợp. Kết quả, source hash và accounting được lưu dưới `reports/controlled/`. Lệnh từ chối ghi đè benchmark cũ. Ngân sách phát triển tổng tối đa 0.50 USD, bao gồm lượt khảo sát trước đó được ghi trong reports.

Xem `reports/BENCHMARK.md` trong workspace phát triển để biết kết quả đo thực tế. Dữ liệu public đợt 2 chưa nằm trong dự án; khi có, chạy lại bằng đường dẫn mới với cấu hình đã khóa và ghi vào một thư mục kết quả mới. Độ chính xác public/synthetic không phải cam kết điểm private.

## Giới hạn được báo rõ

Formula có cache được ưu tiên. Formula chưa có cache hỗ trợ số học, tham chiếu cùng sheet và SUM/AVERAGE/MIN/MAX/COUNT trên vùng; các công thức khác, cross-sheet chưa cache hoặc shared formula chưa cache phải được tính bằng Excel trước, hoặc sẽ báo lỗi, không biến thành 0. Không có engine Excel đầy đủ.

Mỗi workbook sparse tối đa 64 MiB theo dự trù, cache tổng 128 MiB; worker payload tối đa 64 MiB. Input vượt giới hạn bộ nhớ hoặc context được báo rõ và không bị cắt âm thầm. Resource monitor lấy mẫu RSS mỗi 20 ms và dừng workers khi tổng vượt 800 MiB; cần đo lại trên máy BTC để xác nhận giới hạn tại môi trường chấm. Dữ liệu cực lớn hoặc semantics mơ hồ chưa thể bảo đảm trả lời đúng.

## Đóng gói

```bash
python -m benchmarks.package_submission
```

Tạo `dist/table_qa_submission.zip` từ danh sách file cho phép và kiểm tra dung lượng/nội dung. Không đưa `.env`, dữ liệu, đáp án, reports, `.venv`, cache hoặc đường dẫn máy cá nhân vào archive. Có thể giải nén ZIP vào thư mục mới, cài requirements và chạy CLI bằng đường dẫn dữ liệu bất kỳ.
