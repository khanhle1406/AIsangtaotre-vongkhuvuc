# Kế hoạch tối ưu theo cách chấm của đề

Ngày lập: 15/10/2026. Phạm vi hiện tại là lập kế hoạch; chưa thay đổi mã suy luận hoặc gọi thêm API trả phí.

## 1. Mục tiêu và bằng chứng nền

Chỉ so sánh các phương án đáp ứng toàn bộ điều kiện hợp lệ. Chọn theo thứ tự: nhiều câu Exact Match đúng hơn, sau đó thời gian trung bình thấp hơn, sau đó token trung bình thấp hơn. Không quy đổi một câu sai thành lợi ích thời gian, token hoặc USD. Chi phí là giới hạn bắt buộc, không phải tiêu chí xếp hạng độc lập.

Giữ model `qwen/qwen3.7-flash`, CLI và định dạng CSV hiện có. Không dùng ID, tên tệp hoặc đáp án công khai để quyết định kết quả suy luận.

Bằng chứng đã lưu: public 20/20; lượt ZIP đổi đường dẫn/tên workbook/ID đạt 20/20 trong 89,24 giây, 198.156 token, 0,0055774 USD, RSS đỉnh 84,61 MiB. Có 63 test cuối đạt. Những lượt LLM đầy đủ này chạy trước các sửa đổi cuối về ngày tham chiếu và dừng lỗi tài khoản; mã cuối mới được kiểm thử và replay. Không coi replay là chạy lại LLM.

Public và các họ synthetic hiện tại đã được dùng để sửa lỗi. Chúng là regression, không phải ước lượng private test độc lập. API lần cuối trả HTTP 402; khả năng chạy benchmark trả phí cần được kiểm tra khi triển khai.

## 2. Thứ tự triển khai

### P0 — Khóa mốc so sánh và sửa bộ đo

Tệp chính: `benchmarks/compare.py`, `evaluate.py`, test benchmark mới.

- Lưu hash mã, cấu hình, dữ liệu, phân chia tập, phiên bản Python/phụ thuộc và ZIP. Giữ phiên bản 20/20 có thể phục hồi.
- Sửa `score()` để nhận tập ID mong đợi từ queries của chính lượt chạy. Bắt buộc kết quả có đúng tập ID đó; không suy ra mẫu số từ các ID có trong prediction. Thiếu/thừa/trùng ID là submission không hợp lệ.
- Bỏ tự động dùng `reports/tuning/queries.json` khi người chạy không chỉ định. Kiểm tra tuning queries thuộc đúng bộ dữ liệu, tham chiếu và phân chia hiện tại.
- Dùng một sổ ngân sách phát triển có nguồn gốc từng request/lượt chạy, tránh cộng mù mọi metrics trong thư mục hoặc bỏ sót lượt gián đoạn. Bảo toàn dự phòng cho usage chưa xác định.
- Báo cáo riêng: Exact Match toàn bộ và từng họ cấu trúc; số câu không trả lời; số lượt API/retry; input/output/reasoning tokens nếu API cung cấp; thời gian toàn lượt, thời gian từng câu và tổng RSS cha/con. Phân biệt token được API tính phí với token prompt ước lượng.
- Chạy lại baseline của đúng mã cuối nếu API hoạt động và còn ngân sách; nếu không, ghi rõ chưa có baseline live mới.

Nghiệm thu: test thiếu/thừa ID và tuning sai nguồn đều thất bại đúng cách; CSV hợp lệ được chấm nguyên văn; baseline có cấu hình/hash/metrics và trạng thái hoàn tất rõ ràng.

### P1 — Chọn đúng bảng và phạm vi trước khi tính

Tệp chính: `src/excel_parser.py`, `src/verification.py`, `src/llm_agent.py`.

- Nhận diện vùng bảng và tiêu đề theo từng vùng, thay vì coi phần trước hàng dữ liệu đầu tiên của toàn sheet là tiêu đề cho mọi bảng. Giữ nguyên ô gốc, merge, đơn vị, chú thích và tọa độ để đối chiếu khi heuristic không chắc chắn.
- Bổ sung bằng chứng lựa chọn trong JSON model: sheet/vùng, chỉ tiêu, năm, nhóm dân số, đơn vị, phép tính và các cột tham gia. Kiểm tra tại ứng dụng, đối chiếu với trace ô thực sự đã đọc. Giữ tương thích khi bổ sung trường; không thay toàn bộ executor.
- Thu hẹp `complete_mean_contract`: chỉ tự hoàn thiện khi xác định duy nhất bảng, hàng chỉ tiêu và nhóm cột thuộc câu hỏi. Loại khỏi tập tính các mã số, mẫu số và chỉ tiêu không liên quan bằng cấu trúc/tiêu đề, không bằng danh sách tên công khai.
- Phân biệt trung bình các giá trị được trình bày, trung bình có trọng số, tổng nhóm con không chồng lấn và tổng công bố. Có Total không tự động đồng nghĩa phải cộng hoặc phải bỏ. Khi bằng chứng chưa đủ, yêu cầu model giải quyết phạm vi thay vì tự ghi đè kết quả.
- Áp dụng cùng nguyên tắc bằng chứng cho ngày tham chiếu, phần trăm, năm và tên nhóm. Điều kiện ngôn ngữ có thể phát hiện rủi ro nhưng không được tự chứng minh lựa chọn dữ liệu đúng.

Nghiệm thu: giữ regression public 20/20; kiểm tra phản ví dụ có hai bảng cạnh nhau, nhãn lặp, nhiều năm/nhóm trên cùng hàng, cột mã số, Total trùng cấp, ngày tham chiếu khác Admission. Đổi số/nhãn/vị trí phải làm đáp án đổi đúng theo oracle độc lập.

### P2 — Kiểm chứng thích ứng và xử lý các lỗi còn lại

Tệp chính: `src/llm_agent.py`, `src/verification.py`, `src/executor.py`, `src/postprocessor.py`.

- Kích hoạt kiểm chứng bằng tín hiệu của ứng dụng: nhiều vùng cùng phù hợp, phạm vi đọc không khớp câu hỏi, đơn vị không thống nhất, parent/child chồng lấn, giá trị bị loại do kiểu hoặc công thức, và giả định chưa được chứng minh. Không chỉ dựa vào `needs_verification` do model tự khai.
- Lượt kiểm chứng chọn lại phạm vi từ câu hỏi và dữ liệu trước khi xem đáp án đề xuất, rồi đối chiếu hai cách chọn. Giải quyết khác biệt bằng bằng chứng; không dùng bỏ phiếu số đông làm mặc định.
- Giữ đường nhanh một lượt cho câu rõ ràng. Chia sẻ trần ba lượt suy luận và năm HTTP attempts giữa sinh code, sửa lỗi và kiểm chứng; không tạo thêm ngân sách retry ngoài trần.
- Kiểm tra thêm string dates/DOB, dấu phân cách số, số âm, phần trăm, tie khi xếp hạng, làm tròn và thứ tự danh sách bằng workbook có oracle độc lập.
- Ưu tiên formula cached. Chỉ mở rộng tập công thức được hỗ trợ khi có ca kiểm tra cụ thể; phát hiện vòng tham chiếu, công thức ngoài khả năng và cache thiếu. Không phát triển một Excel engine đầy đủ trong đợt này.
- Bảo đảm lỗi kiểu, JSON/code, công thức hoặc API không làm hỏng checkpoint của các câu khác.

Nghiệm thu: lỗi có chủ đích được phát hiện; các câu rõ ràng không bị buộc gọi thêm; mọi request chịu ngân sách/deadline; kiểm chứng không làm mất câu đúng trên regression hoặc tập validation đã khóa.

### P3 — Giảm thời gian và token sau khi khóa hành vi đúng

Tệp chính: `src/excel_parser.py`, `src/llm_agent.py`, `run.py`.

- Đo tỷ trọng prompt, output, retry, parse và worker trước khi tối ưu.
- Nén biểu diễn workbook nhưng giữ tọa độ, kiểu, tiêu đề, đơn vị và chú thích. Gom mô tả lặp; dùng helper để đọc dữ liệu thật, không yêu cầu chép số vào code.
- Chọn vùng bằng cấu trúc và mức phù hợp với câu hỏi; luôn gửi danh mục các bảng/sheet và có cơ chế mở rộng khi không chắc chắn. Mọi ô vẫn nằm trong backend, không tái lập cắt 200 dòng hoặc cắt âm thầm theo context.
- Mặc định một request cho câu rõ ràng; không thêm một lượt LLM chỉ để định tuyến mọi câu. Khi cần mở rộng, lượt bổ sung vẫn dùng chung trần suy luận.
- Cache parse và biểu diễn bất biến theo nội dung workbook/phiên bản parser. Nếu cache kết quả suy luận trong thử nghiệm, phải bao gồm nội dung câu hỏi, model, prompt và cấu hình; tắt cache này khi đo năng lực sinh đáp án mới. Không cache theo ID/tên file.
- So sánh tối đa ba cấu hình trên tuning: mốc 256/2048 hiện tại, cùng mốc với prompt gọn, và reasoning thích ứng tới 1024/output 4096 cho câu có rủi ro. Giữ temperature 0.
- Chỉ thử concurrency 4 sau khi hai worker ổn định. So sánh với concurrency 2 trong cùng điều kiện, có giới hạn RSS và xử lý 429; concurrency 1 là phương án khi workbook lớn. Không tăng chỉ vì RAM public thấp.

Mục tiêu thử nghiệm: giảm ít nhất 20% token hoặc thời gian so với baseline đo cùng điều kiện, với số câu đúng không giảm. Chọn cấu hình theo thứ tự chấm của đề, không theo mức giảm phần trăm. Đây là mục tiêu cần đo, không phải cam kết.

### P4 — Đánh giá tổng quát hóa và chọn phiên bản

Tệp chính: `benchmarks/fixtures.py`, `benchmarks/compare.py`, test mới và báo cáo.

- Đưa public 1 và các họ synthetic từng dùng để sửa vào regression/tuning. Tạo tập mới tách theo workbook và họ cấu trúc; các biến thể cùng nguồn phải nằm cùng phía.
- Bộ mới bao phủ nhiều sheet/bảng, tiêu đề nhiều tầng, bảng cạnh nhau, label trùng, subtotal, dòng ẩn, số liệu sau hàng 200, ngày dạng chuỗi/Excel, phần trăm, số âm, cache công thức thiếu và định dạng đáp án. Đáp án do phép tính độc lập tạo; không dùng chính helper đang được kiểm tra làm oracle.
- Dùng metamorphic test cho đổi ID/file/sheet, dịch bảng, đảo cột tương đương, thêm nhiễu và thay số. Tách kiểm tra parser/helper miễn phí với kiểm tra LLM thực sự đọc lại bố cục đã đổi.
- Khi có public 2 lúc 09:00 ngày 16/10, chạy phiên bản đã khóa trước khi xem lỗi và sửa. Ghi kết quả lần đầu như kiểm tra ngoài mẫu. Sau khi dùng kết quả để sửa, bộ này trở thành regression; muốn kết luận ngoài mẫu mới phải dùng tập chưa quan sát khác.
- Khóa cấu hình trước holdout. Chấm từng họ và toàn bộ; không chấp nhận tăng tổng nhờ một họ dễ mà làm giảm họ đã đúng. Nếu cần sửa theo lỗi holdout, công bố việc tập đó đã được dùng để phát triển.
- So sánh cùng máy/cùng dữ liệu, ghi rõ thứ tự chạy và nhiễu mạng. Chỉ lặp lại baseline/candidate gần ngang nhau, tối đa hai lượt bổ sung cho cặp được chọn nếu còn ngân sách. Không coi một lượt nhanh hơn nhỏ là kết luận chắc chắn.

Quyết định: chọn số câu đúng cao nhất trên tập chưa dùng để chọn cấu hình; khi bằng nhau mới so thời gian, sau đó token. Nếu bằng chứng không đủ để đổi, giữ bản ổn định. Không mô tả điểm holdout nhỏ là bảo đảm điểm private.

### P5 — Kiểm tra môi trường chấm và đóng gói

- Chạy Ruff check, Ruff format check và toàn bộ pytest bằng môi trường Python hiện có. Mọi sửa lỗi phải có regression test về hành vi, không chỉ phản chiếu implementation.
- Cài sạch/chạy ZIP trên Linux với 6 vCPU; đo tổng RSS tiến trình cha/con. Không coi số đo macOS là chứng minh đã đạt trên máy BTC.
- Chạy từ thư mục khác với đường dẫn input/output mới, đổi tên ID/file/sheet; kiểm tra đủ ID và Exact Match. Cần ít nhất một lượt LLM đầy đủ trên đúng hash mã/ZIP cuối khi API cho phép.
- Kiểm tra deadline toàn lượt, timeout/retry/402/429, checkpoint khi gián đoạn và workbook lớn. Giữ bộ nhớ vận hành dưới 800 MiB, deadline nội bộ 2300 giây/20 câu và trần nội bộ 0,09 USD/câu gồm retry, có khoảng đệm cho giới hạn đề.
- Kiểm tra ZIP thực tế dưới 100 MB, không có .env/khóa/venv/cache/dữ liệu/đáp án, README đúng lệnh chạy. Bàn giao mã, test, CSV mẫu, ZIP, manifest và báo cáo cả lần chạy thành công lẫn thất bại.
- Nếu chưa có Linux hoặc API còn lỗi, ghi rõ phần chưa kiểm chứng; không công bố nghiệm thu đầy đủ.

## 3. Ngân sách phát triển còn lại

Cận trên kế toán đã lưu: 0,2335731415 USD trên mức đã cho phép 0,50 USD. Phần còn lại tối đa 0,2664268585 USD, cần đối soát trước request mới. Đây không phải thông tin số dư tài khoản OpenRouter.

| Hạng mục | Trần USD bổ sung |
| --- | ---: |
| Baseline của mã cuối và kiểm tra API | 0,03 |
| So sánh tối đa ba cấu hình trên tuning | 0,10 |
| Holdout và public 2 | 0,09 |
| Lặp độ ổn định và chạy ZIP cuối | 0,04 |
| Tổng phân bổ | 0,26 |

Mỗi giai đoạn bị chặn trước request nếu dự toán vượt phần còn lại. Không tự tiêu hết ngân sách khi mục tiêu đã rõ. Nếu API trả 402, dừng các request tiếp theo và tiếp tục các kiểm tra offline; không chuyển model hoặc tài khoản để né lỗi.

## 4. Lịch và tiêu chí dừng

- 15/10: P0, P1, regression và phản ví dụ offline; triển khai P2 theo lỗi có bằng chứng. Khóa phiên bản trước khi dùng public 2.
- 16/10 từ 09:00: chạy public 2 nguyên trạng; thực hiện P3/P4 trong ngân sách, ghi rõ dữ liệu nào đã dùng để chọn cấu hình.
- Trước 10:00 ngày 17/10: đóng băng mã để dành thời gian cho P5, nộp trước hạn 12:00. Thay đổi cuối chỉ để sửa lỗi làm bài không hợp lệ và phải kiểm tra lại.

Nghiệm thu: không giảm regression public 20/20; đạt kết quả tốt nhất có bằng chứng trên dữ liệu ngoài mẫu; lint/format/test đạt; CSV/ZIP hợp lệ; có lượt live đúng phiên bản cuối và kiểm tra môi trường chấm hoặc nêu rõ thiếu hụt. Thời gian/token chỉ là lý do đổi phiên bản sau khi chất lượng ngang nhau.

Dừng mở rộng khi thay đổi không tăng độ đúng hoặc lợi ích tốc độ không lặp lại được; giữ phiên bản có bằng chứng tốt hơn. Không bổ sung luật riêng cho câu public, không thay toàn bộ kiến trúc, không viết Excel engine đầy đủ, không gọi nhiều model bỏ phiếu mặc định. Mục tiêu là tối đa hóa khả năng đạt điểm cao trong các giới hạn đã biết; không thể chứng minh tối ưu tuyệt đối khi private test chưa công bố.
