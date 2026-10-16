# Đối chiếu hướng dẫn nộp bổ sung

Hướng dẫn bổ sung được dùng làm đặc tả giao diện nộp bài. Các ZIP lịch sử v64 chưa có Dockerfile, vì vậy không dùng trực tiếp để nộp theo hướng dẫn mới.

| Yêu cầu | Mã hiện tại |
| --- | --- |
| ZIP không quá 100 MB, tên theo đội | `benchmarks.package_submission --team-name` kiểm tra tên, kích thước, allowlist và khóa trước khi thay thế ZIP đích |
| Dockerfile ngay gốc ZIP | Dockerfile và `.dockerignore` có trong allowlist ở gốc, không bọc thêm thư mục |
| Linux amd64, CPU | Image Python 3.11 slim Linux amd64, không cài GPU/model local |
| Đủ thư viện khi chạy | `pip install` tại bước build; lúc thực thi không cài thư viện |
| Không chứa khóa API | Không COPY `.env`; build context chỉ gồm Dockerfile, requirements, run.py và src/*.py; ZIP kiểm tra giá trị bí mật trong `.env` |
| ENTRYPOINT nhận tham số | `ENTRYPOINT ["python", "run.py"]` |
| Đủ sáu tham số chấm | `--xlsx-dir`, `--queries`, `--output`, `--openrouter-key`, `--openrouter-model`, `--openrouter-base-url` |
| Không sửa `/input` | Kiểm tra đường dẫn output/temporary/diagnostics trước khi ghi; từ chối ghi trong input-dir hoặc `/input`, ghi đè queries/workbook và alias symlink/hardlink |
| Log stdout/stderr | CLI mặc định không tạo trace/metrics; lưu file chỉ khi người phát triển bật `--save-diagnostics` hoặc `--trace` |
| CSV UTF-8 đúng `id,answer` | ID đầu vào được kiểm tra duy nhất; CSV theo đúng thứ tự và đủ mỗi ID một lần; đáp án được formatter xử lý riêng |
| Thành công sau khi ghi xong | Ghi CSV bằng tệp tạm rồi atomic replace; lỗi ghi/API/câu hỏi hoặc thiếu đáp án trả mã khác 0 |

Giữ các tên CLI cũ `--input-dir`, `--api-key`, `--model` và mặc định Qwen/OpenRouter. Base URL được áp dụng cho cả completion và metadata giá; không chuyển sang gateway/Gemini khi chấm. Thuật toán chọn dữ liệu/tính toán không đổi trong đợt chỉnh tuân thủ này.

## Kiểm tra lặp lại

```bash
python -m pytest -q
ruff check run.py evaluate.py src tests benchmarks
ruff format --check run.py evaluate.py src tests benchmarks
docker build --platform linux/amd64 -t table-qa:submission-guide .
python -m benchmarks.docker_smoke --report-dir reports/submission_smoke_new
python -m benchmarks.package_submission --team-name Fprinciples_TDTU1
```

Tên đội đã được người dùng xác nhận là `Fprinciples_TDTU1`. `--report-dir` phải là thư mục chưa tồn tại. Bước smoke dùng image vừa build, mock API trong mạng Docker `--internal`, dữ liệu sinh riêng, input mount read-only và root filesystem read-only. Kiểm tra cả lượt thành công và HTTP 401; không gọi LLM bên ngoài. Có bước chạy `--help` với `--network none` để xác nhận entrypoint/dependency sẵn có. Bộ test Python kiểm tra thêm đường dẫn mới, alias CLI cũ, CSV Unicode, đầu vào không đổi, lỗi ghi đầu ra, từ chối alias ghi đè và gói ZIP không chứa bí mật.

Kết quả ngày 16/10/2026: **437 test toàn dự án đạt**, Ruff check đạt và format check đạt trên **92 file Python**. Gói giải nén có **419 test** (loại 18 test Colab). Đã build và chạy thành công image CPU Linux amd64 từ source trong ZIP: lượt mock thành công trả mã 0, HTTP 401 trả mã 1, CSV đủ ID, hash input không đổi. Thư mục ứng dụng trong image chỉ chứa 12 file runtime được cho phép, không có `.env` hoặc bộ dữ liệu. Bằng chứng cục bộ nằm trong `reports/submission_guide/`.

## Giới hạn bằng chứng

Kiểm tra Docker/mock xác nhận giao diện và khả năng thực thi, không đo độ chính xác Qwen. Điểm Gemini v64 trong các báo cáo cũ vẫn thuộc source snapshot đó; chưa có benchmark LLM sinh mới sau thay đổi đóng gói/CLI này. Không dùng kết quả mock hoặc replay để tuyên bố đã xác nhận Qwen/private test.

Gói nộp theo hướng dẫn mới là `dist/Fprinciples_TDTU1.zip`. Gói có tên `table_qa_submission_guide_candidate.zip` là bản kiểm tra trước khi nhận tên đội, không dùng thay gói nộp này.
