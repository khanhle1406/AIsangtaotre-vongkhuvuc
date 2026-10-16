# ĐỀ THI
## CHỦ ĐỀ 2: HỎI ĐÁP TRÊN BẢNG TÍNH EXCEL

### 1. Mục tiêu
Xây dựng giải pháp tự động trả lời câu hỏi bằng ngôn ngữ tự nhiên dựa trên dữ liệu trong các tệp Excel. Dữ liệu có thể gồm nhiều trang tính, nhiều bảng trên cùng một trang tính, tiêu đề phân cấp, ô gộp hoặc cấu trúc không đồng nhất. Giải pháp cần xác định đúng thông tin liên quan và đưa ra câu trả lời chính xác.

### 2. Dữ liệu được cung cấp
Ban Tổ chức (BTC) cung cấp dữ liệu công khai để các đội phát triển và tự đánh giá giải pháp, gồm:

| Thành phần | Nội dung |
| :--- | :--- |
| `xlsx_files/` | Thư mục chứa các tệp Excel (.xlsx). |
| `queries.json` | Danh sách câu hỏi với các trường `id`, `file_name` và `query`. |
| `sample_submission.csv` | Tệp mẫu kết quả gồm hai cột `id` và `answer`. |

Trong tệp `queries.json`, `id` là mã câu hỏi; `file_name` là tên tệp Excel tương ứng; `query` là nội dung câu hỏi.

**Hình minh họa: Ví dụ dữ liệu trong tệp Excel**
| Dòng | Cột A | Cột B | Cột C | Cột D | Cột E | Cột F | Cột G |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **21** | 19 | Quang | Van | Bui | 2005-09-13 | 2024-07-13 | 61 |
| **22** | 20 | Lan | Hoang | Nguyen | 1998-02-07 | 2024-03-04 | 76 |

Ví dụ dữ liệu câu hỏi trong tệp `queries.json`:
```json
[
  {
    "id": 1,
    "file_name": "sample.xlsx",
    "query": "How many people have a score higher than 80?"
  },
  {
    "id": 2,
    "file_name": "sample.xlsx",
    "query": "What is the last name of the person with the highest score?"
  }
]
```

Ví dụ kết quả tương ứng trong tệp `submission.csv`:
```csv
id,answer
1,11
2,Ngo
```

Bài dự thi được đánh giá trên tập kiểm thử ẩn do BTC xây dựng theo quy trình tương tự bộ dữ liệu công khai.

Bộ dữ liệu công khai đợt 1: [Truy cập tại đây (Google Drive Folder)](https://drive.google.com/drive/folders/1IiEl_weVjIdd1xlnhtiuY-NzmiThXa4o?usp=sharing)

---

### 3. Yêu cầu đối với bài dự thi
– Giải pháp nhận đầu vào là thư mục chứa các tệp `.xlsx` và tệp `queries.json`; kết quả phải được xuất ra tệp `submission.csv` đúng định dạng mẫu.  
– Mỗi `id` trong `queries.json` tương ứng với đúng một dòng kết quả. Trường `answer` chỉ ghi đáp án cuối cùng, không kèm giải thích.  
– Mỗi đội nộp một tệp `.zip` gồm mã nguồn, các tệp cấu hình/phụ thuộc cần thiết và tệp `README.md` hướng dẫn cài đặt, cấu hình, chạy chương trình bằng dòng lệnh.  
– Giải pháp phải có khả năng chạy lại với dữ liệu đầu vào mới, không phụ thuộc vào đường dẫn của bộ dữ liệu mẫu. Bài không chạy được hoặc không tạo ra tệp kết quả hợp lệ sẽ không được chấm.  

---

### 4. Giới hạn tài nguyên và điều kiện thực thi
- **Mô hình ngôn ngữ (LLM):** Nếu sử dụng LLM để trả lời câu hỏi, giải pháp phải hỗ trợ mô hình thống nhất khi chấm thi là **Qwen3.7 Flash** (model ID: `qwen/qwen3.7-flash`), truy cập qua OpenRouter (https://openrouter.ai/qwen/qwen3.7-flash). Đội thi phải cho phép cấu hình thông tin truy cập API và không đưa khóa API vào mã nguồn. Quy định này không hạn chế việc sử dụng công cụ AI trong quá trình phát triển giải pháp.
- **Chi phí LLM:** Tổng chi phí gọi LLM trên tập kiểm thử ẩn không vượt quá **0.10 USD/câu hỏi** cho mỗi lần chấm, tính cả các lượt gọi lại (retry). Chi phí được xác định theo mức sử dụng API do BTC ghi nhận.
- **Thời gian thực thi:** Tối đa **40 phút cho 20 câu hỏi**, tính từ lúc bắt đầu chạy giải pháp đến khi tạo xong tệp `submission.csv`, bao gồm thời gian xử lý dữ liệu và gọi API. Việc chấm thi được thực hiện trên máy của BTC có cấu hình **6 core vCPU, 12 GB RAM**.
- **Dung lượng và bộ nhớ:** Tệp `.zip` nộp bài không được vượt quá **100 MB**. Trong quá trình chạy trên tập kiểm thử ẩn, tổng không gian bộ nhớ giải pháp sử dụng không được vượt quá **1 GB**.
- **Lưu ý:** Bài dự thi vi phạm một trong các giới hạn nêu trên sẽ không được chấm điểm.

---

### 5. Chấm điểm và xếp hạng
BTC chạy các bài dự thi hợp lệ trên tập kiểm thử ẩn. Thứ tự xếp hạng được xác định theo các tiêu chí ưu tiên sau:
1) **Số câu trả lời đúng theo so khớp chính xác với đáp án chuẩn (Exact Match):** đội có nhiều câu trả lời đúng hơn được xếp trước.
2) **Thời gian thực thi trung bình mỗi câu hỏi:** đội có thời gian thấp hơn được xếp trước nếu số câu trả lời đúng bằng nhau.
3) **Số token LLM sử dụng trung bình mỗi câu hỏi:** đội dùng ít token hơn được xếp trước nếu hai tiêu chí trên bằng nhau.

---

### 6. Lịch trình
| Thời điểm | Hoạt động |
| :--- | :--- |
| **19h00 ngày 13/10** | BTC công bố bộ dữ liệu công khai lần 1; các đội bắt đầu phát triển giải pháp. |
| **09h00 ngày 16/10** | BTC công bố bộ dữ liệu công khai lần 2. |
| **12h00 ngày 17/10** | Hạn cuối nộp tệp `.zip` chứa bài dự thi. |
| **12h00–17h00 ngày 17/10** | BTC chấm các bài dự thi hợp lệ trên tập kiểm thử ẩn. |
| **20h00 ngày 17/10** | Công bố bảng xếp hạng tạm thời. |
| **08h00–17h00 ngày 18/10** | Vấn đáp xác minh giải pháp của các đội thi. |
| **20h00 ngày 20/10** | Công bố bảng xếp hạng chính thức. |

---

### 7. Vấn đáp và xác minh
Phần vấn đáp nhằm xác minh mức độ làm chủ giải pháp của đội thi. Các đội phải giải thích được nguyên lý hoạt động, các thành phần chính và chứng minh khả năng điều chỉnh mã nguồn theo yêu cầu phù hợp với phạm vi đề thi. Đội không đáp ứng yêu cầu xác minh sẽ bị loại khỏi bảng xếp hạng chính thức.
