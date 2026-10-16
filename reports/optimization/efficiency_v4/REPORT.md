# Tối ưu Gemini: độ đúng, throughput và token

## Candidate v4 được chọn trong giai đoạn phát triển

Hợp đồng JSON có khóa cố định cho từng câu giúp giảm lỗi chỉ số; nhắc lại quy tắc giữ đơn vị hiển thị cạnh yêu cầu đầu ra. Ba lượt public cố định của cùng phiên bản đều **20/20**, không có request thiếu usage:

| Lượt public v4 | Tổng giây | Token |
| --- | --- | --- |
| 1 | 6,36 | 74.969 |
| 2 | 7,95 | 114.736 |
| 3 | 6,92 | 83.344 |
| Trung bình ba lượt | **7,07** | **91.016,33** |

Đối chiếu baseline public sinh mới đạt 20/20, cùng runtime sau sửa guard: **23,14 giây / 203.234 token**. Trung bình candidate giảm **69,44% tổng thời gian** và **55,22% token**. Lượt số 2 chỉ giảm khoảng 43,5% token; vì vậy mức trên là **trung bình ba lượt, không phải cam kết tối thiểu 50% cho mọi lượt**. Không bỏ lượt kém hoặc dùng CSV/replay thay generation.

Sau ba lượt này, khóa source/cấu hình rồi đánh giá đúng một lần trên **32 câu mới / 4 workbook và họ cấu trúc mới**, gồm lịch sử sự kiện theo định danh, lựa chọn dự án dưới hai ràng buộc, cắt khoảng thời gian và chuỗi thời gian. Bộ này khác bộ 60 câu v3 và không dùng để chỉnh prompt trước đánh giá:

| Chỉ số challenge độc lập v4 | Baseline | Candidate |
| --- | --- | --- |
| Exact Match | 31/32 | **32/32** |
| Tổng giây | 48,64 | **13,23** |
| Token, đầy đủ usage | 241.053 | **119.012** |
| HTTP attempts, gồm sửa/kiểm chứng | 42 | **19** |

Giảm **72,80% tổng thời gian / 50,63% token**, tăng một câu đúng trong phép đo này. RAM đỉnh candidate **102,09 MiB**. Một câu chênh lệch không chứng minh mức tăng chính xác trên phân phối private của BTC. Bộ này từ đây là bộ đã tiêu thụ; không chỉnh theo kết quả rồi gọi lại là kiểm định độc lập.

Các lượt v4 đều là Gemini sinh mới. Không gọi Qwen trả phí và không đổi mặc định `run.py`. Snapshot/candidate lock, manifest/oracle và checkpoint ở `reports/optimization/efficiency_v4/`. Các phiên bản trước bị loại của v4 (chưa nhắc lại đơn vị, đạt 18/20) được giữ nguyên. JSON Schema được gateway nhận nhưng ứng dụng vẫn tự kiểm tra đầy đủ; không suy ra gateway cưỡng chế schema.

## Phép đo sinh mới, vòng v3

Model gateway `ag/gemini-3-flash`, response model `gemini-3-flash`, temperature 1, thinking low, output tối đa 2.048 token. Baseline dùng hợp đồng robust trước đây và concurrency 2; candidate dùng tối đa 4 câu cùng workbook trong một lượt lập chương trình, concurrency 4. Mỗi chương trình chạy độc lập qua cùng executor, formatter và kiểm chứng. Oracle chỉ được đọc sau khi sinh xong đáp án.

| Bộ | Baseline EM → candidate EM | Tổng giây trước → sau | Token trước → sau | Giảm thời gian / token |
| --- | --- | --- | --- | --- |
| Public, đối chiếu chính | 19/20 → **20/20** | 28,77 → **9,45** | 209.728 → **101.544** | **67,15% / 51,58%** |
| Public, lặp lại | 20/20 → **20/20** | 23,14 → **10,24** | 203.234 → **133.633** | **55,75% / 34,25%** |
| Holdout mới, 60 câu | 60/60 → **60/60** | 96,84 → **23,84** | 353.140 → **172.632** | **75,38% / 51,12%** |

Candidate còn đạt **18/18 validation đã biết** (11,50 giây; 63.769 token) và **24/24 synthetic đã biết** (12,34 giây; 57.886 token). Tất cả các lượt trong bảng có usage đầy đủ, gồm các request sửa/kiểm chứng. Token của request chung được chia nguyên chính xác giữa các câu; HTTP event được khử trùng khi tổng hợp, không tính một request thành nhiều request hoặc miễn token lập chương trình.

Lượt lặp public cho thấy **chưa đạt mức giảm token tối thiểu 50% một cách ổn định**: lỗi chỉ số trong JSON và lượt kiểm chứng bổ sung có thể tăng token. Giữ cả kết quả tốt và kém; không lấy riêng lượt tốt nhất để kết luận đã hoàn tất mục tiêu. Baseline đầu tiên sai một câu do khai báo evidence thiếu; baseline lặp lại đạt 20/20. Hai candidate public đều 20/20 ở source cuối của v3.

## Ý nghĩa của thời gian và RAM

Các số giây trên là tổng wall time của stage, gồm nạp workbook, gọi model, retry và thực thi chương trình. Baseline/candidate cùng máy và gateway nhưng đổi concurrency 2 → 4; mức tăng tốc bao gồm tác dụng của batching và concurrency, không được quy toàn bộ cho giảm prompt. Chưa phải phép đo trên máy BTC.

Quy đổi tổng thời gian/số câu trên holdout là 1,614 → 0,397 giây/câu. Độ trễ từng câu chờ model và xử lý riêng là 3,178 → 3,192 giây/câu: **không giảm 50%**. Batching tăng throughput, không chứng minh model trả từng câu nhanh hơn. Ghi cả hai cách đo vì đề chưa mô tả chi tiết cách BTC đo thời gian trung bình.

RAM đỉnh candidate holdout khoảng **102,27 MiB**, public chính khoảng **96,91 MiB**. Đây là tổng RSS tiến trình chính và worker; không phải RAM model. Chưa xác nhận trên máy 6 vCPU của BTC.

## Thay đổi tổng quát

- Biểu diễn lossless bằng các dãy ô liên tiếp trên cùng dòng: giữ tọa độ gốc, mọi giá trị, kiểu ngày/lỗi/formula, format, merge, hidden rows/columns và header/table hints. Metadata giống nhau được nhóm theo vùng; không cấp phát theo vùng trống và không bỏ dòng sau 200.
- Chia sẻ một lần gửi workbook/hướng dẫn cho tối đa bốn câu. Mỗi câu có chương trình và kiểm chứng riêng; lỗi được sửa riêng, cùng giới hạn ba lượt suy luận/năm HTTP attempts tính cả lượt lập chương trình chung.
- Giữ chương trình phụ thuộc vào đọc dữ liệu thật, không chép đáp án hoặc số đo từ prompt vào code. Không dùng ID, tên file hay CSV mẫu để suy luận.
- Ghi dấu thứ tự của `age_order` để phát hiện đảo oldest/youngest; trước đây helper này bỏ qua dấu vết mà sort viết tay đã có.
- Phép hiệu phải đọc cả hai nhãn chỉ tiêu được nêu rõ. Cực trị không được bỏ qua một category trung gian bên trong vùng đã quan sát nếu câu hỏi không giới hạn lựa chọn. Không mở rộng qua bảng/cột khác.
- Báo lỗi khi bộ lọc yêu cầu ngày typed datetime thành string làm mất toàn bộ hàng; vẫn cho phép kết quả 0 hợp lệ sau bộ lọc điều kiện dữ liệu.

## Holdout và giới hạn kết luận

60 câu thuộc 10 workbook/family, gồm join catalog, ô thiếu và số 0, timestamp qua nửa đêm, trọng số sử dụng công suất, biến động có dấu, đơn vị khối lượng, đồng hạng, bảng nhiều năm dạng dài, thuế và nồng độ. Oracle được tính riêng; dữ liệu và đáp án được hash/đóng băng trước chọn candidate. Source/cấu hình được khóa trước đánh giá, không sửa theo lỗi rồi gọi lại đó là kiểm định độc lập.

Baseline và candidate đều 60/60: có bằng chứng giữ độ đúng và giảm tài nguyên trên bộ này, **chưa có bằng chứng tăng độ chính xác private của BTC**. Bộ này đã được sử dụng; mọi lượt chạy lại hoặc biến thể gần của nó phải ghi là regression. Không ghép điểm với holdout 23/24 cũ để gọi đó là cùng một phép đo trước/sau.

Snapshot đã đo và báo cáo thô nằm trong workspace phát triển tại `reports/optimization/efficiency_v3/sealed_proof/`. Giữ cả các cấu hình bị loại vì trả Python thay JSON hoặc giảm độ đúng. Probe và sổ ngân sách được giữ riêng; gateway miễn phí theo xác nhận người dùng, provider không trả `usage.cost`. Không có request Qwen trả phí trong vòng này.

## Trạng thái tiếp tục tối ưu

V4 giữ kiểm tra khóa/kiểu ở ứng dụng, từ chối JSON trùng khóa trước khi decoder có thể ghi đè; không tái sử dụng điểm holdout độc lập v3 cho phiên bản v4. Cần Qwen signoff và dữ liệu ngoài mẫu tiếp theo trước khi xác nhận cấu hình thi.

## Chạy và bàn giao

`python -m benchmarks.batched_cli --input-dir /path/to/xlsx_files --queries /path/to/queries.json --output /path/to/dev_submission.csv` dùng candidate v4/Gemini gateway đã cấu hình bằng `DEV_LLM_*`, không yêu cầu file đáp án. `--planning-format indexed` chọn giao thức v3 để đối chiếu. Dùng đường dẫn output mới cho mỗi lượt; batch giữ deadline và allowance bền vững. CSV/trace/metrics được ghi riêng.

`run.py` vẫn dùng Qwen/OpenRouter. Chưa tự chuyển candidate batching thành mặc định thi và chưa xác nhận bằng Qwen. ZIP candidate không có khóa, `.env`, dữ liệu/đáp án, report raw, model hoặc dependency GPU. Điểm Gemini không thay bằng chứng Qwen và không bảo đảm điểm private tối đa.
