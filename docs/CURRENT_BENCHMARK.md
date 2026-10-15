# Benchmark và phạm vi bằng chứng hiện tại

Các số dưới đây là **Gemini 3 Flash sinh mới**, không dùng replay làm benchmark LLM. Chúng không chứng minh điểm private của BTC hoặc điểm Qwen3.7 Flash. Ưu tiên Exact Match → thời gian → token.

Thí nghiệm mới nhất **v34 audit** chưa được chấp nhận: public **20/20, 19/20, 20/20**, structural **17/18**. Sàng lọc v33 đạt 116/116 không thay thế được kết quả xác nhận này. Review audit vẫn là tùy chọn phát triển; mặc định thi chưa đổi. Chưa có kiểm định độc lập mới hoặc xác nhận Qwen cho source hiện tại.

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
