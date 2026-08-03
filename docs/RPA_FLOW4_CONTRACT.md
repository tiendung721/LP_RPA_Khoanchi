# Hợp đồng dữ liệu luồng 4 (phần mềm → BAT → PAD)

Phần mềm gọi BAT đã cấu hình với đúng một đối số:

```text
<duong-dan-bat> "<Output\_system\RPA\rpa_input_selection.json>"
```

JSON dùng `version = 1`, `operation = "NHAP_KHOAN_CHI_BK"` và chứa:

- `run_id`, `bk_file`, `sheet_name`, `source_fingerprint`;
- `items`: các SQT người dùng đã chọn;
- mỗi item có `sqt`, toàn bộ `source_rows`, `status_before` và `amounts`;
- `status_callback`: lệnh PAD phải gọi sau khi nút Lưu trên web thành công.

Mỗi lần bấm chạy, phần mềm ghi đè file JSON cố định trên. PAD đọc đúng đường
dẫn này như flow cũ, không cần khai báo Input variable.

Các khóa `amounts` ánh xạ với giao diện web:

| Khóa JSON | Dòng trên web | Cột tổng hợp BK |
| --- | --- | --- |
| `cuoc_bo_dong_hang` | CƯỚC BỘ ĐÓNG HÀNG | CƯỚC MB |
| `nang_ha_dong_hang` | NÂNG HẠ ĐÓNG HÀNG | N.HẠ MB |
| `cuoc_bien` | CƯỚC BIỂN | CƯỚC BIỂN |
| `nang_do_vs_lam_lenh` | NÂNG, D/O, VS, LÀM LỆNH TRẢ HÀNG | N.HA VS D/O LỆNH |
| `cuoc_bo_tra_hang` | CƯỚC BỘ TRẢ HÀNG | CƯỚC MN |
| `tien_hang` | TIỀN HÀNG (HĐ) | Luôn bằng 0 |
| `cong_nhan_boc_xep` | CÔNG NHÂN, BỐC XẾP, KHO HÀNG, NHÀ MÁY | Luôn bằng 0 |
| `luu_cont_qua_tai` | LƯU CONT/ QUÁ TẢI | LƯU CONT/QUÁ TẢI |
| `sua_chua_cont` | Khoản chi đặc biệt: Sửa chữa cont | Sửa chữa Cont |

Một SQT có thể gồm nhiều dòng BK. Phần mềm cộng số tiền và gửi toàn bộ
`source_rows`; PAD chỉ nhập một lần cho SQT đó.

SQT có tổng tất cả khoản tiền bằng 0 vẫn được chọn và chạy. Trường hợp này được
hiển thị như một cảnh báo để người dùng kiểm tra, không phải lỗi chặn luồng.

## Cập nhật trạng thái

Trạng thái chỉ có `Chưa nhập` và `Đã nhập`. SQT `Đã nhập` vẫn được chọn và chạy
lại. PAD không sửa Excel trực tiếp.

Sau khi web lưu thành công một SQT, PAD chạy `python_executable`, `script` và
`arguments` trong `status_callback`, thay `{sqt}` bằng SQT vừa lưu. Ví dụ:

```text
python scripts\rpa_excel_helper.py mark-imported --selection "<json>" --sqt "680"
```

Lệnh trả mã `0` và JSON `success=true` khi cập nhật thành công. Nếu web chưa lưu
hoặc bị lỗi, PAD không gọi helper; trạng thái trong BK được giữ nguyên. Helper
tạo một bản backup cho cả `run_id`, khóa file BK và đánh dấu tất cả dòng nguồn
của SQT là `Đã nhập`.
