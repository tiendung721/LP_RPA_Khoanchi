# Trợ lý Dữ liệu Quyết toán

Ứng dụng desktop Windows giúp người dùng mở một GPT Custom, tiếp nhận file
`ket_qua_boc_tach.json`, kiểm tra dữ liệu, xem/sửa từng dòng và tạo snapshot
JSON đã duyệt. File trong `Ready` là đầu vào ổn định cho các mô-đun Excel hoặc
Power Automate Desktop được phát triển ở giai đoạn sau.

Ứng dụng không dùng OpenAI API, không tự đăng nhập, không điều khiển trình
duyệt và không đọc PDF/ảnh/Excel nguồn. Người dùng tự làm việc với GPT trong
Chrome/Edge rồi tải JSON về.

## Phạm vi

Phiên bản hiện tại bao gồm:

- mở URL GPT Custom bằng Chrome, Edge hoặc trình duyệt mặc định của Windows;
- dùng browser profile riêng để giữ phiên đăng nhập do chính người dùng tạo;
- theo dõi Inbox, quét cả file đã có lúc khởi động và chờ file ghi ổn định;
- bỏ qua file tải tạm, lọc tên file/dung lượng và chống nhận trùng bằng SHA-256;
- lưu bản gốc bất biến, bản làm việc riêng và lịch sử lô trong SQLite;
- kiểm tra schema cùng các quy tắc `fee`/`rule`/`amount`;
- xem, tìm kiếm, lọc, sắp xếp, thêm, sửa và xóa dòng;
- lưu nguyên tử, khôi phục lô đang làm dở và tạo snapshot đã xác nhận trong
  `Ready`;
- cung cấp `ReviewedBatchProvider` để mô-đun sau lấy đúng file đã duyệt.

Chưa triển khai việc ghi dữ liệu vào Excel, đọc Excel để chạy RPA, gọi flow
Power Automate Desktop hay bất kỳ thao tác RPA giả nào. Hai bước này chỉ được
hiển thị là “Sẽ phát triển sau”.

## Yêu cầu hệ thống

- Windows 10 hoặc Windows 11, tài khoản người dùng có quyền ghi vào thư mục cá
  nhân;
- Python 3.12 (bản 64-bit được khuyến nghị khi chạy source);
- Chrome hoặc Microsoft Edge nếu muốn dùng browser profile riêng. Nếu không,
  ứng dụng dùng trình duyệt mặc định của Windows;
- không cần quyền Administrator.

## Cài đặt môi trường phát triển

Mở PowerShell hoặc Command Prompt tại thư mục dự án:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Để chạy test và đóng gói EXE, cài thêm dependency phát triển:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Không cài `openpyxl`, Selenium, Playwright hoặc thư viện PAD vì chúng không
thuộc phạm vi phiên bản này.

## Chạy ứng dụng từ source

Có thể chạy trực tiếp:

```powershell
.\.venv\Scripts\python.exe main.py
```

Hoặc nhấp đúp `run_app.bat`. Nếu `.venv` chưa tồn tại, script sẽ in chính xác
các lệnh cần chạy và không tự ý thay đổi Python toàn hệ thống.

Lần chạy đầu, ứng dụng tự tạo cấu hình, database, log và các thư mục dữ liệu.
Dữ liệu runtime không được ghi cạnh file EXE hay vào `Program Files`.

Muốn dùng một `data_root` khác, truyền đường dẫn lúc khởi động hoặc đặt biến
môi trường tương đương:

```powershell
.\.venv\Scripts\python.exe main.py --data-root "D:\DuLieu\TroLyQuyetToan"
$env:TRO_LY_DATA_ROOT = "D:\DuLieu\TroLyQuyetToan"
.\dist\TroLyDuLieuQuyetToan.exe
```

Không đổi `data_root` khi ứng dụng đang chạy; hãy đóng ứng dụng rồi khởi động
lại với cùng tùy chọn. Inbox và browser profile vẫn chỉnh trực tiếp được trong
trang **Cài đặt**.

## Thiết lập GPT và Inbox lần đầu

1. Mở trang **Cài đặt**, nhập URL đầy đủ của GPT Custom rồi chọn trình duyệt
   **Tự động**, **Chrome**, **Edge** hoặc **Mặc định Windows**. URL phải bắt đầu
   bằng `https://` hoặc `http://`; dự án không đi kèm URL cá nhân.
2. Có thể để ứng dụng tự dò executable hoặc chọn `chrome.exe`/`msedge.exe`.
   Chọn một thư mục **Browser profile** nằm trong vùng dữ liệu của ứng dụng.
3. Nhấn **Kiểm tra mở GPT** hoặc **Mở trợ lý GPT**. Đăng nhập thủ công một lần
   trong profile riêng này. Ứng dụng không đọc mật khẩu/cookie.
4. Trong profile Chrome/Edge vừa mở, vào **Settings > Downloads > Location**,
   đặt vị trí tải xuống là Inbox đang hiển thị trong ứng dụng. Có thể tắt tùy
   chọn hỏi vị trí lưu mỗi lần nếu quy trình nội bộ cho phép.
5. Lưu Cài đặt. Khi đổi Inbox, watcher cũ được dừng rồi watcher mới được khởi
   động mà không cần khởi động lại ứng dụng.
6. Gửi chứng từ cho GPT theo quy trình của đơn vị và tải file
   `ket_qua_boc_tach.json`. Các tên tự tăng như
   `ket_qua_boc_tach (1).json` và tên có hậu tố
   `ket_qua_boc_tach_*.json` cũng được nhận.

Nếu trình duyệt tải sang nơi khác, nhấn **Chọn file JSON thủ công** và chọn
file đó. Ứng dụng vẫn tiếp nhận theo cùng quy trình archive, hash và validation;
không chỉnh trực tiếp file người dùng vừa chọn.

## Quy trình duyệt dữ liệu

Sau khi file tải xong, watcher chờ kích thước và thời điểm sửa đổi ổn định
(mặc định 3 giây) rồi mới chuyển file cho dịch vụ tiếp nhận. File
`.crdownload`, `.part`, `.tmp`, tên bắt đầu bằng `~$`, file sai pattern hoặc
vượt giới hạn mặc định 50 MB không được xử lý như JSON hoàn chỉnh.

Trong màn hình xem và chỉnh sửa:

- **Hợp lệ**: không có lỗi hoặc cảnh báo;
- **Cảnh báo** (nền vàng nhạt): cần kiểm tra nhưng không chặn xác nhận, ví dụ
  container khác mẫu, số tiền trống/0, mã `CXD` hoặc dòng trùng hoàn toàn;
- **Lỗi** (nền đỏ nhạt): sai schema/kiểu dữ liệu hay quan hệ nghiệp vụ và chặn
  **Xác nhận hoàn tất**.

Sắp xếp và lọc chỉ thay đổi cách xem, không đổi thứ tự thật trong mảng `d`.
`Ctrl+S` lưu bản làm việc. Amount được hiển thị có phân cách hàng nghìn nhưng
được ghi dưới dạng integer hoặc `null`. Khi chỉ còn cảnh báo, ứng dụng yêu cầu
xác nhận trước khi tạo snapshot `Ready`.

Hợp đồng JSON được giữ nguyên:

```json
{"v":1,"d":[["DRYU3026167",null,"VTN","CV",13554000],[null,"BL123456789","CB","HD",27500000]]}
```

Root chỉ có `v` và `d`; mỗi dòng luôn là mảng năm vị trí
`[cont, bl, fee, rule, amount]`. Ứng dụng không đổi dòng thành object và không
tự tính lại tiền/VAT.

## Thư mục dữ liệu

Cấu hình mặc định dùng vùng dữ liệu cá nhân, thường là:

```text
%LOCALAPPDATA%\Kikai\TroLyDuLieuQuyetToan\
├── Config\settings.json
├── Archive\Original\
├── Workspace\
├── Ready\
├── Rejected\
├── Database\app_state.db
├── Logs\
└── BrowserProfile\
```

Inbox thân thiện với người dùng thường nằm tại:

```text
%USERPROFILE%\Documents\TroLyDuLieuQuyetToan\Inbox
```

Đường dẫn thực tế luôn lấy từ Cài đặt và có thể khác các giá trị mặc định.

- `Archive\Original`: bản gốc đã tiếp nhận, không được dùng làm bản chỉnh sửa.
- `Workspace\<batch_id>`: bản đang làm việc và các backup gần nhất.
- `Ready`: snapshot bất biến sau mỗi lần xác nhận; đây là nguồn duy nhất dành
  cho tích hợp Excel/RPA.
- `Rejected`: nơi ghi nhận/lưu file không parse hoặc có lỗi cấu trúc nghiêm
  trọng theo luồng tiếp nhận.
- `Database`: chỉ lưu metadata lô và trạng thái ứng dụng, không thay thế JSON
  nghiệp vụ.

Không sửa file trong `Archive` hoặc `Ready` bằng tay. Muốn sửa một lô, mở lại
lô từ Lịch sử, sửa bản làm việc và xác nhận để tạo snapshot mới.

## Chạy test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Test dùng thư mục tạm của pytest, không ghi vào Inbox hay database thật của
người dùng.

## Đóng gói EXE

Sau khi cài `requirements-dev.txt`, chạy:

```powershell
.\build_exe.bat
```

Lệnh tương đương:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean pyinstaller.spec
```

Kết quả là ứng dụng windowed không mở console đen tại
`dist\TroLyDuLieuQuyetToan.exe`. File spec chỉ đóng gói mã/dependency; không
đưa `settings.json`, database, log, BrowserProfile, Inbox, Archive, Workspace
hoặc Ready cá nhân vào EXE.

## Sao lưu và khôi phục

1. Đóng ứng dụng để SQLite và watcher dừng sạch.
2. Sao lưu tối thiểu `Database\app_state.db` và toàn bộ `Ready`.
3. Nên sao lưu thêm `Archive`, `Workspace` và `Config\settings.json` nếu cần
   khôi phục lịch sử đầy đủ. Không cần sao lưu BrowserProfile nếu chính sách
   bảo mật yêu cầu đăng nhập lại.
4. Khi khôi phục, chép dữ liệu về đúng `data_root` trong Cài đặt trước khi mở
   ứng dụng. Giữ nguyên cấu trúc thư mục và không trộn database của hai thời
   điểm khác nhau với nhau.

## Xử lý lỗi thường gặp

### Không mở được GPT

Kiểm tra URL có `http://`/`https://`, thử nút **Tự dò**, kiểm tra đường dẫn
`chrome.exe`/`msedge.exe`, rồi thử lựa chọn **Mặc định Windows**. Nếu Windows
cũng không mở URL, đặt lại trình duyệt mặc định trong Windows Settings. Xem
trang Nhật ký để biết executable nào đã được thử.

### Không nhận file

Đối chiếu Inbox trên giao diện với thư mục tải xuống của đúng browser profile;
kiểm tra tên file có khớp pattern và đuôi thật là `.json`; nhấn **Mở thư mục
nhận file** để xác minh. Có thể dùng **Chọn file JSON thủ công**. Khi vừa đổi
Inbox, lưu Cài đặt để watcher được khởi động lại.

### File còn `.crdownload`, `.part` hoặc `.tmp`

Đó là file trình duyệt đang tải hoặc tải chưa hoàn tất. Chờ trình duyệt bỏ hậu
tố tạm. Nếu hậu tố không biến mất, hủy/tải lại trong trình duyệt; không đổi tên
file tạm thành `.json` bằng tay.

### JSON sai schema

Mở chi tiết lỗi để xác định root/khóa/dòng sai. File đúng phải có chính xác hai
khóa `v`, `d`; `v` bằng integer `1`; mỗi dòng có đúng năm phần tử. Yêu cầu GPT
xuất lại JSON thuần, không có Markdown. Không sửa trực tiếp bản Archive.

### File trùng

Ứng dụng so SHA-256 nội dung chứ không chỉ so tên. Thông báo “File này đã được
tiếp nhận trước đó” nghĩa là không tạo lô mới; mở lô cũ được gợi ý trong Lịch
sử. Đổi tên file nhưng giữ nguyên nội dung không tạo bản sao.

### Không có quyền ghi

Chọn Inbox/data root trong thư mục cá nhân có quyền ghi, tránh `Program Files`,
thư mục hệ thống và thư mục mạng chỉ đọc. Kiểm tra antivirus/Controlled Folder
Access nếu quyền Windows có vẻ đúng. Không chạy Administrator chỉ để che lỗi
cấu hình đường dẫn.

### Ứng dụng báo đang có instance khác

Tìm cửa sổ ứng dụng đang mở và dùng cửa sổ đó. Nếu ứng dụng trước vừa bị dừng
bất thường, chờ vài giây rồi thử lại. Chỉ xóa lock file sau khi chắc chắn không
còn tiến trình `TroLyDuLieuQuyetToan` nào chạy.

## API cho giai đoạn Excel/RPA

`app.services.reviewed_batch_provider.ReviewedBatchProvider` cung cấp ba
phương thức ổn định:

```text
get_latest_ready_json_path() -> Path | None
get_ready_json_path(batch_id: int) -> Path | None
list_ready_batches() -> list[BatchMetadata]
```

Ví dụ tại composition root:

```python
from app.services.reviewed_batch_provider import ReviewedBatchProvider

provider = ReviewedBatchProvider(batch_service)
latest_path = provider.get_latest_ready_json_path()
```

Mô-đun tích hợp sau này nhận instance provider từ tầng khởi tạo ứng dụng rồi
gọi một trong các hàm trên. Path trả về luôn trỏ tới snapshot trong `Ready`.
Không đọc trực tiếp file vừa tải trong Inbox, file Archive hoặc working copy,
vì các file đó chưa chắc đã được người dùng duyệt.

## Ghi chú vận hành và bảo mật

- Browser profile là vùng riêng của ứng dụng nhưng vẫn chứa phiên đăng nhập;
  bảo vệ thư mục này theo chính sách dữ liệu của đơn vị.
- Log ghi sự kiện kỹ thuật và đường dẫn cần thiết, không ghi mật khẩu/cookie.
- Có thể cấu hình mọi đường dẫn; mã nguồn không gắn cứng tên tài khoản Windows.
- Snapshot Ready chỉ thể hiện dữ liệu đã qua validation và xác nhận của người
  dùng, không tự suy luận nghiệp vụ từ mã tiền.
