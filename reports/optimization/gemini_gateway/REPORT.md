# Báo cáo chuyển gateway và tối ưu Gemini — 15/10/2026

Đã tích hợp gateway, chạy Gemini sinh mới, khóa candidate và đánh giá holdout. **Chưa đạt điểm tối đa và chưa đủ điều kiện thay mặc định thi**: public đạt 17/20, holdout đạt 17/18; bước xác nhận Qwen bị chặn vì tài khoản OpenRouter có tổng credit 0 USD. Không gọi inference Qwen trả phí trong đợt này.

## Kết quả sinh mới

Model yêu cầu `ag/gemini-3-flash`; model trả về `gemini-3-flash`. Baseline là mã hiện tại A, không phải snapshot cũ hay submission lưu sẵn. Candidate C: compact không mất ô + hợp đồng helper/JSON đặt ở system và cuối user message; temperature 1.0, thinking `minimal` được gateway nhận, output 2.048, concurrency 2. Việc gateway nhận tham số không chứng minh thinking thực tế được áp dụng chính xác; usage không công bố riêng reasoning token.

| Bộ dữ liệu | Exact Match A → C | TB giây/câu A → C | Tổng giây A → C | Token API đã ghi nhận A → C | HTTP attempts A → C |
| --- | --- | --- | --- | --- | --- |
| Public 20 câu | 16/20 → 17/20 | 10.12 → 10.62 | 102.19 → 134.61 | 527,584 → 249,821 | 50 → 29 |
| Synthetic đã biết 24 câu | 24/24 → 24/24 | 7.71 → 2.02 | 105.03 → 25.03 | 188,628 → 107,771 | 49 → 25 |
| Holdout độc lập 18 câu | 16/18 → 17/18 | 5.78 → 3.08 | 62.31 → 27.75 | 183,404 → 112,312 | 41 → 23 |

Holdout tăng một câu đúng (88,89% → 94,44%); thời gian trung bình giảm khoảng 46,7%. Synthetic giữ 24/24, thời gian trung bình giảm khoảng 73,7%. Public tăng một câu đúng nhưng thời gian trung bình tăng khoảng 5%; **không tuyên bố public nhanh hơn**. Public có timeout và retry, tổng thời gian 134,61 giây ở candidate. Mỗi cấu hình chỉ đo một lượt; chưa đo độ ổn định qua nhiều seed/lượt và chưa thể suy ra tốc độ trên máy BTC.

Token trong bảng là tổng usage API nhận được, chưa bao gồm phần không biết của request lỗi mạng: lần lượt baseline/candidate thiếu usage ở public 3/3 attempts, synthetic 1/0, holdout 1/0. Vì vậy tổng token thực sự của các lượt đó chưa biết chính xác; không dùng số 0 thay cho phần thiếu. Hạn mức batch giữ reservation bảo thủ cho request thiếu usage. Holdout có số token đã ghi nhận giảm 183.404 → 112.312 (38,8%); con số giảm này không phải phép đo đầy đủ mọi request.

RSS candidate: public 71,48 MiB, synthetic 75,98 MiB; holdout baseline/candidate 90,58/93,39 MiB. RSS baseline public/synthetic bị lượt resume ghi đè thành 0 trong report cũ: **coi là thiếu phép đo, không phải dùng 0 MiB**. Mã runner mới đã lưu peak vào checkpoint để tránh lỗi này.

## Vì sao chọn C

| Cấu hình trên cùng 8 câu tuning | EM | TB giây/câu | Token ghi nhận | Attempts |
| --- | --- | --- | --- | --- |
| screen_A | 8/8 | 5.22 | 67,390 | 17 |
| screen_B | 8/8 | 4.63 | 66,901 | 17 |
| screen_C | 8/8 | 2.79 | 34,524 | 8 |
| screen_minimal | 8/8 | 2.04 | 34,651 | 8 |
| screen_output1024 | 8/8 | 5.62 | 34,597 | 9 |

A/B/C đều 8/8; C nhanh hơn và tránh nhiều lượt sửa JSON. `minimal` vẫn 8/8, nhanh hơn trong lượt đo nên được chọn. Output 1.024 vẫn 8/8 nhưng chậm hơn, có thêm retry; giữ 2.048. Thứ tự chọn là EM, thời gian, token. Các phép đo có nhiễu mạng; chưa coi mức chênh lệch này là hằng số hiệu năng.

Probe phát hiện gateway trả SSE dù yêu cầu JSON, đồng thời có token framing ngoài prompt. Đã bổ sung bộ đọc stream có giới hạn, ghép delta, kiểm tra finish reason, ghi usage/model; không mang `reasoning.max_tokens`/`usage.include` của OpenRouter sang gateway. JSON vẫn được ứng dụng kiểm tra bằng Pydantic. Gateway chỉ dùng khóa DEV, HTTPS và chặn redirect; không tự đổi model/provider.

## Các lỗi còn lại và kiểm tra tổng quát hóa

- Public `p4_q009`: tự nhân 1.000, trả 2.218.000 thay cho 2.218; rủi ro diễn giải đơn vị.
- Public `p4_q012`: cộng phạm vi E8:E16 ra 51 thay cho 35; rủi ro cộng chồng Total/nhóm tuổi.
- Public `p4_q016`: chương trình chọn trong cả hàng Total và khai báo evidence thiếu ô header; verifier từ chối, đáp án trống.
- Candidate holdout sai `unseen-015`: 98 thay cho 62; rủi ro lựa chọn/ngày tham chiếu. Không sửa prompt theo lỗi này rồi chạy lại holdout.
- Sáu biến đổi kiểm tra đổi tên ID/file/sheet, dịch qua dòng 300, đảo cột, bảng nhiễu và thay số liệu có oracle độc lập. **Gemini sinh mới 5/6**; trường hợp đảo cột sinh `next(...)`, executor chưa hỗ trợ nên thất bại.

Sau khi đóng băng và đo holdout, đã thêm cờ `iterator_helpers=True` hỗ trợ `next`/`iter` và generator lazy trong AST worker. Cờ **mặc định tắt**, không có trong CLI nộp thi. Kiểm tra scope, short-circuit trước lỗi chia 0, iterator rỗng/default và chặn introspection đều đạt. Replay sáu chương trình đã lưu đạt **6/6**, chỉ chạy tính toán/format; không chạy lại LLM hoặc toàn bộ kiểm chứng chọn nguồn. Không thay điểm Gemini 5/6 hay holdout 17/18 bằng điểm replay.

Không thêm luật theo ID, tên file hoặc đáp án. Gold chỉ vào evaluator. Tuning lấy từ các họ synthetic đã biết; 18 câu holdout thuộc họ khác, không dùng để chọn prompt. Candidate lock lưu hash source, transport, helper và manifest holdout trước khi chấm holdout. Receipt chặn tái sử dụng bộ này như holdout độc lập trong lần lựa chọn mới. Nguồn thật đã đánh giá được giữ trong `evaluated_source/`; bản giao có thêm cờ executor tắt mặc định và sửa ghi RSS. Đây là thay đổi sau lock, chưa được LLM xác nhận.

## Hạn mức và trạng thái Qwen

Hai batch hữu hạn, mỗi batch trần 30 phút / 200 inference HTTP attempts / 2 triệu token:

- Baseline/sàng lọc: 170 attempts, dự toán token sau đối soát 1.154.363.
- Validation/holdout: 127 attempts, dự toán token sau đối soát 785.913.
- Hai request chẩn đoán giao thức đầu tiên được giữ riêng trong `diagnostic_batch.json`. Các lần ngắt/resume giữ dự toán cho request chưa biết usage. Không mở batch thứ ba hoặc chạy lại holdout sau sửa mã.

Gateway được coi miễn phí **theo xác nhận của người dùng**; API không trả trường `usage.cost`, do đó không giả mạo chi phí API xác nhận bằng 0. Giá trị ước tính là 0, trường provider cost là null. Nếu báo giá dương, batch dừng để đối soát. Sổ chi phí phát triển bảo thủ hiện là 0.3179270045/0,50 USD, giữ nguyên lịch sử trước đợt này.

Qwen signoff kiểm tra số dư: tổng credit 0, usage 0,200794792 USD. Không bắt đầu inference, số câu Qwen sinh mới **0**. Dự trù 0,05 USD cho signoff chưa dùng; không fallback sang Gemini để thay kết quả Qwen. Không promote C hoặc cờ iterator. Chưa thử concurrency 1/2/4 vì bước đó phụ thuộc Qwen xác nhận. Dữ liệu public đợt 2 ngày 16/10 chưa đánh giá. Cần xác nhận Qwen và một holdout mới trước khi kết luận về cấu hình cải tiến tiếp theo.

`submission.csv` ở gốc vẫn là tệp lịch sử Qwen 20/20; kiểm tra lại bằng evaluator đạt 20/20 **không phải một lượt LLM mới**. Các benchmark Gemini nằm trong thư mục riêng, không ghi đè bài nộp.

## Kiểm thử và bàn giao

- `pytest -q`: **161 passed in 13.49s**.
- `ruff check run.py evaluate.py src tests benchmarks`: **All checks passed!**.
- `ruff format --check run.py evaluate.py src tests benchmarks`: **34 files already formatted**.
- Bao gồm test gateway JSON/SSE, usage thiếu, 429/5xx, timeout, 401/402/403, chi phí dương, quota, checkpoint/hash, resume không gọi lại câu xong, contract C và iterator.
- ZIP thi: **104.353 byte**, 31 file; SHA-256 `4a761e248333f17d64e1ece16f04b24e8f9f42c6d1d7d9bd414cdf6f19d50910`.
- Kiểm tra ZIP không có `.env`, khóa thật, model, notebook, công cụ Colab, dependency GPU, môi trường ảo hoặc cache. Giải nén ở thư mục tạm: mock integration **2/2** với ID/file/sheet/đường dẫn mới có dấu cách; không gửi request mạng. Đây là kiểm tra tích hợp, không phải benchmark Qwen.

Bằng chứng: `summary.json`, `release_summary.json`, `candidate_lock.json`, từng `checkpoint.json`/`report.json`, `qwen_signoff.json`, `iterator_replay.json`, `final_tests.txt`, `package_verification.json`. ZIP ở `dist/table_qa_submission.zip`. Mục tiêu điểm tối đa chưa đạt; không có dữ liệu private để bảo đảm mức tối đa.
