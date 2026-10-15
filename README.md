# Hỏi đáp trên workbook Excel

Giải pháp dùng `qwen/qwen3.7-flash` qua OpenRouter để chọn dữ liệu và sinh chương trình Python; phép tính chạy cục bộ trên giá trị thật trong workbook. Không đọc đáp án mẫu, không tra kết quả theo ID hoặc tên file.

Đã chốt giai đoạn phát triển Gemini tại **v64 / `parallel8`**: public **20/20 cả ba lượt**, **254/254** hồi quy mở rộng và **18/18** kiểm định mới (baseline 17/18). Public trung bình **11,017 giây / 93.740 token**, giảm **57,44% thời gian / 56,77% token so với baseline cùng đợt**; RAM local đỉnh **130,06 MiB**. Trên kiểm định mới, độ đúng tăng nhưng thời gian tăng 49,12%; không tuyên bố mọi benchmark đều giảm 50%. Không đạt giảm 50% so với mốc nhanh nhất lịch sử. Các thử nghiệm JSON và lập lịch sửa song song bị loại; đã khôi phục đúng source v64 và dừng theo tiêu chí thực dụng mới của người dùng.

Xem [bản chọn và báo cáo bàn giao](docs/FINAL_SELECTION.md), [toàn bộ lịch sử benchmark](docs/CURRENT_BENCHMARK.md). **Đây là kết quả Gemini; Qwen/private BTC chưa được xác nhận.** `run.py` giữ Qwen/OpenRouter. Để chạy đúng bản phát triển đã chọn, thêm `--planning-profile parallel8 --concurrency 4` vào lệnh `benchmarks.batched_cli` bên dưới.

Xem [báo cáo giai đoạn đầu](docs/BENCHMARK.md): Gemini sinh mới đạt public 20/20 và holdout độc lập 23/24; candidate chưa được xác nhận bằng Qwen. Các công cụ Colab được giữ để tham khảo lịch sử, không thuộc luồng chạy hiện tại hoặc gói thi.

[Kiểm tra độ ổn định và chuyển giao](docs/TRANSFER.md) ghi riêng các vòng mới, gồm cả lượt thất bại. Mã hiện tại dùng biểu diễn gọn cho cả request sửa lỗi, hỗ trợ ngày ISO và phạm vi hàng rõ ràng, kiểm tra nguồn ngày/đơn vị/nhãn. CLI batching Qwen là tùy chọn chưa có bằng chứng Qwen sinh mới; `run.py` giữ entrypoint thông thường.

Vòng tối ưu v3/v4 dùng chung một lượt lập chương trình cho các câu hỏi cùng workbook; xem [benchmark hiệu suất lịch sử](docs/EFFICIENCY.md). Candidate v4/Gemini đạt public 20/20 trong ba lượt sinh mới, giảm trung bình 69% tổng thời gian và 55% token; challenge độc lập mới đạt 32/32 so với baseline 31/32. V3 trước đó đạt 60/60 trên bộ độc lập khác. Các số này gắn với snapshot v3/v4, không thay cho đánh giá mã mới. Mỗi chương trình vẫn chạy và được kiểm chứng riêng. CLI phát triển nhận đường dẫn mới và không cần đáp án chuẩn:

```bash
python -m benchmarks.batched_cli --input-dir /path/to/xlsx_files --queries /path/to/queries.json --output /path/to/dev_submission.csv
```

CLI này chỉ dùng Gemini gateway từ `DEV_LLM_*`; giới hạn một batch 30 phút/200 HTTP attempts/2 triệu token. `run.py` vẫn là entrypoint Qwen/OpenRouter; candidate batching chưa được xác nhận bằng Qwen và chưa thay mặc định thi.

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
| `--concurrency` | `2` | Chọn `1`, `2` hoặc thử `4`; chế độ `4` giảm giới hạn mỗi worker xuống 128 MiB |
| `--compact-prompt` | tắt | Cách ghi ô gọn, giữ mọi giá trị/kiểu/format/tọa độ; cần benchmark live trước khi bật mặc định |
| `--adaptive-reasoning` | tắt | Lượt sửa lỗi/kiểm chứng tăng tới reasoning 1024/output 4096, vẫn cùng trần chi phí và số lượt |
| `--deadline-seconds` | `2300` | Giới hạn toàn lượt chạy, kể cả retry; không cho tăng quá 2300 |
| `--total-budget` | `1.8` | Tổng ngân sách USD; nên giảm khi thử nghiệm |
| `--query-budget` | `0.09` | Trần mỗi câu, kể cả retry; không cho tăng quá 0.09 |
| `--reasoning-tokens` | `256` | Reasoning budget |
| `--max-tokens` | `2048` | Tổng output budget, bao gồm reasoning |
| `--trace` | cạnh CSV | Đường dẫn trace JSONL tùy chọn |

Chương trình lấy bảng giá công khai của model và dự trù theo giá cao nhất của các provider/tier. Mỗi request phải được giữ ngân sách trước khi gửi. Timeout hoặc thiếu usage giữ dự trù đó làm chi phí ước tính; không giả sử request lỗi miễn phí. Không tự chuyển model.

`submission.csv` luôn có hai cột `id,answer`, đúng thứ tự câu hỏi. Sau mỗi câu hoàn thành, CSV được ghi atomically. Cạnh CSV có `.trace.jsonl` và `.metrics.json` chứa code, ô đã đọc, kết quả thô, giả định, lỗi, token, chi phí, thời gian và RSS của tiến trình chính cùng workers. Trace không ghi khóa API. Nếu một câu thất bại, answer để trống, lỗi được ghi lại và CLI trả exit code 1; không invent đáp án để che lỗi. Không dùng lại câu trả lời cũ khi dữ liệu thay đổi.

## Cấu trúc và các quy tắc quan trọng

- Parser đọc XML workbook theo streaming, chỉ lưu ô có giá trị hoặc formula. Không cấp phát ma trận theo `max_row/max_column`, không cắt ở dòng 200. Giữ sheet, tọa độ, kiểu, format số, vùng gộp, indent/bold, hàng/cột ẩn, tiêu đề, đơn vị và footnote. Có header hints theo vùng bảng; các vùng là gợi ý, không chứng minh chắc chắn cấu trúc và phải kiểm tra lại bằng ô gốc. Quá nhiều vùng sparse thì bỏ hints, vẫn giữ toàn bộ ô.
- `cell(sheet,address)` trả giá trị thật; ngày tháng là đối tượng datetime. `num` đọc số; `cells` đọc bảng hai chiều, `values` đọc vùng phẳng row-major, `age_days` tính ngày tuổi, `age_order` xếp dòng theo tuổi, `argmax` chọn tọa độ cực trị, `data_rows` lọc kiểu và `find_rows` tìm dòng theo nhãn; `label` kế thừa nhãn chuỗi trong vùng gộp; `rows` trả số dòng có dữ liệu. Ô số gộp chỉ có giá trị ở ô nguồn.
- `data_rows(sheet, {'A':'string','B':'number'})` lọc các cột có kiểu khác nhau, không buộc cột tên phải là số. `argmax(..., absolute=True)` so trị tuyệt đối. Guard `raise ValueError/TypeError/RuntimeError` được hỗ trợ; bắt/nuốt exception bằng try/except vẫn bị cấm.
- LLM trả JSON được kiểm tra bằng Pydantic: code, result_variable, format, assumptions, needs_verification. Biến kết quả được khai báo rõ; chấp nhận result/answer và result_* ở câu lệnh cuối, không lấy biến trung gian tùy ý. Code phải đọc workbook và kết quả phải phụ thuộc vào phép đọc; không chấp nhận biến trung gian tùy ý làm đáp án. Các kiểm tra mâu thuẫn tiêu đề và ngày tham chiếu không dùng nhãn đáp án. Phạm vi trung bình across-all và tổng có parent được hoàn thiện bằng code sinh từ tọa độ thật khi chỉ có một cách chọn rõ ràng; trace ghi contract_repair.
- Worker dùng bộ thông dịch AST, không dùng `exec/eval`. Chỉ hỗ trợ một tập con Python cho tính toán; không import hệ thống, introspection, đọc file hay network. Môi trường worker không nhận API key. Timeout mặc định 5 giây, RSS tối đa 256 MiB; Linux có thêm RLIMIT_AS/CPU. Đây không phải một sandbox OS cho việc chạy Python tùy ý.
- Tối đa ba lượt sinh/kiểm chứng chương trình và năm lần thử HTTP mỗi câu. 429, timeout và 5xx có backoff. Kiểm chứng bổ sung khi có mâu thuẫn, nhãn trùng chưa có bằng chứng phân biệt nhóm hoặc model đánh dấu mơ hồ; lượt kiểm chứng chọn lại nguồn độc lập, không nhận code/đáp án đầu để tránh bám theo lựa chọn ban đầu. JSON có thể khai báo `selection` gồm sheet/range/operation/unit; range được đối chiếu với các ô thực sự đã đọc. Code chạy được không bảo đảm ngữ nghĩa đúng.
- Tuổi dùng ngày tham chiếu trong câu hỏi. Khi thiếu và chỉ có cặp Birth/Admission, dùng Admission. Trung bình chỉ được tự hoàn thiện khi có một phạm vi bảng/nhánh tiêu đề rõ ràng; không tự thêm cột mã số, mẫu số, trọng số hoặc bảng cạnh bên. Trong phạm vi đó, câu hỏi lấy trung bình mọi mức được trình bày bao gồm các Total riêng, trừ khi hỏi leaf/weighted. Với cộng nhóm, không cộng cả parent và children. Ưu tiên tổng đã công bố khi có sai số làm tròn.
- Format tuân thủ số lượng, kiểu, precision và separator trong câu hỏi; không xóa dấu câu cuối tên riêng hoặc trích một số từ thông báo lỗi.

## Đánh giá và benchmark

```bash
python evaluate.py submission.csv /path/to/reference_answers.csv
```

Evaluator so khớp nguyên văn trường answer sau khi đọc CSV, không đổi hoa/thường hay strip đáp án. Thiếu/thừa/trùng ID hoặc sai cột là lỗi.

`python -m benchmarks.fixtures` tạo workbook tổng hợp cùng oracle độc lập trong `reports/holdout/`: sheet/file đổi tên, bảng dịch qua dòng 300, cột đảo vị trí, bảng nhiễu, tuổi theo ngày sự kiện, phần trăm, ngày ISO, subtotal và formula. Đây là dữ liệu kiểm thử, không được tải vào inference.

`python -m benchmarks.compare --report-dir reports/new_run --seed 51037` so sánh cấu hình 256/2048 và 1024/4096 trên tuning; khóa cấu hình trước khi đánh giá workbook công khai dành riêng và bộ tổng hợp. Kết quả, source hash và accounting được lưu dưới `reports/controlled/`. Lệnh từ chối ghi đè benchmark cũ. Ngân sách phát triển tổng tối đa 0.50 USD, bao gồm lượt khảo sát trước đó được ghi trong reports.

Benchmark dùng sổ `reports/optimization/development_budget.json`, giữ trước ngân sách mỗi lượt và khóa để tránh hai experiment ghi đè/cùng tiêu. Khi giải nén ZIP sang nơi khác, muốn tiếp tục cùng đợt phát triển phải mang theo sổ này; không tạo sổ mới để bỏ qua chi phí cũ. `--tuning-queries` phải thuộc đúng bộ hiện tại và không chia cùng workbook/họ cấu trúc giữa tuning/holdout. Trường `family` tùy chọn chỉ dùng khi phân chia benchmark; các biến thể cùng nguồn phải có cùng family. Bộ sinh synthetic cũ là validation, không phải private holdout độc lập.

Chạy một lượt live có kế toán và lưu bằng chứng:

```bash
python -m benchmarks.experiment --report-dir reports/experiment_new --limit 0.03
```

Thêm `--compact-prompt`, `--adaptive-reasoning` hoặc `--concurrency 4` để thử từng thay đổi. Chọn bằng Exact Match trước thời gian rồi token; các tùy chọn chưa được live xác nhận giữ tắt mặc định. HTTP 402 có thể do số dư tài khoản dù API key chưa chạm trần; xem `GET /api/v1/key` và `GET /api/v1/credits`, không đưa token vào log.

Trong phát triển có thể đặt `BAZAARLINK_API_KEY` trong `.env` rồi chạy `python -m benchmarks.experiment --provider bazaarlink --report-dir reports/bazaar_new --limit 0.03 --concurrency 1`. Harness chỉ chấp nhận đúng `qwen/qwen3.7-flash` hoặc alias được catalog công bố, dùng giá cao nhất trong mọi tier để giữ ngân sách và ghi provider vào báo cáo. `--baseline` chạy solver/prompt/wire từ snapshot trước tối ưu khi snapshot có trong workspace. Endpoint tạm chỉ áp dụng trong harness; `run.py` vẫn dùng OpenRouter và không dùng khóa BazaarLink. Không so trực tiếp thời gian/chi phí giữa hai provider. Free tier có quota riêng; HTTP 429 với `Retry-After` vượt deadline sẽ dừng request mới toàn lượt. Không cộng phần thiếu do quota vào kết luận về độ chính xác model.

Để thử pipeline bằng model miễn phí trước khi xác nhận bằng Qwen, dùng khóa OpenRouter hiện có:

```bash
python -m benchmarks.experiment --provider openrouter-free --report-dir reports/free_dev_new --concurrency 1 --limit 0.01
```

Chế độ này chọn `nvidia/nemotron-3-super-120b-a12b:free`, kiểm tra lại catalog/giá và quota tài khoản trước khi chạy, gửi mỗi HTTP attempt cách nhau tối thiểu 3,1 giây, giới hạn tổng attempts theo quota còn lại. Routing chỉ chấp nhận giá prompt/completion/request/image bằng 0; không chuyển sang model trả phí. Có thể chọn `--development-model <id:free>` nếu catalog xác nhận miễn phí và hỗ trợ các tham số cần thiết. Model miễn phí có thể bị giới hạn theo ngày, quá tải hoặc bị gỡ; tạo thêm khóa không tăng quota tài khoản. Xem [giới hạn OpenRouter](https://openrouter.ai/docs/api_reference/limits). Request ngoài harness hoặc tiến trình khác vẫn có thể tiêu chung quota.

Kết quả được đánh dấu `judge_model_benchmark=false`, chỉ dùng tìm lỗi parse/JSON/code/helper/format và kiểm tra tích hợp. Độ chính xác, thời gian, token của model thay thế không đại diện cho Qwen3.7 Flash; không khóa cấu hình thi dựa riêng trên kết quả này. Chạy tests và replay offline khi sửa mã, dùng model miễn phí cho thử nghiệm tích hợp, sau đó mới dùng Qwen cho kiểm tra chấp nhận. `--limit` là khoản giữ trước tạm trong sổ ngân sách; model được xác nhận miễn phí có dự trù 0 và khoản giữ được hoàn lại khi kết thúc. `run.py` tiếp tục mặc định Qwen qua OpenRouter.

Xem `reports/BENCHMARK.md` và `reports/optimization/REPORT.md` trong workspace phát triển để biết kết quả đo thực tế. `python -m benchmarks.offline` cần baseline snapshot và trace trong workspace phát triển, không nằm trong ZIP. Dữ liệu public đợt 2 chưa nằm trong dự án; khi có, chạy lại bằng đường dẫn mới với cấu hình đã khóa và ghi vào một thư mục kết quả mới. Độ chính xác public/synthetic không phải cam kết điểm private.

## Phát triển với Gemini qua gateway

Đặt `DEV_LLM_BASE_URL`, `DEV_LLM_API_KEY`, `DEV_LLM_MODEL` trong môi trường hoặc `.env`; không dùng khóa OpenRouter thay cho khóa gateway. Model phát triển được cấu hình riêng; `run.py` tiếp tục dùng Qwen qua OpenRouter. Luồng Colab/T4 đã dừng, công cụ Colab và dependency GPU không nằm trong ZIP thi.

```bash
python -m benchmarks.gateway_probe --root reports/gateway_new
python -m benchmarks.experiment --provider gateway --report-dir reports/gateway_known_validation --compact-prompt --helper-contract --thinking minimal
```

Probe kiểm tra JSON, model trả về và usage; thử `low` trước, chỉ thử lại payload cơ bản một lần khi bị từ chối 400/422. Gateway có thể trả SSE dù yêu cầu JSON; bộ đọc ghép nội dung và kiểm tra kết thúc stream. Tham số thinking được chấp nhận không chứng minh gateway áp dụng đúng thinking level. Không tự đổi model hoặc chuyển sang API trả phí.

`benchmarks.gateway_runner` thực hiện hai đợt cố định: baseline/sàng lọc và validation/holdout. Mỗi đợt tối đa 30 phút, 200 HTTP attempts và 2 triệu token; checkpoint gắn hash dữ liệu, source, model, prompt và cấu hình. Không tái sử dụng checkpoint khác hash, không khởi tạo lại hạn mức đã hết. Chi phí ước tính bằng 0 dựa trên xác nhận của người dùng; `usage.cost` được ghi riêng, chi phí dương sẽ dừng batch. Request thiếu usage giữ dự toán token bảo thủ; lỗi mạng giữ reservation và được báo là chưa biết usage, không phải 0 token.

Bộ holdout trong workspace đã được đánh giá. Không chạy lại rồi gọi kết quả đó là holdout độc lập; runner lưu receipt và chặn dùng lại nó trong một đợt lựa chọn mới. `reports/optimization/gemini_gateway/REPORT.md` tách kết quả sinh mới, replay và bước Qwen còn thiếu. Không bật cấu hình C làm mặc định thi khi chưa qua Qwen signoff.

Executor có cờ Python `iterator_helpers=True` cho thử nghiệm `next`/`iter` và generator lazy trong môi trường giới hạn. Cờ mặc định **tắt**, không được bật bằng CLI nộp thi, chưa xác nhận bằng Qwen. Kết quả replay của cờ này được ghi riêng và không thay điểm holdout đã khóa.

## Candidate tăng độ chính xác

Candidate mới giữ đầy đủ system prompt, thêm hợp đồng dữ liệu/đơn vị và kiểm chứng tổng hợp/cực trị. Bản rút gọn không được chọn vì validation còn lỗi dùng helper. Điểm Gemini và kiểm tra dịch bảng/đổi tên được ghi ở `reports/optimization/precision_v2/REPORT.md`; không dùng chúng thay bằng chứng Qwen.

Có CLI riêng để chạy candidate với **đúng Qwen qua OpenRouter**, không dùng gateway phát triển:

```bash
python -m benchmarks.precision_submission --input-dir /path/to/xlsx_files --queries /path/to/queries.json --output /path/to/candidate_submission.csv
```

Đánh giá độc lập của phiên bản đã khóa được giữ nguyên trong `frozen_proof/`; sửa hợp đồng dấu sau đó chỉ được kiểm tra bằng regression/replay và có lock riêng, không đổi tên kết quả thành holdout mới. ZIP candidate là `dist/table_qa_precision_candidate.zip`; ZIP nộp trước tối ưu được giữ riêng.

CLI này bật helper iterator, giữ trần 0,09 USD/câu, deadline 2.300 giây và cấu hình RAM của scheduler. Khóa lấy từ `OPENROUTER_API_KEY` hoặc `--api-key`; không tự đổi model. `python run.py ...` vẫn là entrypoint thông thường. Candidate cần Qwen signoff trước khi chọn làm cấu hình nộp chính thức; khi có credit, chạy `python -m benchmarks.qwen_signoff --root reports/optimization/precision_v2/post_holdout_candidate` trong workspace phát triển. Signoff áp dụng EM → thời gian → token và không chấp nhận suy giảm trên từng bộ kiểm tra.

Kiểm tra evidence phân biệt `lookup_probe` (các nhãn ứng viên của phép tìm kiếm) với ô số/nhãn thực sự được đọc để tính/đưa ra đáp án. Các phép đọc số vẫn phải nằm trong vùng được khai báo. Sửa tổng và cực trị chỉ thực hiện khi phạm vi đủ rõ; trace giữ chương trình gốc lẫn chương trình kiểm chứng bằng tọa độ thật. Không có luật chọn đáp án theo ID, đường dẫn hoặc bảng đáp án.

## Giới hạn được báo rõ

Formula có cache được ưu tiên. Formula chưa có cache hỗ trợ số học cơ bản, tham chiếu cùng/khác sheet (cả tên có khoảng trắng/dấu nháy), absolute references và SUM/AVERAGE/MIN/MAX/COUNT trên vùng hoặc nhiều đối số. Các công thức khác hoặc shared formula chưa cache phải được tính bằng Excel trước, hoặc sẽ báo lỗi, không biến thành 0. `argmax` không bỏ qua lỗi Excel/công thức thiếu cache; `num` từ chối chuỗi dấu phân cách mơ hồ như `1,2`. Không có engine Excel đầy đủ.

Mỗi workbook sparse tối đa 64 MiB theo dự trù, cache tổng 128 MiB; worker payload tối đa 64 MiB. Khi văn bản workbook vượt 800.000 byte UTF-8, chương trình gửi một view có danh mục sheet và các ô phù hợp, ghi rõ số ô chưa hiển thị. Toàn bộ dữ liệu vẫn ở backend; model có thể yêu cầu `request_regions` để xem nguyên vùng trước khi sinh code. Việc xem thêm dùng chung trần ba lượt suy luận, năm HTTP attempts và chi phí. Vùng quá lớn bị từ chối rõ ràng để yêu cầu hẹp hơn, không trả dữ liệu vùng bị cắt dở. Input vượt giới hạn bộ nhớ vẫn được báo lỗi. Resource monitor lấy mẫu RSS mỗi 20 ms và dừng workers khi tổng vượt 800 MiB; cần đo lại trên máy BTC để xác nhận giới hạn tại môi trường chấm. Dữ liệu cực lớn hoặc semantics mơ hồ chưa thể bảo đảm trả lời đúng.

## Đóng gói

```bash
python -m benchmarks.package_submission
```

Tạo `dist/table_qa_submission.zip` từ danh sách file cho phép và kiểm tra dung lượng/nội dung. Không đưa `.env`, dữ liệu, đáp án, reports, `.venv`, cache hoặc đường dẫn máy cá nhân vào archive. Có thể giải nén ZIP vào thư mục mới, cài requirements và chạy CLI bằng đường dẫn dữ liệu bất kỳ.
