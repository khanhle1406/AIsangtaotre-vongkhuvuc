# Benchmark và phạm vi bằng chứng hiện tại

Các số dưới đây là **Gemini 3 Flash sinh mới**, không dùng replay làm benchmark LLM. Chúng không chứng minh điểm private của BTC hoặc điểm Qwen3.7 Flash. Ưu tiên Exact Match → thời gian → token.

Mốc public **v52** đạt **20/20 cả ba lần**, trung bình **6,543 giây / 83.712 token**, giảm **73,07% thời gian / 59,86% token** so với baseline cùng đợt. Nhưng ngoài public chỉ đạt **249/254**, thấp hơn mốc 253/254: **chưa chấp nhận cấu hình này**. So với trung bình public v17, mức giảm khoảng **33,94% thời gian / 18,24% token**, chưa đạt 50% so với mốc lịch sử. Lượt mới **v54** đạt public **20, 20, 19**, ngoài public **250/254** và chậm hơn baseline cùng đợt; cũng chưa được chấp nhận. Bản sửa giới hạn kiểm chứng sau v54 mới kiểm thử offline. **Chưa chọn bản nộp** hoặc xác nhận Qwen/private BTC; không ghép điểm từ nhiều phiên để tạo một lượt đủ điểm.

V41 trước đó đạt public 20/20 ba lượt, trung bình 11,007 giây / 126.576,33 token, decision 17/18. Các kết quả này vẫn thuộc snapshot v41, không thay cho đánh giá v44.

Đánh giá decision độc lập trước sửa (source v37) đạt **12/18 ở cả baseline lẫn candidate**, không cải thiện độ đúng/thời gian. Các lần 17/18 sau sửa là hồi quy, không phải kiểm định độc lập mới. V39 đạt public đủ điểm ba lượt nhưng chạm trần 200 attempts giữa chừng; phần chưa chạy không phải câu model trả lời sai. Review audit và các tối ưu mới chưa chuyển thành mặc định thi; chưa xác nhận Qwen/private BTC.

Candidate gần nhất vượt qualification chính và kiểm định độc lập là **v30, low/concurrency 4**. Public 20/20 ba lượt; bộ mới 18/18 so với baseline 17/18. Regression mở rộng sau đó còn một câu lỗi. Public giảm 50,41% thời gian / 44,53% token; kiểm định mới giảm 25,17% thời gian / 57,83% token so với baseline cùng đợt. **Chưa đạt giảm 50% cho cả hai chỉ số trên mọi bộ; chưa vượt v17 về hiệu suất public.** Mọi kết quả thất bại được giữ dưới đây.

## Candidate v17 đã khóa

Nguồn: `reports/optimization/efficiency_v17_regression/summary.json`. Baseline chạy từng câu, concurrency 2; candidate lập chương trình chung tối đa bốn câu/workbook, concurrency 4. Mỗi chương trình tính trên workbook thật và được kiểm tra riêng.

| Bộ | Exact Match | Tổng giây | Token API |
| --- | --- | --- | --- |
| Baseline public | 20/20 | 28,122 | 221.470 |
| Candidate public 1 | 20/20 | 9,507 | 111.419 |
| Candidate public 2 | 20/20 | 8,993 | 99.793 |
| Candidate public 3 | 20/20 | 11,212 | 95.930 |
| Regression 60 | 60/60 | 47,464 | 209.146 |
| Regression 32 | 32/32 | 27,176 | 112.491 |
| Validation đã biết 18 | 18/18 | 4,791 | 43.248 |
| Synthetic đã biết 24 | 24/24 | 10,639 | 59.039 |
| Robustness đã tiêu thụ 24 | 24/24 | 38,237 | 145.919 |

Public trung bình **9,904 giây / 102.380,67 token**, giảm **64,78% tổng thời gian / 53,77% token** so với baseline cùng đợt, không phải so với bản nhanh nhất lịch sử. RSS đỉnh không quá **135,97 MiB**, usage đầy đủ.

## Kiểm định độc lập structural 18

Nguồn: `reports/optimization/structural_v1_proof/summary.json`. Giữ nguyên source v17; dữ liệu đóng băng trước inference. Ba họ mới: FIFO tồn kho, nội suy/tích phân tuyến tính từng đoạn, định mức vật tư nhiều cấp. Oracle dùng công thức tiền tố, phân số chính xác, Counter/Decimal; đáp án chỉ vào evaluator.

| | Baseline | Candidate |
| --- | --- | --- |
| Exact Match | 17/18 | **18/18** |
| Tổng giây | 33,557 | 26,218 |
| Token API | 128.443 | 102.348 |
| HTTP attempts | 26 | 19 |
| Độ trễ trung bình theo trace | 3,676 giây | 5,382 giây |
| RSS tổng đỉnh | 85,06 MiB | 85,56 MiB |

Giảm **21,87% tổng thời gian / 20,32% token**, tăng một câu đúng; chưa giảm 50% trên bộ này. Throughput không đồng nghĩa độ trễ từng câu. Bộ đã tiêu thụ, các lần sau chỉ là regression.

## Giới hạn và thí nghiệm tiếp theo

Kiểm định độc lập robustness trước đó: baseline **23/24**, candidate lúc đó **22/24**. Sửa kiểm tra phạm vi gây review không cần thiết giúp v17 đạt 24/24 trên dữ liệu đã biết; đó không phải kiểm định độc lập lại. V18 bị loại vì regression 60 chỉ đạt 59/60. Giữ nguyên mọi report thất bại.

Theo yêu cầu người dùng, tiếp tục phát triển bằng Gemini. Mọi bộ đã mở đều được ghi là regression ở các vòng sau.

## Thí nghiệm tiếp tục v19/v20

| Đối chiếu sinh mới, cùng 62 câu đã biết | Đúng | Tổng giây | Token |
| --- | --- | --- | --- |
| v19: trước hướng dẫn runtime | 61/62 | 68,293 | 284.524 |
| v19: thêm hướng dẫn runtime | 62/62 | 69,591 | 275.800 |
| v20: cùng runtime, chưa có chỉ dẫn cột | 60/62 | 59,983 | 260.339 |
| v20: thêm chỉ dẫn cột gốc | 62/62 | 37,526 | 222.818 |

V20 chỉ thay phần chỉ dẫn cột; giữ nguyên ví dụ helper, khác với thí nghiệm v18 đã bị loại. Các phép đo luân phiên thứ tự đối chiếu/candidate. Cải thiện ở đây có biến động model/gateway; không diễn giải thành bảo đảm thống kê.

Qualification v20 đạt public **20/20 ở cả ba lượt**, regression **60/60, 32/32, 18/18, synthetic 24/24, robustness 24/24**. Public trung bình **10,692 giây / 110.112,67 token**, so với baseline đủ điểm **29,611 giây / 217.984 token**: giảm **63,89% thời gian / 49,49% token**, chưa đạt giảm token 50%. RSS đỉnh **138,58 MiB**.

Kiểm định độc lập mới `generalization_v1_proof` được khóa sau qualification, gồm phân công một-một tối ưu, hồi quy có trọng số và chuỗi Markov. Oracle độc lập dùng duyệt hoán vị và phân số chính xác; 18 đáp án được kiểm tra tay trong tests.

| Kiểm định độc lập mới | Baseline | Candidate v20 |
| --- | --- | --- |
| Exact Match | 13/18 | 14/18 |
| Tổng giây | 53,388 | 89,472 |
| Token | 201.343 | 208.325 |

**Không chấp nhận v20.** Điểm tăng một câu nhưng vẫn còn lỗi và hiệu suất giảm. Nhiều lỗi do runtime chưa hỗ trợ `itertools.permutations` và hợp tập hợp, dẫn đến sửa nhiều lượt rồi hết ngân sách review. Report thất bại giữ nguyên; bộ 18 này đã tiêu thụ.

## Sửa runtime và loại thí nghiệm rút prompt v21

Bổ sung hoán vị có giới hạn đầu vào/đầu ra, các phép tập hợp chuẩn và làm rõ generator function không được hỗ trợ. Không mở NumPy/SciPy hay thực thi Python tùy ý. Chạy lại nguyên bốn chương trình từng lỗi do thiếu phép toán cho kết quả đúng sau sửa; đây là **replay**, không tính vào độ chính xác LLM sinh mới.

Ablation sinh mới, cùng runtime mới và chỉ dẫn cột:

| Bộ | Hợp đồng đầy đủ | Rút hợp đồng cuối prompt |
| --- | --- | --- |
| Generalization đã biết | 18/18 | 13/18 |
| Structural đã biết | 18/18 | 18/18 |
| Robustness đã biết | 24/24 | 21/24 |
| Public | 19/20 | 20/20 |
| Toàn bộ | **79/80** | **72/80** |
| Token toàn bộ | 399.543 | 536.992 |

**Loại bản rút hợp đồng**; giảm đầu vào không đồng nghĩa giảm tổng token khi lỗi/sửa tăng. Prompt đầy đủ cũng có một lỗi public nên chưa được chấp nhận qua gate. Không dùng lượt public đủ điểm của bản rút gọn để che suy giảm các bộ khác.

V22 giữ hợp đồng đầy đủ, thử kiểm tra phạm vi cột tổng quát. Public **20/20 cả ba lượt**, regression **59/60, 32/32, 18/18, synthetic 23/24, robustness 24/24**. Chưa chấp nhận: một chương trình đếm cả header như bản ghi thiếu số đo; một guard nhầm các measure khác nhau trong cùng năm thành các category cùng loại. Giữ nguyên lỗi và report.

V23 thu hẹp guard: bỏ qua yêu cầu published total, nhánh có measure/category được gọi tên, định dạng số hỗn hợp, parent hoặc ancestry cạnh tranh. Chỉ báo nguồn thiếu, không tự gán đáp án. Thay thế kiểm tra cũ chỉ xét một cột trong riêng câu hỏi industry. Hợp đồng runtime nhắc rõ string-only `data_rows` có thể khớp heading; đếm bản ghi cần cận dữ liệu thật và phải giữ bản ghi có measure trống. Không đổi ngầm ngữ nghĩa helper. Tests dùng ma trận dịch dòng/cột, mixed measures/formats, Total và nhánh cạnh tranh. Source này đang qua qualification; chưa có kiểm định độc lập mới.

## V23–v26: chưa chấp nhận candidate mới

| Source | Ba lượt public | Regression 60 / 32 | Known 18 / synthetic 24 / robustness 24 |
| --- | --- | --- | --- |
| v23 | 20, 20, 20 | 60/60; 31/32 | 18/18; 24/24; 24/24 |
| v24 | 20, 20, 20 | 60/60; 29/32 | 18/18; 24/24; 24/24 |
| v26 | 19, 19, 20 | 59/60; 31/32 | 18/18; 24/24; 24/24 |

V23 public trung bình 16,386 giây / 145.615 token; v24 là 10,479 giây / 113.753,67 token, giảm 62,25% thời gian và 42,68% token so với baseline cùng đợt. Không xem chênh lệch giữa hai đợt này là phép đo nhân quả vì model/gateway có biến động. Chưa bản nào vượt toàn bộ gate độ đúng, nên **không thay candidate v17 đã qua kiểm định** bằng một lượt nhanh riêng lẻ.

V24 chuẩn hóa phản hồi một program khi chỉ có một câu và metadata chung có thể xác minh. Không suy ra program còn thiếu, không bỏ metadata xung đột hoặc `needs_verification`; raw response vẫn lưu. V26 thêm provenance cho list do `cells()` trả về: so sánh nhầm một row/list với scalar trong AST sẽ báo lỗi sửa, thay vì âm thầm trả False rồi đếm 0. So sánh list với list, `values()` phẳng và `cell()` scalar giữ nguyên hành vi.

V25 bị dừng vì một lỗi đặt decorator trong lúc thêm provenance. Lượt đó **không hợp lệ**, không dùng đánh giá chất lượng; receipt lỗi và dự trù usage được giữ. Sau sửa, toàn bộ **258 test** đã qua, Ruff check/format đạt. Chưa có bằng chứng độc lập mới cho các source v23–v26.

V27 sàng lọc tham số Gemini low/medium × concurrency 4/8 trên cùng public 20, challenge 32 và generalization 18 đã biết. Dùng chung trần 30 phút / 200 HTTP attempts / 2 triệu token, giữ nguyên prompt và thuật toán. Lưu effort thực sự yêu cầu; gateway chấp nhận tham số không chứng minh cách model nội bộ áp dụng nó. Không tự đổi mặc định theo một lượt sàng lọc. `run.py` và CLI Qwen vẫn giữ concurrency hiện có.

| V27, tổng 70 câu đã biết | Exact Match | Tổng giây ba bộ | Token API |
| --- | --- | --- | --- |
| low, concurrency 4 | 69/70 | 55,029 | 319.303 |
| low, concurrency 8 | 69/70 | 63,270 | 321.089 |
| medium, concurrency 4 | 69/70 | 83,796 | 282.936 |
| medium, concurrency 8 | **70/70** | 111,965 | 409.138 |

Usage đầy đủ. RSS đỉnh cả đợt **138,38 MiB**. Chọn medium/8 để **xác nhận tiếp**, chưa chấp nhận làm mặc định: nó đủ điểm trong lượt sàng lọc nhưng chậm gấp khoảng hai lần low/4 trên tổng ba bộ. Không có cải thiện hiệu suất 50% ở đợt này. V28 chạy lại qualification đầy đủ với cấu hình đã khóa medium/8; bộ kiểm định mới, nếu mở, phải giữ đúng cấu hình đã qua qualification.

V28 không đạt: public **19/20, 18/20, 19/20**, còn các regression **60/60, 32/32, 18/18, 24/24, 24/24**. Lỗi public lặp lại chọn Total toàn bảng thay cho nhánh con được hỏi; không dùng kết quả sàng lọc 70/70 để thay kết quả xác nhận này.

V29 mở rộng kiểm tra tên cột sang caption cha của một nhánh, thay vì chỉ caption lá: khi câu hỏi gọi tên hai nhánh tách rời, phải đọc dữ liệu trong cả hai nhánh. Cùng caption dưới ancestry cạnh tranh không được suy đoán. Không chọn hộ giá trị hoặc cột theo ID/đáp án. Test dùng bảng mới với nhánh cha gộp, Total/child và caption trùng dưới hai ancestry. **260 test**, Ruff check/format đã đạt trước khi khởi động qualification v29.

## V30: candidate Gemini qua kiểm định mới

V29 đạt public 20/20 ba lượt nhưng còn 17/18 ở known và 23/24 ở synthetic, nên chưa được chấp nhận. V30 bổ sung các thao tác chuẩn an toàn (`filter`, `map`, unbound string methods đã được phép, nhóm regex); thông báo rõ cách gọi constructor datetime. Giữ giới hạn AST, thời gian/bộ nhớ và cấm I/O/introspection. Nhận dạng cộng/nhân tích lũy bằng vòng lặp tương đương aggregation trong một bảng phẳng đã xác minh, tránh review nhầm nhãn bản ghi lặp thành các section khác nhau. Trường hợp lookup mơ hồ hoặc qualifier sai vẫn bị kiểm tra. Tests dùng dữ liệu mới và đối chiếu tra cứu mơ hồ.

Nguồn: `efficiency_v30_low4/summary.json` và `compositional_v1_proof/summary.json` dưới `reports/optimization`. Source/config được khóa trước inference, không đổi khi đánh giá bộ mới.

| Bộ v30 | Exact Match | Tổng giây | Token API |
| --- | --- | --- | --- |
| Baseline public | 20/20 | 26,571 | 198.054 |
| Candidate public 1 | 20/20 | 19,748 | 112.116 |
| Candidate public 2 | 20/20 | 7,482 | 87.844 |
| Candidate public 3 | 20/20 | 12,303 | 129.604 |
| Regression 60 | 60/60 | 31,748 | 164.332 |
| Regression 32 | 32/32 | 9,525 | 64.524 |
| Known 18 | 18/18 | 6,545 | 43.166 |
| Synthetic 24 | 24/24 | 10,140 | 51.935 |
| Robustness đã biết 24 | 24/24 | 7,254 | 35.158 |

Public trung bình **13,177 giây / 109.854,67 token**; không loại lượt chậm khỏi trung bình. RSS đỉnh qualification **135,14 MiB**. So với v17 (9,904 giây / 102.380,67 token), public chưa nhanh hơn; v30 có thêm các sửa lỗi tổng quát và bằng chứng trên họ bài mới.

Kiểm định độc lập gồm đường găng DAG, tương quan hạng có ties và relational division. Oracle lần lượt duyệt đường đi độc lập, so sánh hạng từng cặp bằng Fraction và SQLite, được kiểm tra tay trước inference. Bảng/cột được dịch, đảo và có archive nhiễu. Không dùng đáp án để chọn dữ liệu hay sinh code.

| Kiểm định compositional 18 | Baseline | Candidate |
| --- | --- | --- |
| Exact Match | 17/18 | **18/18** |
| Tổng giây | 38,904 | 29,111 |
| Token API | 150.339 | 63.404 |
| HTTP attempts | 30 | 10 |
| Độ trễ trung bình theo trace | 4,107 giây | 5,232 giây |
| RSS tổng đỉnh | 76,78 MiB | 102,67 MiB |

Baseline đã chạy đủ 18 câu nhưng một câu hết lượt sửa do import không được hỗ trợ; không phải lỗi mạng. Vì vậy `generation_complete=true`, còn `complete=false` theo định nghĩa không có lỗi của harness; candidate không lỗi. Usage đầy đủ, không thay token thiếu bằng 0. Giảm tổng thời gian thể hiện throughput; không khẳng định giảm độ trễ từng câu. Bộ này đã tiêu thụ, chỉ được dùng như regression từ đây.

Nghiệm thu mã hiện tại: **263 test passed**, Ruff check và format đạt. Cần tiếp tục giảm retry/import không hỗ trợ và kiểm chứng bằng Qwen trước khi chọn gói thi cuối. Chi phí phát triển gateway được coi miễn phí theo xác nhận người dùng, tách khỏi cost do API báo; đợt này không gọi Qwen trả phí.

Kiểm tra thêm cùng source/config, sau khi kiểm định mới đã kết thúc:

| Regression mở rộng | Exact Match | Tổng giây | Token |
| --- | --- | --- | --- |
| Structural đã dùng | 18/18 | 13,792 | 90.065 |
| Generalization đã dùng | 17/18 | 33,172 | 95.054 |
| Transfer đã dùng | 24/24 | 6,679 | 44.363 |

Một câu generalization có chương trình đầu tính đúng nhưng bị review do nhiều tên dimension xuất hiện trong câu hỏi bị xem như điều kiện AND trên từng bản ghi. Các lượt sửa tiếp theo dùng NumPy không được hỗ trợ rồi nhầm `cells()[0]` với scalar. Đây là lỗi còn mở, không xóa khỏi thống kê hoặc coi 18/18 ở lượt khác là thay thế. Qualification chính đạt 158/158 regression; kiểm tra mở rộng đạt 59/60, tổng **217/218 câu đã biết**, tách khỏi public lặp và 18 câu độc lập mới. Tập độc lập mới đã tiêu thụ; mọi sửa theo lỗi của nó cần một kiểm định mới.

ZIP phát triển đã được giải nén ở thư mục riêng, không mang khóa môi trường: **245 test passed**, Ruff check/format đạt; 18 test Colab được loại khỏi gói cùng các công cụ GPU. ZIP nguồn khoảng 0,25 MB, có quét khóa thật trong `.env`, không đóng gói `.env`, dữ liệu/đáp án, model, cache hoặc môi trường ảo. Đây là candidate phát triển, chưa phải xác nhận nộp thi cuối.

Qwen signoff chưa gọi inference trả phí: preflight tín dụng dừng trước request, `new_generations=0`, `promoted=false`. `run.py` giữ model thi và cấu hình mặc định. Chi phí Gemini bằng 0 theo xác nhận của người dùng; không gọi đó là chi phí đo được khi API không báo cost.

## V31–v34: sửa hợp đồng và đo review

V31 còn lỗi public nhân đơn vị qua đầu ra chuỗi, synthetic chọn cột năm khác và review thay chương trình BOM đúng bằng phép nhân đơn giá lần hai. V32 giữ nguyên các lượt sai, bổ sung guard đơn vị cho đầu ra số dạng chuỗi, kiểm tra năm ở lookup, giữ dimension theo cột (OR trong một dimension, AND giữa các dimension) và chẩn đoán import cụ thể. Không sửa giá trị dựa trên đáp án.

V32 sinh mới: public **20/20 cả ba lượt**, trung bình **12,997 giây / 127.181,67 token**, RSS đỉnh **126,53 MiB**; baseline 20/20, **25,028 giây / 189.597 token**. Giảm **48,07% tổng thời gian / 32,92% token**. Toàn bộ hồi quy đã biết **232/236**; vì vậy chưa chấp nhận candidate. Thời gian toàn bộ chia số câu là throughput, không đồng nghĩa độ trễ từng câu.

V33 sửa thêm hai đường lỗi chung: phép membership so sánh hàng 2D với danh sách scalar phải báo lỗi kiểu thay vì âm thầm bỏ hết bản ghi; phép đếm chênh lệch hai bộ lọc kiểu phải phát hiện tiêu đề bị tính thành bản ghi thiếu số đo. Helper vẫn giữ ngữ nghĩa và có kiểm tra cận dòng đúng. Replay chương trình đếm cũ xác nhận guard bắt được header; replay không tính vào điểm sinh mới.

So sánh review trên cùng runtime và 116 câu đã tiêu thụ; luân phiên thứ tự chính sách theo bộ, dùng chung trần 30 phút / 200 HTTP attempts / 2 triệu token:

| Chính sách | Exact Match | Tổng giây | Token API |
| --- | --- | --- | --- |
| Chọn lại từ workbook, không kèm code | 114/116 | 72,575 | 431.725 |
| Audit code chưa được xác minh, không kèm đáp án đã tính | 116/116 | 78,267 | 460.698 |

Audit tăng hai câu đúng trong lượt sàng lọc, đổi lại tăng 7,84% thời gian / 6,71% token. Usage đầy đủ; RSS đỉnh đợt so sánh 135,625 MiB. Đây là một lượt A/B có biến động model/gateway, không phải chứng minh nhân quả hoặc dữ liệu độc lập. Chọn audit để xác nhận vì đề ưu tiên Exact Match; chưa đổi mặc định.

V34 xác nhận bằng public lặp và toàn bộ 236 câu hồi quy, khóa source/config có cả chính sách review. Kết quả public 20/20, 19/20, 20/20 và structural 17/18 đã đủ để loại candidate khỏi bước kiểm định độc lập. Lỗi public đọc subgroup full-time của một nhánh metric thay cho nhánh tổng thể; lỗi FIFO chọn đơn hàng được cấp một phần thay vì đơn đầu tiên không được cấp gì. Không lấy điểm 116/116 của sàng lọc để che các lỗi này.

Nghiệm thu mã: **274 test passed**, Ruff check/format đạt. Không có inference Qwen trả phí trong giai đoạn này; tiếp tục Gemini theo yêu cầu người dùng. Không tự chuyển model hoặc dùng đáp án/ID trong inference. Chi phí gateway 0 là theo xác nhận người dùng, tách khỏi usage.cost do API báo; usage thiếu không được thay bằng 0 token.

V34 đã kết thúc: **235/236 hồi quy**, public **59/60 trên ba lượt**. Public trung bình **10,214 giây/20 câu** (throughput **0,511 giây/câu**) và **121.122 token/20 câu** (**6.056,1 token/câu**); baseline đủ điểm là 23,205 giây / 198.389 token. Giảm **55,98% thời gian / 38,95% token**, nhưng không chấp nhận đánh đổi một câu sai. Độ trễ trung bình trace public là **2,699 giây/câu**, không phải 0,511 giây. Báo cáo máy: `reports/optimization/GEMINI_CONTINUATION_V34.json`. Không có kiểm định độc lập mới trong v31–v34.

## V35–v37: giữ độ đúng khi thử tiết kiệm token

Tín hiệu review mới kiểm tra chỉ tiêu cha được gọi tên trong dấu nháy, có cột tổng thể và cột subgroup: chương trình đọc riêng subgroup không được hỏi sẽ cần xác minh. Phần numeric header của các subgroup dọc có thể kế thừa header sheet; định nghĩa cột local vẫn ghi đè. Đây là tín hiệu mềm, không ép chọn Total hay gán giá trị. Test dùng tên metric, subgroup và tọa độ mới, gồm yêu cầu subgroup hợp lệ.

V35 thử A/B/C với cùng runtime, audit và 80 câu đã biết; luân phiên thứ tự các cấu hình giữa bộ:

| Cấu hình | Exact Match | Tổng giây | Token |
| --- | --- | --- | --- |
| A: biểu diễn hiện tại | 80/80 | 69,394 | 407.160 |
| B: tham chiếu header trùng hoàn toàn | 79/80 | 39,406 | 262.653 |
| C: B + nhắc kiểm tra điều kiện đầu ra | 79/80 | 53,109 | 305.887 |

B giảm 8,39% byte workbook public trong phép đo offline và giảm 43,21% thời gian / 35,49% token trong lượt sinh mới này, nhưng **chưa chọn B/C vì độ đúng thấp hơn**. Chênh lệch tổng token gồm cả biến động retry, không chỉ phần metadata. Biểu diễn tham chiếu có kiểm thử khôi phục đầy đủ ô/kiểu/merge/header và không sửa backend. Các tùy chọn vẫn tắt mặc định.

V36 chuẩn hóa giả định dạng cặp khóa câu hỏi chỉ khi có ánh xạ một-một đầy đủ tới các khóa đã yêu cầu. Không đoán bằng thứ tự, không bỏ metadata lạ/trùng/thiếu, không bỏ `needs_verification`, không sửa code. Replay giữ nguyên chương trình sai đơn vị và guard vẫn từ chối nó. V36 public 20/20 cả ba lượt; hồi quy **233/236**. Public trung bình **13,083 giây / 115.932,33 token**, so với baseline 26,488 giây / 220.132 token: giảm 50,61% thời gian / 47,34% token. RSS đỉnh 134,59 MiB. Chưa đạt mục tiêu giảm cả hai 50%, không mở holdout.

V37 bổ sung `list.insert` chuẩn Python có giới hạn số phần tử. Phát hiện chương trình dùng `[0]` trên scalar string của `values()` trước join/filter, khiến nhãn bị cắt thành ký tự đầu rồi trả 0; yêu cầu review khi câu hỏi không yêu cầu trích ký tự/initial/prefix. Không cấm Python string indexing, không tự đổi 0 thành đáp án. Test xác nhận ý định lấy initials vẫn được giữ. Replay chương trình đường găng từng bị chặn bởi insert trả đúng; replay hai chương trình trả 0 nay tạo tín hiệu review. Đây không phải benchmark LLM sinh mới.

V37 sinh mới: public **20/20, 20/20, 20/20**; regression60 60/60, regression32 32/32, known18 **17/18**, synthetic24 24/24, structural18 18/18, generalization18 18/18, transfer24 24/24, compositional18 **17/18**, robustness24 24/24. Tổng hồi quy **234/236**. Hai lỗi còn lại: ghép ngày thuộc hai bản ghi khác nhau; backtrack critical path theo thời điểm bắt đầu thay vì kết thúc predecessor. Candidate vẫn bị loại; không lấy public đủ điểm để che lỗi còn lại.

Bộ mới `decision_v1_holdout` gồm 18 câu/ba workbook: minimum set cover, conditional Bayesian evidence và effective-dated interval join. Oracle độc lập lần lượt duyệt toàn bộ tập con, xác suất liên hợp bằng Fraction, SQL interval join cộng số học phân số; 18 đáp án đã kiểm tra tay trong tests. Dữ liệu được dịch/đảo cột và thêm archive nhiễu, manifest đóng băng trước inference. **Chưa chạy model, chưa có receipt đánh giá**, vì candidate chưa vượt toàn bộ qualification. Không thêm helper hay luật suy luận cho ba họ này.

**287 tests passed**, Ruff check/format đạt. Không gọi Qwen trả phí trong vòng này. Báo cáo máy đầy đủ: `reports/optimization/GEMINI_CONTINUATION_V37.json`. Goal vẫn active; chưa hoàn thành mục tiêu độ đúng và hiệu suất.

## Decision assessment, v39–v41 và giới hạn vận hành

Bộ decision 18 câu đã được mở **một lần** trên source v37 đóng băng. Vì qualification còn lỗi, lượt này có `assessment_only=true`, giữ nguyên hai báo cáo qualification sai và bị cổng Qwen từ chối trước network. Đây là phép đo độc lập của source chưa đạt yêu cầu, không phải vượt cổng nghiệm thu.

| Decision độc lập trước sửa | Exact Match | Tổng giây | Token |
| --- | --- | --- | --- |
| Baseline | 12/18 | 44,900 | 167.086 |
| Candidate v37 | 12/18 | 54,852 | 144.975 |

Cả 18 câu đều đã được gọi model; sáu lỗi mỗi nhánh là lỗi code/runtime, không phải API. Không có cải thiện độ đúng hoặc thời gian; token giảm 13,23%. Source/runtime hiện tại đã khác, nên bằng chứng này không chứng minh độ đúng của source mới. Bộ đã tiêu thụ, không được gọi lại là unseen bằng cách đổi seed, file hoặc tên dataset.

Runtime được bổ sung `set.update`, quan hệ tập hợp và dịch bit chuẩn Python, có giới hạn bước, số phần tử và số bit trước phép dịch trái (kể cả `<<=`). Bổ sung lỗi kiểu khi so sánh `datetime` với chuỗi ISO để tránh điều kiện luôn False rồi trả 0; cách so sánh ngày/ngày hoặc ISO/ISO vẫn giữ. Đây là thay đổi phép toán và hợp đồng kiểu, không có lời giải riêng cho set cover/Bayes hay ID câu hỏi.

Các lượt **sinh mới trên bộ đã biết**: v39 decision 17/18, v40 14/18, v41 17/18. Không chọn riêng lượt tốt để thay lịch sử. V40 public 18/20, 20/20, 20/20: một kế hoạch sai envelope làm hai câu phải sửa riêng; một chương trình đọc đủ các cột rồi chỉ lấy cột lá để tính mean, vượt qua kiểm tra read coverage. V41 kiểm chứng giá trị trung bình của nhánh ALL đã xác định rõ, thay vì coi đọc đủ ô là dùng đủ toán hạng. Tự tính lại từ workbook khi sai và không có yêu cầu weighted/leaf/chuyển đơn vị/phần trăm lưu dạng fraction; dùng cùng hợp đồng định dạng để tránh sửa vì khác số chữ số. Test dùng bảng mới và các trường hợp không được tự ghi đè. Replay chương trình mean cũ trả đúng 3.14 không thêm phản hồi model; replay không tính vào benchmark.

V39 chạm **200 HTTP attempts**, 1.351.779 token dự trù/đã biết. Transfer chỉ chạy một phần; compositional và robustness có **0 HTTP attempts**, nên **chưa đánh giá**, không phải chất lượng 0 điểm. Giữ nguyên report/CSV gốc và bổ sung phân loại trong `GEMINI_CONTINUATION_V41.json`. Harness đã sửa để dừng trước dataset mới và ghi `unassessed`; thiếu stage không thể làm qualification tự vượt qua. Không reset v39 hoặc mở thêm lượt để điền kết quả thiếu. Các phép đo sau đó dùng source mới với thay đổi kiểu/bit/mean và phạm vi riêng, không thay thế qualification thiếu.

V39 public lượt ba mất 62,265 giây vì một URLError/retry; giữ nguyên trong trung bình. Request đó thiếu usage: report ghi 129.659 token đã biết và trần dự trù 158.155, không ghi request lỗi dùng 0 token. Lượt mạng lỗi không dùng làm bằng chứng model hiểu sai; thời gian vẫn là chi phí vận hành thực tế.

| V41 sinh mới, xác nhận tập trung | Exact Match | Tổng giây | Token |
| --- | --- | --- | --- |
| Baseline public | 20/20 | 23,638 | 190.230 |
| Public 1 | 20/20 | 9,428 | 121.359 |
| Public 2 | 20/20 | 11,710 | 145.705 |
| Public 3 | 20/20 | 11,883 | 112.665 |
| Decision hồi quy | 17/18 | 31,300 | 148.408 |

Public trung bình **11,007 giây / 126.576,33 token**, tương đương throughput **0,550 giây / 6.328,82 token mỗi câu**; độ trễ trung bình trace **2,862 giây/câu**. Usage đầy đủ, RSS đỉnh **120,06 MiB**. Giảm 53,44% tổng thời gian và 33,46% token so với baseline cùng đợt. V17 vẫn nhanh hơn về public; v41 không phải kỷ lục mới. V41 là diagnostic regression, không có lock qualification đủ stage; không thể dùng thay toàn bộ 254 câu hồi quy hoặc làm cổng chốt bài.

**293 tests passed**, Ruff check/format và `git diff --check` đạt. Còn lỗi scalar unpacking/indexing ở decision-003; lỗi binding hai ngày khác bản ghi và backtrack objective còn cần đánh giá lại. Không gọi Qwen trả phí, không đổi mặc định model thi. Bằng chứng máy và mọi lượt thất bại nằm trong `reports/optimization/GEMINI_CONTINUATION_V41.json`.


## V42–v44: kiểu dữ liệu, miền dữ liệu và ràng buộc nhãn

V42 so sánh system prompt đầy đủ và rút gọn trên cùng 92 câu đã biết, luân phiên thứ tự theo bộ, giữ nguyên hợp đồng ngữ nghĩa và runtime. Full đạt **89/92, 60,910 giây, 366.762 token**; lean đạt **83/92, 128,345 giây, 415.387 token**. Loại lean: giảm input nhưng tăng lỗi và lượt sửa; không chọn chỉ dựa vào public đủ điểm hoặc token đầu vào.

Sửa lỗi shape của `values`/`cells` bằng chẩn đoán có biểu thức và dòng lỗi. Chỉ sau lỗi unpack thực tế, ứng dụng có thể đổi `values` thành `cells` khi chiều rộng vùng bằng số biến unpack, nguồn/alias không có cách dùng cạnh tranh và không phải yêu cầu tách ký tự. Giữ nguyên tọa độ, giá trị và trace code gốc; chương trình sửa chạy lại trong worker và qua toàn bộ guard. Replay decision-003 v41 trả đúng sau một phản hồi giả lập: đây là kiểm thử offline, không phải độ đúng Gemini sinh mới.

Bổ sung soft review khi `data_rows` string-only không có cận đưa ô đầu bảng có dấu hiệu tiêu đề vào miền required/coverage/count. Không bỏ ngầm hàng đầu, không khẳng định schema cho bảng toàn text. V43 vẫn còn lỗi sau review: kiểm chứng thêm chưa bảo đảm model sửa đúng.

V43 public **20/20, 19/20, 20/20**, decision **16/18**; public trung bình 21,355 giây / 129.486,67 token. Lỗi rank: số được đọc từ các hàng đúng nhưng nhãn literal được ghép theo thứ tự khác. V44 kiểm tra nhãn–giá trị theo hàng nguồn khi chỉ có một measure, nhãn phân biệt, khóa sort bằng số nguồn và chiều xếp hạng rõ ràng. Không ép kiểm tra khi nhãn lặp, measure/biến đổi mơ hồ. Test dùng tên/sheet/file/tọa độ khác public. Replay chương trình sai cũ được phát hiện; không tự gán đáp án mẫu.

V44 public **20/20 ba lượt**, decision **16/18**. Chưa thể quy toàn bộ biến động điểm/thời gian giữa hai đợt cho guard vì model/gateway không tất định. Giữ cả lượt public chậm và các lỗi decision. Source hiện tại có **297 test đạt**, Ruff check/format đạt. Hai đợt focused đều là chẩn đoán, không phải qualification đầy đủ hoặc holdout mới; source chính thức Qwen vẫn giữ nguyên model/entrypoint.

Lượt `v44_all_known_254` đánh giá riêng toàn bộ 254 câu đã tiêu thụ, candidate-only, cùng source v44 và cùng cấu hình audit. Khóa danh sách cùng hash dữ liệu trước inference; một trần riêng 30 phút / 200 HTTP attempts / 2 triệu token cho cả 10 bộ. Đây là thí nghiệm mới có phạm vi định trước, không bổ sung phần còn thiếu của v39 hoặc đặt lại ngân sách v39. Không có baseline đồng thời trong lượt này, nên không dùng nó tuyên bố cải thiện tốc độ có đối chứng.

Kết quả lượt hồi quy đầy đủ v44: **253/254 (99,61%)**, **116,729 giây** cho 254 câu, **693.267 token**, **122 HTTP attempts**, RSS đỉnh **150,19 MiB**. Usage đầy đủ, không có phần chưa đánh giá. Từng bộ: 60/60, 32/32, known 18/18, synthetic 24/24, structural **17/18**, generalization 18/18, transfer 24/24, compositional 18/18, robustness 24/24, decision 18/18. Câu structural sai nhân đơn giá ở cả giá trị cơ sở lẫn tổng cuối, làm bình phương đơn giá; review audit trả lại cùng code sai. Giữ nguyên lỗi, không thay đáp án. Đây là chỉ số hồi quy đã biết, không phải độ đúng private. Decision ở lượt focused trước vẫn 16/18; không chọn riêng lượt 18/18 để khẳng định ổn định.


## V45–v48: giảm kiểm chứng thừa và sửa hợp đồng phản hồi

| Thí nghiệm sinh mới | Đối chiếu | Candidate | Quyết định |
| --- | --- | --- | --- |
| v45, 92 câu đã biết | low 90/92; 100,656 giây; 454.664 token | medium riêng khi review 89/92; 99,233 giây; 416.722 token | Không chọn medium |
| v48, 92 câu đã biết | system hiện tại 90/92; 61,459 giây; 321.452 token | system envelope đồng bộ 91/92; 78,240 giây; 362.895 token | Giữ để kiểm tra tiếp; chưa đổi mặc định |

V45 thêm trạng thái verification riêng cho từng câu; payload và trace ghi đúng effort thực tế được yêu cầu. Probe medium thành công trong cùng ngân sách batch, không chứng minh gateway thực sự áp dụng mức reasoning nội bộ nào. Lượt đầu vẫn low, lượt cuối vẫn high, không tăng giới hạn ba lượt/five HTTP attempts. Chính sách medium không được chọn vì tổng độ đúng giảm.

V46 sửa một false positive có thể tái hiện: cùng thực thể nằm ở hai cột vai trò khác nhau trong một quan hệ đã được đọc đầy đủ không tự chứng minh có nhiều section. Chỉ miễn cảnh báo trùng nhãn khi có một vùng bảng/một context, các cột vai trò có header riêng biệt, đủ mọi hàng chứa nhãn được đọc và các số đều nằm trong vùng đó. Đọc một phần, bảng khác, nhãn chỉ ở một cột và qualifier năm/nhóm vẫn qua kiểm tra cũ. Replay nguyên chương trình hợp lệ từng bị từ chối ở generalization-016 trả 1.437500 từ một response giả lập, không thêm model call: đây là bằng chứng offline.

| Đợt đầy đủ | Public ba lượt | Public giây trung bình | Public token trung bình | Ngoài public đã biết | Requests toàn đợt |
| --- | --- | --- | --- | --- | --- |
| v46 | 20, 20, 20 | 13,588 | 140.608,33 | 253/254 | 196/200 |
| v47 | 20, 20, 20 | 15,321 | 116.024,67 | 251/254 | 200/200 |

Mỗi đợt trên chạy 334 câu gồm baseline public 20, candidate public ba lần và 254 câu hồi quy. V46 giảm 44,01% thời gian / 30,76% token public so với baseline cùng đợt, RSS đỉnh125,13MiB. V47 giảm40,33% /46,16%, RSS122,41MiB. Cả hai usage đầy đủ. V47 xử lý đủ334 bản ghi và vừa dùng hết200requests; flag stopped do chạm trần sau lượt cuối vẫn được giữ, không mở lượt mới để lấp dữ liệu. Không có holdout độc lập mới.

V47 nhận root selection:[] như metadata rỗng trung tính khi đủ đúng qN, giữ metadata/needs_verification/selection riêng từng program và raw response gốc. Root selection không rỗng/null/object, key thiếu/thừa/unknown hoặc root code cạnh tranh vẫn bị từ chối; không đoán quyền sở hữu nguồn. Replay phản hồi cũ giữ được program hợp lệ và vẫn từ chối program xếp hạng sai bằng guard hiện có. Hướng dẫn data_rows được làm rõ: string-only vẫn khớp heading, cận dữ liệu cần dựa workbook. Điều này chưa bảo đảm model làm đúng; ba lỗi v47 là so ô trống None với chuỗi rỗng, hết lượt khi guard review sau sửa hasattr, và một phép tính số bước sai.

V48 thử sửa mâu thuẫn cấp system: batch system mô tả keyed programs thay vì yêu cầu root code đơn, giữ nguyên toàn bộ phần helper/nguồn/ngữ nghĩa phía sau CELL TYPES. Repair đơn câu giữ prompt đơn câu. Feature chỉ bật ở CoherentPlanningAgent; StructuredBatchedAgent mặc định không đổi sang feature này. Candidate tăng một câu trên92 nhưng chậm hơn27,30% và tăng12,89% token so với đối chiếu cùng đợt; chưa đủ chứng minh cải thiện private hoặc chấp nhận. Public riêng v48 cả hai20/20: đối chiếu8,846giây/88.724token; candidate19,994giây/124.636token. Đây là **mỗi bên một lượt**, không so lượt nhanh này với trung bình lịch sử để tuyên bố thắng.

Source cuối giai đoạn có304tests đạt, Ruff check/format đạt. Không promote candidate; yêu cầu kiểm tra đầy đủ và holdout độc lập còn thiếu. Benchmark vẫn chưa đạt cải thiện50% cho cả thời gian/token một cách ổn định. Mọi chi phí gateway được ghi miễn phí theo xác nhận người dùng, không phải số tiền do provider báo; không gọi Qwen trả phí trong đợt này.


## V49–v52: gộp workbook, giữ riêng nguồn thực thi

Mỗi workbook có namespace sheet riêng trong lượt lập chương trình. Mỗi chương trình chỉ được đọc workbook sở hữu câu hỏi đó; trùng tên sheet hoặc trùng nội dung câu hỏi không làm trộn nguồn. Công thức tham chiếu sheet được ánh xạ trong đúng workbook. Khi cache gộp vượt giới hạn, chương trình tải và xử lý từng workbook đầy đủ, không dùng dữ liệu bị cắt.

| Sàng lọc trên cùng 92 câu đã biết | Exact Match | Tổng giây | Token API |
| --- | --- | --- | --- |
| V49 cùng workbook | 92/92 | 87,957 | 350.398 |
| V49 gộp tối đa 8 câu | 92/92 | 71,014 | 218.825 |
| V50 gộp 8 | 89/92 | 99,888 | 342.607 |
| V50 gộp 8, lập lịch câu riêng song song | 92/92 | 90,471 | 326.601 |
| V50 gộp 16 | 90/92 | 86,296 | 214.542 |

V49 giảm 19,26% thời gian và 37,55% token. V50 chọn lập lịch song song để kiểm tra tiếp; không chọn gộp 16 vì giảm độ đúng. Thứ tự cấu hình được luân phiên giữa các bộ; mọi điểm trên là hồi quy, không phải holdout độc lập.

| Kiểm tra đầy đủ, Gemini sinh mới | V51 | V52 |
| --- | --- | --- |
| Baseline public | 20/20; 24,727 giây; 190.793 token | 20/20; 24,296 giây; 208.540 token |
| Ba lượt public | 20, 19, 19 | 20, 20, 20 |
| Public trung bình | 14,756 giây; 94.983 token | 6,543 giây; 83.712 token |
| Ngoài public, 254 câu đã biết | 253/254 | 249/254 |
| Tổng giây / token ngoài public | 177,769 / 551.149 | 190,693 / 557.170 |
| RSS tổng đỉnh | 143,91 MiB | 125,78 MiB |
| HTTP attempts / dự trù token toàn đợt | 127 / 1.026.891 | 122 / 1.016.846 |

V52 sửa kiểm tra nhánh chỉ tiêu theo từng bản ghi và bổ sung `column_letter` có giới hạn, tránh lệch cột do `chr` và hỗ trợ cột AA trở đi. Hai lượt đều xử lý đủ 334 câu, usage đầy đủ; không đạt gate nên **không mở bộ prospective mới 18 câu**.

Năm lỗi V52: đếm cả heading trong tập yêu cầu; hiểu sai số quan sát của sự kiện xác suất; hai câu lấy thu nhập của người khác; thuật toán đường găng sai sau sửa lỗi runtime. Đây là các lỗi cần tổng quát hóa cách chọn nguồn và kiểm chứng thuật toán, không thêm luật theo ID. Replay phát hiện nguồn sai hoặc bỏ cảnh báo giả được ghi riêng, không tính thành điểm LLM mới.

Bộ prospective đã đóng băng trước V51 có số liệu lẫn bố cục mới và ba họ riêng: chênh lệch kép trên panel cân bằng, phân bổ hai sản phẩm với ràng buộc tài nguyên liên tục, hạn dịch vụ theo lịch làm việc. Oracle độc lập; đáp án chỉ vào evaluator. Khi gate chưa đạt, bộ này vẫn là **chưa đánh giá**, không phải 0/18.


## V53–v54: giải độc lập có chọn lọc, chưa chấp nhận

Thêm cảnh báo khi câu hỏi gọi tên một bản ghi duy nhất nhưng chương trình chỉ đọc số của hàng khác trong cùng bảng. Không tự thay số hoặc suy ra đáp án. Thử giải lần hai từ workbook gốc cho phép tính có số liệu ở nhiều sheet; lượt hai không thấy chương trình/đáp án đầu. Chỉ khi hai đáp án khác nhau mới đưa hai chương trình chưa xác minh vào lượt phân xử thứ ba.

V53 gặp lỗi mạng lặp lại: 22 attempts thiếu usage. Dừng có kiểm soát, giữ dự trù token bảo thủ **899.195** cho 49 attempts, lưu checkpoint và phần chưa chạy; **không dùng lượt này làm đối chiếu chất lượng hoặc hiệu suất**. Probe catalog sau đó trả HTTP 200 và đúng model. V54 là lượt khôi phục riêng, không ghi đè hoặc đặt lại hạn mức V53.

| V54, Gemini sinh mới | Kết quả |
| --- | --- |
| Baseline public | 20/20; 25,874 giây; 212.715 token |
| Ba lượt candidate public | 20/20; 20/20; 19/20 |
| Public trung bình | 33,609 giây; 168.431 token |
| Regression 60 / 32 | 58/60; 32/32 |
| Known 18 / synthetic 24 | 18/18; 24/24 |
| Decision / structural / generalization | 17/18; 17/18; 18/18 |
| Transfer / compositional / robustness | 24/24; 18/18; 24/24 |
| Ngoài public tổng cộng | 250/254; 318,220 giây; 882.291 token |
| RSS tổng đỉnh | 137,61 MiB |
| HTTP attempts / dự trù token | 200 / 1.600.299; usage đầy đủ |

Xử lý đủ 334 câu, không có lỗi hết allowance trong từng câu. Hết đúng 200 attempts sau bước cuối nên harness vẫn ghi cờ dừng; không diễn giải thành thiếu dữ liệu hoặc sửa báo cáo gốc. Public chậm hơn baseline 29,90%, token giảm 20,82%; độ đúng không đạt yêu cầu. Không gán toàn bộ chênh lệch giữa các phiên cho một thay đổi vì model/gateway có biến động. Transfer và compositional đủ điểm không bù cho các bộ giảm điểm.

Hai chương trình regression đã sửa đúng ở lượt hai nhưng bị mất đáp án khi lần giải độc lập cuối sinh lỗi. **Bản checkpoint sau V54** chỉ bắt đầu cơ chế hai lời giải khi còn đủ hai lượt cho giải mới và phân xử; nếu thiếu lượt, ghi rõ đã bỏ qua kiểm chứng độc lập, vẫn giữ mọi kiểm tra nguồn/ngữ nghĩa thông thường. Sửa này có unit test, **chưa có benchmark Gemini mới**. Signoff Qwen cũng chặn profile phát triển chưa được transport chính thức triển khai, tránh chạy nhầm cùng-workbook rồi tuyên bố đã xác nhận packing. Không có request Qwen trả phí mới.

Cấu hình gộp và giải độc lập vẫn là thử nghiệm qua `--planning-profile`; mặc định CLI thi không được đổi. Bộ prospective 18 câu vẫn chưa mở vì gate thất bại. Mốc 253/254 trước đây cũng thuộc dữ liệu đã tiêu thụ; chưa có bằng chứng cải thiện private BTC.
