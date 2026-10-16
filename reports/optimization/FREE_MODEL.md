# Model miễn phí cho giai đoạn phát triển

Kiểm tra ngày 15/10/2026 bằng catalog/API OpenRouter thật. Không tìm thấy biến thể Qwen miễn phí trong catalog tại thời điểm khảo sát. Không có bảo đảm free không giới hạn: tài khoản đang có trần 50 request miễn phí/ngày, dùng chung giữa các model. Không cần nạp thêm để thực hiện các lượt thử miễn phí đã ghi nhận dưới đây.

## Chọn model và phép đo thực tế

Chọn `nvidia/nemotron-3-super-120b-a12b:free` để thử tích hợp: context endpoint 262.144 token, hỗ trợ reasoning, response_format JSON và sinh code. Đây là lựa chọn có các khả năng phù hợp pipeline, chưa chứng minh tương đương Qwen3.7 Flash.

| Phép đo | Kết quả |
| --- | ---: |
| Exact Match trên toàn bộ 20 câu công khai | 15/20 (75%) |
| Thời gian toàn lượt | 145.73 giây |
| HTTP attempts, gồm sửa lỗi/kiểm chứng/retry | 27 |
| Token API trả về | 230070 |
| Chi phí API báo cáo | 0 USD |
| RSS đỉnh tổng tiến trình | 66.64 MiB |
| Unit/regression tests, cả bản giải nén ZIP | 118 đạt |
| Replay 20 chương trình Qwen đã sinh trước đây | 20/20 |

Cấu hình thử: concurrency 1, reasoning 256, output 2048, temperature 0; compact/adaptive tắt. Request kiểm tra JSON ban đầu cũng thành công, báo cost 0. Cả 27 response của lượt public có usage.cost=0, không suy chi phí từ việc thiếu usage.

Ba câu không tạo đáp án: dùng helper sai rồi sửa JSON không hợp lệ, chọn ô không phải số, chọn nhầm hàng độ tuổi và bị kiểm tra scope từ chối. Hai câu còn lại trả lời sai ngữ nghĩa. Chi tiết từng ID, code, vùng đọc, usage và lỗi nằm trong `free_nemotron_public/`. Không sửa pipeline hay thêm đáp án/luật theo ID để tăng điểm model thử.

15/20 là điểm sinh mới của Nemotron; 20/20 replay là kết quả chạy lại code đã lưu, không phải benchmark Qwen sinh mới. Không so trực tiếp với thời gian/điểm Qwen lịch sử khác phiên bản và khác concurrency, không dùng để kết luận giảm/tăng private accuracy. Bộ 18 câu holdout đã khóa vẫn chưa được dùng để tuning hoặc chạy model thay thế.

## Đối chiếu thêm Dots3-Note Preview

Chạy `dots-studio/dots-3-note-preview:free` trên **đúng 5 câu Nemotron vừa sai**, cùng cấu hình reasoning 256/output 2048/concurrency 1. Kết quả **2/5**, 257.75 giây, 12 HTTP attempts, 123109 token, 0 USD. Đây là tập stress được chọn sau khi xem lỗi, không phải holdout hoặc đối chiếu toàn bộ public giữa hai model. Không suy ra điểm 20 câu bằng cách ghép hai kết quả.

Dots trả lời đúng hai câu sai ngữ nghĩa của Nemotron, nhưng cả ba câu cần sửa chương trình đều hết output. Usage reasoning thực tế có lúc vượt max_tokens=256 đã yêu cầu (thí dụ 1.281 reasoning token trong output 2.048), nên không phù hợp làm mặc định thử nhanh ở cấu hình này. Chưa thử ngân sách output lớn hơn; không kết luận chất lượng tổng quát của Dots thấp hơn Nemotron. Giữ Nemotron làm mặc định thử tích hợp. Chi tiết nằm trong `free_dots_challenge/report.json` và trace kèm theo.

Tổng hai lượt benchmark và request probe: 40 HTTP attempts, đều báo chi phí 0 USD. Snapshot quota cuối được lưu riêng trong `free_quota_final.json`; counter tài khoản là số đo tại thời điểm đọc, không thay cho số HTTP attempts trong trace.

## Cách dùng và kiểm soát

```bash
.venv/bin/python -m benchmarks.experiment --provider openrouter-free --report-dir reports/free_dev_next --concurrency 1 --limit 0.01
```

Mỗi lần dùng một thư mục mới để giữ bằng chứng. Có thể thêm `--queries /path/to/smoke_queries.json --references /path/to/answers.csv --input-dir /path/to/workbooks` để chỉ chạy ca tích hợp cần thiết. Reference chỉ được evaluator đọc, không vào prompt/suy luận.

- Giữ `run.py` mặc định `qwen/qwen3.7-flash` qua OpenRouter để chấm thi.
- Chế độ miễn phí chỉ ở harness; yêu cầu một ID `:free` cố định, catalog có giá mọi trường/tier bằng 0, và đủ tham số pipeline. Không dùng `openrouter/free` chọn model ngẫu nhiên.
- Mỗi HTTP attempt có routing max_price prompt/completion/request/image bằng 0, require_parameters=true; không thêm paid model fallback.
- Đọc quota tài khoản trước khi chạy; quota thiếu hoặc hết sẽ dừng trước inference. HTTP attempts cách tối thiểu 3,1 giây, tổng attempts trong lượt không vượt remaining được đọc. Tiến trình khác vẫn có thể dùng chung quota; xử lý 429/deadline vẫn áp dụng. Không tìm cách vượt quota bằng nhiều khóa.
- Kiểm tra context theo model thay thế; không âm thầm cắt workbook để vừa context. Câu vượt context được báo lỗi.
- Sổ ngân sách phát triển vẫn giữ cận trên lịch sử 0,3179270045 USD, dưới 0,50 USD; các thử nghiệm miễn phí hoàn tất không tăng chi phí. Khoản --limit giữ trước được hoàn lại khi kết thúc; không phải tiền bị trừ từ OpenRouter.

Quy trình ít tốn API: chạy tests và replay offline cho thay đổi parser/executor/format; chạy một nhóm câu tích hợp bằng model miễn phí; chỉ dùng Qwen cho xác nhận cuối cùng và so sánh cấu hình theo Exact Match → thời gian → token. Kết quả model miễn phí không quyết định mặc định thi.

## Bằng chứng và nguồn

- `free_model_catalog.json`: snapshot các ID/giá/tham số miễn phí.
- `free_model_probe.json`: kiểm tra thực tế JSON, model và usage.
- `free_nemotron_public/report.json`: điểm strict và metrics đủ 20 câu; `provenance.json` chứa hash dữ liệu/runtime.
- `free_dev_offline_replay.json`: replay 20/20, không có LLM gọi mới.
- `free_dev_release.json`: source/ZIP hash, dung lượng, stdout test của ZIP giải nén.
- [Model Nemotron trên OpenRouter](https://openrouter.ai/nvidia/nemotron-3-super-120b-a12b:free)
- [Giới hạn tài khoản và free usage](https://openrouter.ai/docs/api_reference/limits)
- [Giới hạn giá provider routing](https://openrouter.ai/docs/guides/routing/provider-selection#max-price)

ZIP hiện tại: 84718 byte, 25 file; không chứa .env/khóa API/venv/cache/dữ liệu/đáp án. SHA-256: `f12366a89d01d9ec2bd49ee8b2ef1ed0d72ab68cf9cb79cce1aa7c26ffaadbdc`. Runtime SHA-256: `97ace4e0b58252797cf9b571e83bfd6852e8906ff2ddb0daeb19b7ba450c7e18`.
