# Tối ưu độ chính xác và kiểm tra tổng quát hóa — 15/10/2026

**Public đã đạt 20/20 trong hai lượt Gemini sinh mới, đồng thời 20/20 sau đổi toàn bộ ID/file/sheet và dịch bảng.** Validation đã biết đạt 18/18, biến đổi tổng hợp 6/6. Holdout mới tăng từ 22/24 lên 23/24; chưa có bằng chứng đạt tối đa trên private thật. Bản sửa hợp đồng dấu sau đánh giá đạt 24/24 bằng replay trên bộ đã tiêu thụ, không gọi đó là holdout độc lập mới.

## Các phép đo sinh mới

Model yêu cầu `ag/gemini-3-flash`, response model `gemini-3-flash`. Candidate: system prompt đầy đủ, compact giữ tọa độ/kiểu/merge/đơn vị, hợp đồng helper/JSON ở user message, thinking `low` được gateway nhận, temperature 1.0, output 2.048, concurrency 2, iterator helpers bật. Không dùng CSV lịch sử thay cho các lượt dưới đây.

| Bộ kiểm tra | Exact Match | TB giây/câu | Tổng giây | Token API nhận được | HTTP attempts |
| --- | --- | --- | --- | --- | --- |
| Public — lượt 1 | 20/20 | 13.80 | 161.32 | 210,653 | 26 |
| Public — lượt 2 | 20/20 | 7.87 | 79.37 | 229,346 | 25 |
| Public đổi bố cục | 20/20 | 5.62 | 67.56 | 219,518 | 23 |
| Validation đã biết | 18/18 | 5.71 | 51.99 | 131,472 | 26 |
| Biến đổi tổng hợp | 6/6 | 2.71 | 8.40 | 25,319 | 6 |
| Holdout mới — đối chiếu C | 22/24 | 5.57 | 81.25 | 132,163 | 31 |
| Holdout mới — candidate | 23/24 | 5.59 | 84.78 | 141,866 | 33 |

So với candidate Gemini lượt trước (17/20 public, 17/18 validation đã biết, 5/6 biến đổi), độ đúng đã tăng lên 20/20, 18/18 và 6/6. Hai lượt public gốc là hai lần sinh riêng; bản đổi bố cục dùng cùng nội dung/oracle public nên **không phải 20 câu độc lập ngoài mẫu**. Bộ 24 synthetic cũ đạt 24/24 sinh mới ở lượt trước sửa kiểm chứng cực trị/lookup; bản cuối giữ 24/24 qua replay, không nhận là một lượt sinh mới của bản cuối.

Thời gian public dao động 7,87–13,80 giây/câu, tổng 79,37–161,32 giây/20 câu. Độ trễ API và retry gây biến động; **không tuyên bố tốc độ luôn tốt hơn** lượt cũ 10,62 giây/câu. Theo đề, tăng Exact Match được ưu tiên trước tốc độ. Lượt public mới ghi nhận 210.653 và 229.346 token, so với 249.821 ở candidate cũ; vì request lỗi thiếu usage, đây là tổng API đã nhận, chưa chứng minh tổng token thực sự giảm đúng tỷ lệ đó.

Số request thiếu usage: public lượt 1/2 là 4/2; public đổi bố cục 1; validation/biến đổi tổng hợp 0/0; holdout candidate/baseline 2/1. Batch giữ dự trù bảo thủ cho phần thiếu. RSS đỉnh đo trên candidate holdout 100,66 MiB; các bộ còn lại khoảng 82–87 MiB. Không suy ra tốc độ OpenRouter hay máy BTC từ máy phát triển/gateway này.

## Sửa nguyên nhân, không thêm luật theo câu mẫu

1. **Đơn vị:** hợp đồng yêu cầu giữ thang số của bảng, chỉ đổi khi câu hỏi yêu cầu tường minh. “Chỉ số nguyên, không kèm đơn vị” không có nghĩa tự nhân 1.000. Câu yêu cầu actual USD thay cho thousand USD vẫn phải đổi; holdout mới có cả hai trường hợp.
2. **Phạm vi cộng:** phát hiện khoảng tuổi chồng lấn, không cộng đồng thời 16–19 với 16–17/18–19. Khi chỉ có một cột và một vùng bảng đủ bằng chứng, dùng total công bố kể cả model bỏ sót ô total. Không tự áp total khi hỏi leaf hoặc yêu cầu bỏ total. Kiểm thử dùng số liệu khác và dịch xuống dòng 310; không có quy tắc theo ID/tên file.
3. **Cực trị theo category:** helper `category_rows` loại hàng grand Total/All; các category trung gian vẫn hợp lệ. Nếu nhãn trả về không phải cực trị trong các hàng đủ bằng chứng đã đọc, ứng dụng sinh chương trình tính lại từ tọa độ thật. Từ chối tự sửa khi nhiều cột/vùng, nhãn lặp, tie không rõ hoặc câu hỏi giới hạn phạm vi. Không bỏ nhóm trung gian chỉ vì nó có các nhóm con.
4. **Evidence:** `find_rows` có thể trả nhiều ứng viên, trong khi chương trình chỉ chọn một. `lookup_probe` ghi riêng các nhãn ứng viên, không buộc khai báo chúng như ô số được chọn. Ô số/nhãn được đọc trực tiếp vẫn phải nằm trong evidence. Test chứng minh đọc số ngoài phạm vi tiếp tục bị từ chối. Chương trình sửa do ứng dụng tạo có evidence riêng; trace giữ cả chương trình model gốc.
5. **Hợp đồng JSON:** `null` ở các trường định dạng tùy chọn có mặc định được hiểu là không chỉ định; kiểu sai/giá trị không hỗ trợ vẫn bị từ chối. Điều này tránh ba lượt sửa vô ích cho một phép tính hợp lệ.
6. **Helper/transport:** iterator lazy và `next` có giới hạn, giữ scope, không đọc phần tử sau kết quả đầu khi chưa cần. SSE kết thúc khi đã có finish reason và usage, không phải chờ proxy đóng kết nối. Thiếu usage không bị ghi thành dùng 0 token.

Bản system prompt rút gọn cũng từng đạt public 20/20 nhưng validation còn lỗi coi danh sách phẳng là bảng hai chiều. Bản đầy đủ được giữ để ưu tiên độ đúng; không chọn bản rút gọn chỉ để ít token hơn. Các lỗi ở lượt lặp lại đã được tái hiện bằng regression; không chỉ lấy một lượt public tốt rồi dừng.

Quét inference `run.py` và `src/*.py` không có ID public, tên workbook public hoặc đọc `sample_submission.csv`. Khi giải nén ZIP ở thư mục tạm không chứa bộ public/gold, CLI candidate vẫn tạo CSV hợp lệ trong phép thử mock. Oracle chỉ vào evaluator; không có tra đáp án theo ID/path. Đây là bằng chứng về triển khai, không phải chứng minh thống kê rằng không thể overfit.

## Tính độc lập của holdout và sửa sau đánh giá

24 câu thuộc bốn workbook mới: định danh trùng/ô thiếu, ma trận tra cứu theo scenario, đối soát tồn kho và kỳ tài chính với thang đơn vị. Oracle được tính riêng trước chọn candidate, manifest hash đóng băng. Workbook/biến thể của chúng không xuất hiện trong tuning. Các phép toán cơ bản vẫn có thể trùng kiến thức ở public; bộ này không được coi là đại diện chắc chắn cho phân phối private.

Sau khi khóa source/prompt/transport, candidate được đánh giá đúng một lần: **23/24**; C đối chiếu cùng executor đạt **22/24**. Không điều chỉnh rồi chạy lại và gọi kết quả đó là holdout mới. Lỗi còn lại là trả `-8` khi câu hỏi yêu cầu positive magnitude `8`.

Sau đó mới thêm chuẩn hóa dấu theo yêu cầu tường minh của câu hỏi; “keep/retain its sign” được ưu tiên giữ dấu, không áp tuyệt đối tùy tiện. Test dùng nhiều số âm/dương/0 độc lập. Đồng thời thêm guard tôn trọng leaf-only khi sửa total. Các sửa này nằm ở lock/source mới riêng, chưa có phép đo LLM ngoài mẫu mới. Điểm độc lập vẫn là 23/24.

Replay toàn pipeline trên các chương trình đã lưu, không gọi LLM:

| Bộ sau sửa | Replay |
| --- | --- |
| public | 20/20 |
| known_validation | 18/18 |
| synthetic | 24/24 |
| metamorphic | 6/6 |
| public_mutation | 20/20 |
| consumed_holdout_validation | 24/24 |

Tổng replay **112/112**, không đổi tên thành độ chính xác sinh mới. Bản được đo độc lập giữ trong `frozen_proof/evaluated_source/`; bản sau sửa có `post_holdout_candidate/candidate_lock.json`. Dữ liệu public đợt 2 chưa có trong workspace để kiểm tra ngoài mẫu tiếp theo.

## Giới hạn thử nghiệm và Qwen

Các đợt đều hữu hạn, giữ nhật ký cả lần dừng giữa chừng khi phát hiện lỗi validation đã biết:

- Tuning: 197/200 attempts, dự toán token sau đối soát 1.306.488/2.000.000.
- Validation/sửa lỗi trước holdout: 157/200 attempts, dự toán 1.179.152/2.000.000.
- Proof cuối: 170/180 attempts, dự toán 1.353.943/2.000.000; không mở vòng tuning sau holdout.

Mỗi batch có deadline 30 phút, query vẫn tối đa ba lượt sinh/sửa/kiểm chứng và năm HTTP attempts. Mọi lượt thử bị dừng được giữ nguyên evidence và không được xếp như một benchmark hoàn tất. Gateway được coi miễn phí **theo xác nhận của người dùng**; API không trả `usage.cost`, nên provider cost là unknown/null, không nhận là API xác nhận miễn phí. Không quan sát chi phí dương; guard sẽ dừng nếu có. Sổ phát triển bảo thủ giữ nguyên 0.3179270045/0,50 USD.

OpenRouter preflight tiếp tục trả total credits 0 USD; **Qwen sinh mới 0 câu**. Không tự chuyển endpoint/model để gọi đó là xác nhận Qwen. Chưa đánh giá concurrency 1/2/4 trên Qwen. Chọn cấu hình nộp chính thức vẫn phải qua Qwen, theo EM → thời gian → token và không suy giảm từng bộ. Không bảo đảm điểm tối đa trên tập ẩn.

## Bàn giao và chạy

- **182 tests passed**, Ruff check/format đều đạt (44 file).
- Candidate ZIP: **131,223 byte**, 41 file; SHA-256 `91e6fd646ea41c05c043cfa78dafa2f84e5d2f79221ed739ed92581d783637a9`.
- Đã giải nén sang thư mục khác, kiểm thử mock CLI chính thức Qwen với ID/file/sheet mới, ô dòng 306, đường dẫn có dấu cách. URL phải là OpenRouter; không gửi request mạng trong mock. Không có `.env`, khóa thật, model, công cụ Colab, dependency GPU, venv/cache trong ZIP.
- ZIP cũ và `submission.csv` lịch sử được giữ nguyên; không ghi đè bằng CSV Gemini.

CLI candidate dùng Qwen qua OpenRouter:

```bash
python -m benchmarks.precision_submission --input-dir /path/to/xlsx_files --queries /path/to/queries.json --output /path/to/candidate_submission.csv
```

Đặt `OPENROUTER_API_KEY` hoặc dùng `--api-key`; không dùng DEV key cho OpenRouter. Giữ trần 0,09 USD/câu, deadline 2.300 giây, concurrency 2 và giám sát RSS 800 MiB. Khi khôi phục credit, signoff đã chuẩn bị:

```bash
python -m benchmarks.qwen_signoff --root reports/optimization/precision_v2/post_holdout_candidate
```

`run.py` vẫn hỗ trợ giao diện cũ và model Qwen mặc định. Candidate chưa được tự promote. Nguồn được đo: `56e89679ea8fdb9b47d48b40e0da0625d774762b36e10ffce9d5113441169244`. Nguồn bàn giao sau sửa dấu/guard: `5ce54085b3a88b487b20f88b83400e367b38c1ad76f8a0faf03b9d79a2d88acb`. Báo cáo thô ở từng `report.json`/`checkpoint.json`, `post_holdout_replay.json`, `inference_leakage_scan.json`, `package_verification.json` và log tests. Mức cải thiện đã chứng minh rõ hơn so với vòng trước; phần xác nhận Qwen/private thật vẫn còn thiếu.
