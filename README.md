# Trợ lý Dữ liệu Quyết toán

Ứng dụng desktop Windows mở Trợ lý ảo bằng file BAT, tự nhận file JSON tải
xuống trong `Output`, kiểm tra dữ liệu và hỗ trợ xem/sửa/xác nhận kết quả.

Luồng hiện tại không còn mở URL, cấu hình trình duyệt, mở thư mục nhận file ở
Bước 1 hoặc chọn JSON thủ công.

## Chức năng chính

- Bước 1 chỉ có nút **Mở Trợ lý ảo**.
- File BAT do người dùng chọn trong Cài đặt và được chạy tách rời qua
  `cmd.exe`.
- Trước khi chạy BAT, ứng dụng cập nhật nguyên tử Chrome `Preferences` của
  profile trong bundle để tải thẳng về thư mục `Output`.
- Theo dõi `ket_qua_boc_tach*.json`, bỏ qua file tải tạm và chờ file ghi ổn
  định.
- Mỗi lượt tải thay thế file JSON trước đó và được đặt tên
  `ket_qua_boc_tach_YYYYMMDD_HHMMSS.json`.
- Kiểm tra schema và các quy tắc nghiệp vụ hiện có; hỗ trợ xem, thêm, sửa, xóa,
  xem JSON thô, lưu và xác nhận.
- Bước 2 hiển thị trạng thái file và thời điểm lưu gần nhất theo định dạng
  `HH:mm ngày dd/MM/yyyy`.
- Bước 3 đồng bộ các SQT mới từ workbook Hàng ngày và nhập khoản chi của
  file JSON hiện hành đã xác nhận vào workbook BK.
- Mọi lần ghi BK đều dùng backup, working copy, kiểm tra lại và thay file
  nguyên tử; tác vụ chạy nền để không khóa giao diện.

## Yêu cầu

- Windows 10 hoặc Windows 11.
- Python 3.12 bản 64-bit.
- Google Chrome và bundle Trợ lý ảo đã giải nén đúng cấu trúc.
- Không cần quyền Administrator.

## Cài đặt và chạy

Nhấp đúp `run_app.bat`, hoặc chạy:

```bat
run_app.bat
```

Script kiểm tra Python 3.12 64-bit, tạo `.venv` nếu cần, cài dependency runtime
và mở ứng dụng. Lần đầu cần Internet để tải thư viện. Các lần sau không gọi
`pip` nếu `requirements.txt` không thay đổi và môi trường vẫn hợp lệ.

Để cài dependency phục vụ test:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Mặc định toàn bộ dữ liệu nội bộ được đặt ngay trong thư mục chứa source hoặc
file `.exe`, nên có thể copy/đóng gói cả bundle mà không phụ thuộc AppData.
Có thể chủ động chọn vùng dữ liệu khác khi khởi động:

```powershell
.\run_app.bat --data-root "D:\DuLieu\TroLyQuyetToan"
$env:TRO_LY_DATA_ROOT = "D:\DuLieu\TroLyQuyetToan"
.\run_app.bat
```

Không đổi `data_root` khi ứng dụng đang chạy. Thư mục này dùng cho Config,
Database, Logs và cây dữ liệu nội bộ bên dưới `Output\_system`.

## Thiết lập lần đầu

1. Mở **Cài đặt**.
2. Chọn file BAT của bundle, ví dụ
   `RPA_ChatGPT_Launcher\Mo_Tro_Ly_RPA.bat`.
3. Giữ `Output` mặc định hoặc chọn thư mục khác.
4. Nhấn **Kiểm tra cấu hình**, sau đó **Lưu cấu hình**.
5. Về trang Quy trình và nhấn **Mở Trợ lý ảo**.
6. Làm việc trong cửa sổ Trợ lý ảo rồi nhấn tải file kết quả. Ứng dụng sẽ tự
   nhận file; không cần chọn file bằng tay.

Để dùng Bước 3, cấu hình thêm:

- **File Hàng ngày trên LAN** (`.xlsx` hoặc `.xlsm`).
- **File BK Tổng hợp cá nhân** (`.xlsx` hoặc `.xlsm`).

Nút **Kiểm tra cấu hình** chỉ đọc workbook/bản sao tạm, không lưu thử vào file
gốc. Định dạng Excel cũ `.xls` không được hỗ trợ.

Ứng dụng không sửa file BAT, PowerShell, extension hay file ZIP. Chỉ Chrome
`Preferences` trong `RPA_ChatGPT_Profile\Default` được cập nhật để đặt:

```json
{
  "download": {
    "default_directory": "<đường dẫn Output>",
    "prompt_for_download": false,
    "directory_upgrade": true
  }
}
```

Các khóa khác trong `Preferences` được giữ nguyên.

## Hợp đồng JSON

Ứng dụng chỉ hỗ trợ schema:

```json
{
  "v": 1,
  "d": [
    ["DRYU3026167", null, "VTN", "CV", 13554000]
  ]
}
```

Root chỉ có `v` và `d`. Mỗi dòng trong `d` có đúng năm vị trí:

```text
[container, bl, fee, rule, amount]
```

Không dùng các root `metadata`, `du_lieu_boc_tach`, `canh_bao` hoặc
`raw_data`.

## Vòng đời file Output

Thư mục mặc định là:

```text
<thư mục chứa main.py hoặc .exe>\Output
```

Khi có file hoàn chỉnh mới:

1. Các file kết quả JSON cũ trong `Output` bị loại bỏ.
2. File mới được đặt tên theo timestamp nhận file.
3. Nội dung được kiểm tra và tự động mở trên màn hình review.

Quy tắc mới nhất luôn thắng. Nếu hai lượt tải chồng nhau, ứng dụng bỏ qua sự
kiện cũ. Nếu file mới sai schema, file cũ vẫn bị loại bỏ theo quy tắc đã chốt
và Bước 2 hiển thị nguyên nhân lỗi, không hiển thị lưu thành công.

Khi lưu từ màn hình review, ứng dụng ghi nguyên tử trực tiếp vào một file JSON
timestamp mới rồi xóa tên cũ. Không tạo archive, working copy, `.bak` hoặc
snapshot Ready. Nếu file mới được tải khi cửa sổ cũ còn thay đổi chưa lưu, dữ
liệu cũ bị bỏ và cửa sổ review chuyển ngay sang dữ liệu mới.

## Thư mục dữ liệu

Mặc định dữ liệu nội bộ nằm cùng thư mục ứng dụng:

```text
khoanchi_pm_project\                 (hoặc thư mục chứa file .exe)
├── Config\settings.json
├── Database\app_state.db
├── Logs\
└── Output\
    ├── ket_qua_boc_tach_YYYYMMDD_HHMMSS.json
    └── _system\
        └── Excel\
            ├── Temp\
            ├── Backup\
            └── Reports\
```

Khi cả bundle được chuyển vị trí, ứng dụng tự cập nhật `data_root`, `Output`
mặc định và các đường dẫn batch trong SQLite sang vị trí mới. Đường dẫn ngoài
bundle do người dùng tự chọn vẫn được giữ nguyên.

- `Output\ket_qua_boc_tach_YYYYMMDD_HHMMSS.json`: JSON hiện hành duy nhất.
- `Output\_system\Excel\Temp`: snapshot nguồn và working copy ngắn hạn.
- `Output\_system\Excel\Backup`: backup BK tạo ngay trước mỗi lần ghi.
- `Output\_system\Excel\Reports`: vùng dành cho báo cáo xử lý Excel.
- `Database`: metadata batch và trạng thái ứng dụng.

## Chạy kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Test sử dụng thư mục tạm của pytest, không ghi vào Output hay database vận hành
của người dùng.

## Xử lý lỗi thường gặp

### Không mở được Trợ lý ảo

Kiểm tra đã chọn file `.bat`, file nằm trong đúng bundle và các thư mục launcher,
extension vẫn đầy đủ. Dùng **Kiểm tra cấu hình** để xem thông báo cụ thể.

### Không nhận file

Kiểm tra tên file khớp `ket_qua_boc_tach*.json`, file đã tải xong và Output
trong Cài đặt đúng với thư mục đang được theo dõi. Các hậu tố `.crdownload`,
`.part`, `.tmp` và `.download` được xem là file tạm.

### JSON sai schema

File phải có đúng root `{v, d}`, `v` là integer `1` và mỗi dòng có đúng năm
phần tử. Bước 2 sẽ hiển thị lỗi cấu trúc và khóa nút xem/sửa cho đến khi có file
mới đọc được.

### Không có quyền ghi

Chọn Output trong vùng người dùng có quyền ghi; tránh `Program Files`, thư mục
hệ thống và thư mục mạng chỉ đọc. Kiểm tra Controlled Folder Access nếu quyền
Windows có vẻ đúng nhưng ứng dụng vẫn báo lỗi.

## API cho mô-đun tích hợp sau

`app.services.reviewed_batch_provider.ReviewedBatchProvider` cung cấp:

```text
get_latest_ready_json_path() -> Path | None
get_ready_json_path(batch_id: int) -> Path | None
list_ready_batches() -> list[BatchMetadata]
```

Các tên API cũ được giữ để tương thích, nhưng path trả về trỏ tới file JSON
hiện hành đã xác nhận trong `Output`.
