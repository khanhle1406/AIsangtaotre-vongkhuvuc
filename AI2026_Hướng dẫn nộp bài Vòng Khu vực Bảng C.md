# CUỘC THI SÁNG TẠO TRẺ QUỐC GIA TRONG LĨNH VỰC TRÍ TUỆ NHÂN TẠO NĂM 2026
## HƯỚNG DẪN NỘP BÀI BẢNG C

---

### 1. Cấu trúc bài nộp

- **Định dạng & Dung lượng**: Bài nộp là một tệp `.zip` không quá 100 MB.
- **Quy tắc đặt tên file ZIP**: Đặt theo tên đội thi, ví dụ đội tên là `team001` thì tên file là `team001.zip`.
- **Vị trí tệp Dockerfile**: Tệp `Dockerfile` **bắt buộc phải nằm ngay ở thư mục gốc** của tệp ZIP, không được đặt trong bất kỳ thư mục con nào. Tên và cấu trúc các tệp còn lại do đội tự chọn.

```text
team001.zip
|-- Dockerfile
`-- ...mã nguồn và tệp cần thiết...
```

- **Môi trường thực thi Docker**:
  - Ảnh Docker phải chạy trên kiến trúc **Linux amd64**, **không dùng GPU**.
  - Ảnh Docker phải chứa sẵn toàn bộ mã nguồn cùng các thư viện phụ thuộc cần thiết (offline install hoặc build sẵn trong image).
  - **Tuyệt đối không đưa khóa API vào bài nộp**.

---

### 2. Entrypoint

- Ảnh Docker phải khai báo `ENTRYPOINT` để nhận các tham số dòng lệnh từ hệ thống chấm. Không bắt buộc ngôn ngữ hoặc tên tệp cụ thể.
- Ví dụ:
  - **Python**: `ENTRYPOINT ["python", "main.py"]` (hoặc `run.py`)
  - **JavaScript**: `ENTRYPOINT ["node", "main.js"]`
  - **Rust**: `ENTRYPOINT ["./app"]`
- **Quy chuẩn thực thi**: Chương trình được khai báo trong `ENTRYPOINT` phải nhận các tham số do hệ thống chấm cung cấp và **chỉ thoát với mã 0** sau khi đã ghi xong kết quả.

---

### 3. Các tham số hệ thống cung cấp

Hệ thống chấm thi tự động sẽ chạy bài làm với 6 tham số dòng lệnh:

```bash
--xlsx-dir /input/xlsx_files \
--queries /input/queries.json \
--output /output/submission.csv \
--openrouter-key <key> \
--openrouter-model qwen/qwen3.7-flash \
--openrouter-base-url https://openrouter.ai/api/v1
```

**Chương trình dự thi bắt buộc phải**:
- Đọc các bảng tính trong thư mục nhận từ tham số `--xlsx-dir`.
- Đọc danh sách câu hỏi từ tệp nhận từ tham số `--queries`.
- Ghi kết quả vào đúng đường dẫn nhận từ tham số `--output`.
- **Không được sửa đổi dữ liệu** trong thư mục `/input`.
- Ghi nhật ký (logs) ra `stdout` hoặc `stderr`, không ghi lẫn vào tệp kết quả.

---

### 4. Định dạng kết quả

- Tệp kết quả xuất ra phải là định dạng **CSV UTF-8** với đúng hai cột: `id,answer`.
- Ví dụ:
  ```csv
  id,answer
  1,11
  2,Ngo
  ```
- **Ràng buộc kết quả**:
  - Mỗi `id` trong `queries.json` phải xuất hiện đúng một lần.
  - Không được thiếu, trùng lặp hoặc thêm `id`.
  - Cột `answer` chỉ chứa đáp án cuối cùng, không kèm giải thích.
