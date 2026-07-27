# Spec — Khai ánh xạ cột & cột khoá bằng lệnh Telegram

_Ngày: 2026-07-27 · Trạng thái: đã chốt thiết kế, chờ lập kế hoạch triển khai_

## 1. Vấn đề

Chức năng theo dõi thay đổi (spec [2026-07-26](2026-07-26-theo-doi-thay-doi-sheet-design.md))
đã cho phép thêm/bớt/đổi tab file theo dõi ngay trên Telegram. Nhưng hai khoá cấu hình
còn lại của một nguồn — `columns` (ánh xạ tên cột → ý nghĩa) và `key_column` (cột dùng
làm khoá định danh dòng) — **vẫn phải mở `config.yaml` sửa tay rồi khởi động lại bot**.

Hệ quả thật, không phải chuyện thẩm mỹ: nguồn nào bot không đoán được ý nghĩa cột sẽ chạy
**chế độ `generic`**, mà ở chế độ đó `classify` không có `field_map` để đối chiếu, nên
**đổi hạn và đổi người phụ trách không bao giờ được báo ngay** — chúng chỉ vào bản tin gom,
tức là muộn tới 8 tiếng. Bộ lọc `projects`/`assignees` cũng vô tác dụng.

Ngoài ra sửa tay `columns` còn kèm một cái bẫy: đổi ánh xạ là đổi luôn cách sinh khoá định
danh, nên ảnh chụp cũ không còn khớp và lần quét kế tiếp sẽ dội một loạt thay đổi giả.
Người sửa tay phải tự nhớ xoá nguồn rồi thêm lại.

## 2. Phạm vi

**Làm:** hai nhánh lệnh mới `/nguon cot` và `/nguon khoa`, kèm việc tách `cmd_nguon`
thành các hàm con.

**Không làm:** không đụng thuật toán so sánh, không đổi định dạng tin nhắn thông báo,
không thêm khoá cấu hình mới ngoài hai khoá đã có sẵn trong cấu trúc nguồn.

## 3. Cú pháp

```
/nguon cot <id>                          Xem ánh xạ hiện tại + cột thật + chế độ
/nguon cot <id> <Tên cột> = <ý nghĩa>    Khai một cột
/nguon cot <id> xoa <Tên cột>            Gỡ ánh xạ của một cột
/nguon khoa <id> <Tên cột>               Đặt cột khoá định danh
/nguon khoa <id> xoa                     Bỏ cột khoá
```

Chỉ admin, giống các nhánh `/nguon` khác.

**Mỗi lệnh khai một cột.** Tên cột tiếng Việt có dấu cách, gộp nhiều cặp vào một lệnh
làm cú pháp mong manh và sai một chỗ là hỏng cả lệnh; khai từng cột thì mỗi lần bot xác
nhận lại được ngay.

Ý nghĩa hợp lệ **lấy thẳng từ khoá của `FIELD_ALIASES`** (`VALID_FIELDS`), không chép tay
danh sách thứ hai: `name`, `assignee`, `due`, `status`, `project`, `stt`, `jira`,
`created`, `est`, `done_date`, `note`.

**Quy tắc tách chuỗi, chốt rõ để khỏi đoán:**

- Cặp `Tên cột = ý nghĩa` tách ở dấu `=` **cuối cùng** trong chuỗi, vì tên cột có thể chứa
  `=` còn tên trường thì không bao giờ. Hai vế đều `.strip()`.
- Từ khoá `xoa` được xét **trước** khi coi phần còn lại là tên cột. Sheet có cột tên đúng
  bằng "xoa" là trường hợp không đáng thiết kế cho.
- Không có dấu `=` → trả về hướng dẫn cú pháp, không đoán ý người dùng.

## 4. Kiểm tra trước khi ghi

Cả hai lệnh đọc tiêu đề sheet thật (`sheets.fetch_rows`) rồi mới nhận:

| Tình huống | Trả lời |
|---|---|
| Không có nguồn id đó | `Không có nguồn id “x”.` |
| Không mở được file | Báo lỗi kèm **email service account** để share lại; **không ghi gì** |
| Tên cột không có trong sheet | Từ chối, liệt kê các cột thật |
| Ý nghĩa lạ | Từ chối, liệt kê `VALID_FIELDS` |
| Gỡ một cột chưa từng khai | Báo chưa khai, không coi là lỗi |

So khớp tên cột qua `_norm` sẵn có (bỏ qua hoa/thường và khoảng trắng thừa), để gõ
`bên liên quan` cũng khớp cột `Bên liên quan`.

## 5. Ghi & chụp lại

Ghi vào `watch.sources[i].columns` / `.key_column` qua `cfg.set` → **áp dụng ngay, không
restart**, giống `/cauhinh set` và các nhánh `/nguon` khác.

Ngay sau đó **bỏ ảnh chụp cũ của nguồn** và lưu state — đúng cách `/nguon tab` đang làm:

```python
(state.get("sources") or {}).pop(sid, None)
state_store.save(watch_state_path(), state)
```

Lần quét tới rơi vào nhánh "chưa có ảnh chụp" nên chụp lại và **im lặng**. Đây là lý do
chính để làm lệnh này thay vì sửa tay: bước dọn ảnh chụp không còn phụ thuộc trí nhớ người
dùng.

`key_column` cũng đổi cách sinh khoá nên xử lý y hệt.

## 6. Nội dung trả lời

Sau khi khai xong, bot trả về **chế độ trước → sau** và phần còn thiếu:

```
Đã khai “Bên liên quan” = assignee.
Đã nhận ra ý nghĩa 2/5 cột.
Chế độ: generic → generic
Còn thiếu để lên chế độ task: name, thêm 1 trong {assignee, due, status}
Sẽ chụp lại ảnh ở lần quét tới (không báo tin giả).
```

Nếu đã đủ điều kiện thì dòng "Còn thiếu" biến mất và chế độ hiện `generic → task`.

Mục đích: người dùng biết **còn thiếu gì mới lên được chế độ task**, thay vì khai vài cột
rồi không hiểu sao vẫn generic.

`/nguon cot <id>` không kèm tham số thì in: ánh xạ đang khai, danh sách cột thật của
sheet, chế độ hiện tại, phần còn thiếu, và nhắc cú pháp.

## 7. Kiến trúc

**Logic thuần → `change_tracker.py`** (test được offline vì không import gspread/telegram):

- `VALID_FIELDS: frozenset[str]` — `frozenset(FIELD_ALIASES)`, dẫn xuất nên không lệch được.
- `describe_mode(headers, columns_override=None) -> tuple[str, int, int]` — `(chế độ, số
  cột đã nhận ra ý nghĩa, tổng số cột)`.
- `missing_for_task(headers, columns_override=None) -> list[str]` — các phần còn thiếu để
  đủ điều kiện chế độ `task`; rỗng nghĩa là đã đủ.
- `match_column(headers, name) -> str|None` — tên cột gốc khớp `name`, bỏ qua hoa/thường
  và khoảng trắng thừa. Đây là chỗ duy nhất thực hiện việc so khớp tên cột, để `bot.py`
  không phải chạm vào hàm nội bộ `_norm`.

**Phần chạm Telegram/sheet ở lại `bot.py`.**

**Tách `cmd_nguon`.** Hàm này đang 164 dòng với 4 nhánh; thêm 2 nhánh nữa là ~250 dòng.
Tách thành: `cmd_nguon` chỉ định tuyến (~15 dòng) + `_nguon_liet_ke`, `_nguon_them`,
`_nguon_tab`, `_nguon_xoa`, `_nguon_cot`, `_nguon_khoa`. Bốn hàm đầu là **bê nguyên code
hiện có, không đổi hành vi**.

## 8. Chỗ khác phải sửa theo

- `HELP_TEXT` — thêm 2 dòng cú pháp mới.
- Thông báo cuối của `/nguon them` hiện khuyên *"khai ánh xạ cột trong config.yaml
  (watch.sources -> columns)"* → đổi thành gợi ý `/nguon cot <id>`.
- `AGENTS.md` mục 14 và `README.md` mục theo dõi thay đổi — bổ sung 2 lệnh.

## 9. Kiểm thử

Tự động (`python -m unittest discover -s tests -t .`), bổ sung vào
`tests/test_change_tracker.py`:

1. `VALID_FIELDS` đúng bằng tập khoá của `FIELD_ALIASES`.
2. `describe_mode` trên sheet lạ hoàn toàn → `generic`, số cột nhận ra = 0.
3. `describe_mode` với `columns_override` đủ → `task`, số cột nhận ra tăng đúng.
4. `missing_for_task` trên sheet lạ → nêu cả `name` lẫn phần thiếu trong
   `{assignee, due, status}`.
5. `missing_for_task` khi chỉ thiếu 1 trong 3 cột lõi → nêu đúng "thêm 1".
6. `missing_for_task` khi đã đủ điều kiện → trả rỗng.
7. `match_column` khớp được tên cột viết khác hoa/thường và thừa khoảng trắng; tên không
   có trong sheet → `None`.

Phần lệnh chạm `telegram`/`gspread` không test tự động được (máy dev không cài) → giữ quy
ước hiện có: `python -m py_compile src/*.py` + script stub trong scratchpad. Việc tách
`cmd_nguon` là refactor thuần nên xác minh bằng đối chiếu diff: bốn nhánh cũ phải giữ
nguyên từng dòng logic.

## 10. Tiêu chí hoàn thành

- Khai được ánh xạ cột và cột khoá hoàn toàn bằng lệnh Telegram, không mở `config.yaml`,
  không restart.
- Khai xong, lần quét kế tiếp **không** sinh thông báo giả nào.
- Khai sai tên cột hoặc sai ý nghĩa đều bị từ chối kèm gợi ý đúng, và **không** ghi vào
  config.
- Trả lời cho biết chế độ trước → sau và phần còn thiếu.
- `python -m unittest discover -s tests -t .` xanh (71 → 78 test).
- Bốn nhánh `/nguon` cũ hoạt động y như trước khi tách hàm.
