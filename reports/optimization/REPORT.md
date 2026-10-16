# Kết quả tối ưu và phần còn cần benchmark live

Bổ sung: đã tích hợp và đo model miễn phí cho phát triển; xem [FREE_MODEL.md](FREE_MODEL.md) và `free_dev_release.json` cho bằng chứng/ZIP hiện tại. Các số đo 109 test và hash trong manifest cũ bên dưới thuộc bản bàn giao trước bổ sung này.

Ngày thực hiện: 15/10/2026. Đã triển khai các sửa đổi và kiểm chứng offline; chưa thể kết luận đã tối ưu điểm private hoặc hoàn tất nghiệm thu live/Linux.

## Kết quả đo trước/sau

| Phép đo | Trước | Sau | Ý nghĩa và giới hạn |
| --- | ---: | ---: | --- |
| Bộ phản ví dụ về scope/formula | 4/16 | 16/16 | Cùng dữ liệu có kiểu và chương trình đầu vào, so sánh executor + sửa phạm vi. Bộ được thiết kế để tái hiện lỗi đã biết; không phải tỷ lệ chính xác LLM/private. |
| Replay chương trình public từng sinh thực tế | 20/20 | 20/20 | Mã mới vẫn cho đáp án đúng và vượt kiểm tra cấu trúc; không sinh lại chương trình qua LLM. |
| Unit/regression tests | 63 | 109 | Test mới bao gồm cách đo, ngân sách, bảng/nhóm, công thức, context mở rộng, transport tạm và quota/retry. |
| Văn bản prompt của 20 câu public | 363.792 byte | 274.614 byte khi bật compact | Giảm **24,51% byte UTF-8**, gồm system prompt và câu hỏi. Chưa phải token do API tính hoặc thời gian LLM. |
| Văn bản prompt với mặc định full | 363.792 byte | 387.982 byte | Tăng 6,65% do bổ sung hướng dẫn và cấu trúc. Compact giữ tắt cho đến khi có so sánh live không giảm Exact Match. |
| Parse + wire + render 10 workbook, median 5 lượt luân phiên | khoảng 0,04 giây | khoảng 0,05 giây | Có overhead phân tích vùng bảng; số đo từng lượt nằm trong offline.json. Không tuyên bố cải thiện thời gian toàn hệ thống. |

Ruff check và format check đạt. Số đo chi tiết, từng ca và hash runtime nằm trong `offline.json`. Bộ 16 ca dùng số sinh độc lập; không dùng đáp án public để tạo đáp án suy luận. Bốn ca control vẫn đúng ở cả hai bản.

Mốc live thành công trước đợt tối ưu này là 20/20 public, lượt ZIP 89,24 giây/20 câu, 198.156 token và 0,0055774 USD. Đó là bằng chứng lịch sử; không gán các con số này cho phiên bản vừa sửa.

## Những thay đổi tạo ra cải thiện

1. **Scope:** bổ sung vùng bảng/header riêng, hỗ trợ bảng cạnh nhau hoặc theo chiều dọc và bảng chỉ có một cột số. Trung bình không còn tự thêm mọi ô số cùng hàng khi khác nhánh North/South, khác bảng, mã số, mẫu số hoặc trọng số chưa được hỏi. Năm nằm trong nhãn như “FY 2025” được đối chiếu bằng nội dung nhãn. Khi chưa đủ bằng chứng, giữ kết quả để kiểm chứng thay vì ép một cách chọn.
2. **Kiểm chứng:** hệ thống tự phát hiện scope mơ hồ và nhãn lặp, không chỉ tin cờ của model. Lượt kiểm chứng chọn lại nguồn từ câu hỏi/workbook, không nhận đáp án và code trước. Phần dữ liệu được yêu cầu xem thêm vẫn được giữ khi kiểm chứng. Câu hỏi không nêu subgroup có bằng chứng từ section Total/All được giữ đường nhanh; không tự thêm lượt chỉ vì nhãn xuất hiện trong subgroup khác. Trace lưu tín hiệu kiểm chứng và các vùng nguồn được khai báo.
3. **Không kiểm tra nhầm nguồn:** kiểm tra tên thực thể chỉ xét sheet/vùng đã được đọc. Nhãn Total ở bảng bên trái không còn biến dữ liệu bảng bên phải thành parent. Kiểm tra tiêu đề trích dẫn dùng nguồn đã chọn thay vì tiêu đề toàn sheet.
4. **Tính toán:** công thức chưa cache hỗ trợ thêm tham chiếu khác sheet, absolute reference, tên sheet có khoảng trắng/dấu nháy và nhiều đối số trong SUM/AVERAGE/MIN/MAX/COUNT. Vẫn dùng AST giới hạn, không dùng eval/exec. Phát hiện vòng tham chiếu khác sheet. `argmax` đánh giá ô công thức và báo lỗi Excel/công thức không hỗ trợ thay vì âm thầm bỏ ô. `num` không còn biến chuỗi mơ hồ `1,2` thành `12`.
5. **Context:** chế độ compact giữ tọa độ, giá trị, kiểu JSON, ngày, format, merge, hidden, indent/bold; dùng kiểu JSON tự nhiên để tránh lặp tag. Khi văn bản workbook quá 800.000 byte, tự chuyển sang view có khai báo phần chưa hiển thị và cơ chế `request_regions`. Backend vẫn chứa toàn bộ workbook. Vùng đọc thêm phải hoàn chỉnh hoặc bị từ chối rõ ràng để thu hẹp, không bị cắt dở. Việc xem thêm dùng chung trần suy luận/request/chi phí.
6. **Vận hành:** có tùy chọn reasoning thích ứng cho lượt sửa/kiểm chứng, không thay trạng thái giữa các câu đồng thời. Concurrency 4 là tùy chọn và giảm worker xuống 128 MiB; mặc định giữ 2. Usage ghi riêng prompt/completion/reasoning khi API có cung cấp.
7. **Bộ đo:** kiểm tra ID dựa trên queries của chính experiment; không lấy mẫu số từ predictions. Không tự dùng tuning cũ. Workbook/biến thể cùng `family` không được nằm cả tuning và holdout. Báo cáo tách điểm public đầy đủ với workbook dành riêng. Sổ ngân sách giữ trước chi phí mỗi experiment, bảo toàn khi gián đoạn và khóa giữa các process.

Không thêm tra đáp án theo ID, tên file hoặc query vào luồng `run.py`/`src`. Các chương trình ghi lại và oracle chỉ dùng trong benchmark/replay offline.

## Cấu hình bàn giao

- Model `qwen/qwen3.7-flash`, temperature 0, reasoning 256, output 2048, concurrency 2.
- Giữ `--compact-prompt` và `--adaptive-reasoning` **tắt mặc định**. Chưa có bằng chứng live để đánh đổi độ đúng lấy byte hoặc tốc độ. Có thể dùng hai cờ này với `benchmarks.experiment` để so sánh ngay khi API hoạt động.
- Giữ tối đa ba lượt suy luận, năm HTTP attempts, deadline nội bộ 2300 giây, 0,09 USD/câu kể cả retry và bộ nhớ vận hành được theo dõi ở ngưỡng 800 MiB.
- Cơ chế view mở rộng chỉ thay đường đi khi full workbook quá lớn; workbook thông thường vẫn gửi đủ ô.

## Trở ngại HTTP 402 và chi phí

Lượt baseline mới dừng vì HTTP 402, không có token suy luận; không dùng kết quả trống 0/20 của lượt hỏng này để đánh giá chất lượng model. Hai request đồng thời bị từ chối được giữ dự phòng bảo thủ 0,009262583 USD, không khẳng định đây là tiền đã bị tính. Sau đó đã dừng request trả phí.

Trước khi thử API tạm, sổ ghi cận trên 0,2428357245 USD. Sau các lượt BazaarLink bị quota, cận trên bảo thủ là **0,3179270045/0,50 USD**, còn tối đa **0,1820729955 USD**. Phần tăng có dự phòng cho request lỗi chưa có usage, không đồng nghĩa tiền đã bị trừ. Xem `development_budget.json`; không cộng lại mọi metrics để tránh lẫn/đếm hai lần các lượt cũ.

Kiểm tra read-only bằng đúng khóa đang cấu hình trả: key limit 3 USD, limit_remaining 2,835319566 USD; endpoint credits báo total_credits 0 và total_usage 0,200794792 USD. Khóa trong môi trường trùng khóa trong `.env`. Hạn mức của khóa và credit khả dụng của tài khoản là hai điều kiện riêng; xem [tài liệu giới hạn OpenRouter](https://openrouter.ai/docs/api_reference/limits) và [endpoint credits](https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits). Không lưu token hoặc định danh tài khoản trong báo cáo. File `account_status.json` chỉ có các trường trạng thái/chi phí đã chọn.

## Đóng gói và việc còn lại

ZIP mới nằm ở `dist/table_qa_submission.zip`; manifest lưu kích thước/hash. Đã kiểm tra archive chỉ chứa mã, test, benchmark, README và cấu hình/phụ thuộc cho phép; không có `.env`, secret, dữ liệu/đáp án, reports, venv hoặc cache. Baseline source và ZIP cũ được giữ trong `baseline_source`, không đưa vào ZIP nộp.

`zip_validation.json` ghi kiểm thử từ ZIP giải nén sang cwd mới, môi trường không có API key, test suite và replay với input ngoài thư mục code, workbook/ID đổi tên. Replay sử dụng chương trình từ lượt LLM cũ, không được gọi là live benchmark. Docker daemon không hoạt động, nên chưa xác nhận Linux 6 vCPU hay trần bộ nhớ trên máy BTC.

Sau khi credit khả dụng được khôi phục:

1. Chạy baseline snapshot và bản sửa trên cùng tuning, cùng cấu hình, qua sổ ngân sách; không coi baseline hỏng HTTP 402 là điểm so sánh.
2. So sánh compact, sau đó reasoning thích ứng/concurrency chỉ trên tuning, trong trần đã phân bổ. Chọn theo Exact Match → thời gian → token. Giữ mặc định nếu chưa đủ bằng chứng.
3. Khóa cấu hình trước khi dùng public đợt 2 và một bộ khác họ cấu trúc chưa dùng để sửa. Báo cáo lần đầu trước chỉnh; mọi tập đã xem lỗi phải chuyển thành regression.
4. Chạy ZIP của đúng hash cuối trên Linux; xác nhận điều kiện tài nguyên và CSV trước nộp.

Chưa có benchmark LLM trước/sau thành công của phiên bản mới, chưa có private test và chưa có dữ liệu public đợt 2 trong workspace. Các cải thiện offline và độ gọn prompt không chứng minh mức tăng điểm private hoặc mức giảm token/thời gian API.

## Cập nhật API BazaarLink theo yêu cầu

Đã thêm transport chỉ dùng trong harness `benchmarks.experiment --provider bazaarlink`. Model được đối chiếu catalog bằng ID/alias `qwen/qwen3.7-flash`; metadata có giá theo từng tier và hỗ trợ reasoning. Cả catalog và response schema được kiểm tra từ [tài liệu BazaarLink](https://bazaarlink.ai/en/docs/api). Chỉ endpoint của module đang benchmark được đổi trong context manager rồi khôi phục; `run.py` vẫn dùng OpenRouter. Khóa đọc từ `.env`/môi trường, file cấu hình cục bộ có quyền 0600; không đưa vào mã/log/ZIP.

Đã bắt đầu hai lượt baseline trên cùng gateway:

- `bazaar_baseline`: concurrency 2; bị nhiều HTTP 429 và hết phần dự phòng 0,03 USD của lượt thử. Chỉ 4 câu có kết quả, không dùng làm số đo độ chính xác toàn bộ.
- `bazaar_baseline_serial`: chạy lại concurrency 1; vẫn bị quota và dừng trước khi hoàn tất 20 câu. Cũng không dùng để chọn cấu hình hoặc so sánh trước/sau.

Thông báo chẩn đoán thực tế trả HTTP 429, `error.code=free_daily_limit`: tài khoản đã hết **60 request model miễn phí/ngày**, `Retry-After=79511` giây tại lúc kiểm tra; reset ở 00:00 UTC, tương ứng 07:00 Việt Nam. Đây là quota tài khoản, không phải lỗi schema, model không tồn tại hay bằng chứng giải pháp bị giảm điểm. Endpoint credits/usage và các response thành công báo chi phí thực 0 USD, phù hợp free tier; các request lỗi vẫn giữ dự phòng bảo thủ. Không dùng mức 0 USD này để dự đoán chi phí OpenRouter khi chấm.

Lúc đầu 429 chưa được phân biệt theo thông điệp cụ thể. Đã sửa root cause vận hành: tôn trọng Retry-After, không đợi quá deadline, dừng request mới toàn lượt khi reset quá xa hoặc nhận free_daily_limit. Trace chỉ lưu mã lỗi được giới hạn, không lưu thông điệp có thể echo credential.

Các chương trình thật từ lượt baseline còn phát hiện guard `raise ValueError` hợp lệ bị AST từ chối và việc lọc cột tên/text cùng cột số dễ bị model dùng sai. Đã bổ sung Raise có giới hạn ba loại exception, giữ cấm try/except; `data_rows` nhận mapping kiểu cho từng cột và `argmax` có absolute=True. Chương trình thật từng thất bại ở p4_q006 vì Raise nay replay trả **7668**, khớp đáp án. Xem `bazaar_failed_program_replay.json`; đây là sửa lỗi thực thi, không phải lượt sinh code mới.

Đã khóa thêm bộ 18 câu/3 workbook với các họ long-form events, join theo project code khác sheet và ngày dạng text với ngày tham chiếu Audit. Oracle tính độc lập; query/workbook được băm trong `frozen_holdout/manifest.json`. Chưa chạy LLM trên bộ này vì quota; chưa dùng điểm của nó để tinh chỉnh.

Chưa thể hoàn tất benchmark live trước/sau cho tới khi tài khoản có credit trả phí, có khóa khác đủ quyền hoặc quota được reset. Không gọi tiếp chỉ để thử lại quota, không đổi sang model khác và không bật compact/adaptive mặc định khi thiếu bằng chứng Exact Match. ZIP và manifest mới là checkpoint đã kiểm thử; nghiệm thu Linux/live vẫn còn thiếu.
