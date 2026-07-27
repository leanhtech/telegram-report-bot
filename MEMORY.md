# MEMORY.md — Bộ nhớ dự án

Ghi lại **quyết định, bối cảnh và bẫy** không nhìn thấy được từ code, để AI/agent
(và người) nắm nhanh "tại sao". Tra cứu "cái gì / như thế nào" ở [AGENTS.md](AGENTS.md).

_Cập nhật gần nhất: 2026-07-26._

## Hiện trạng (2026-07-21)

- Bot đang hoạt động, triển khai bằng Docker (`restart: unless-stopped`).
- Lịch gửi (giờ VN, đã đúng T2–T6 sau khi sửa lỗi ngày):
  - `team_report` 16:20, T2–T6 · `personal_report` 16:00 · `deadline_alert` 13:28 ·
    `weekly_summary` 16:25 **Thứ 6**.
- `team.members` đã được điền qua Telegram (8 người) vì **đọc dropdown nhân sự đang
  fail ở runtime** → hiện `/tai` dùng fallback từ config. Việc đọc dropdown tự động chưa
  xác nhận chạy được (chưa có log lỗi cụ thể để chỉnh).

## Quyết định & lý do (nhật ký thay đổi)

1. **Sửa lỗi lịch "Thứ 5 không gửi".** Nguyên nhân: `python-telegram-bot` ≥ 20 đổi map
   ngày sang `0=Chủ Nhật`. Config cũ `[0,1,2,3,4]` bị hiểu thành CN–T5 (thừa CN, thiếu
   T6). → Đổi tất cả lịch ngày thành `[1,2,3,4,5]` (T2–T6), `weekly_summary` → `[5]` (T6).
   **Vì sao nhớ:** đây là bẫy dễ tái diễn mỗi khi chỉnh `days`.

2. **Dọn code thừa.** Bỏ import `ParseMode` không dùng (sau này thêm lại khi cần HTML),
   khóa `weekly_summary.topic` thừa (code chỉ đọc `topic_id`), trường `Task.raw` (dựng
   mỗi dòng, không ai đọc). Giữ `task_type/est/stt` vì map cột thật + rẻ.

3. **Báo cáo "các dự án" gom theo từng dự án.** Trước đây gộp phẳng nhiều dự án → rối.
   Nay nhóm theo `📁 Tên dự án:`, "(Chưa phân loại dự án)" xuống cuối. Kiosk vẫn phẳng
   (một dự án).

4. **Phần "Dự kiến" chỉ còn việc cần làm tiếp, không gồm việc đang làm dở chung chung.**
   - Ban đầu: bỏ task "Đang thực hiện" khỏi Dự kiến, chỉ giữ "dự tính giao" (task mới,
     chưa có nhân sự/ngày/hạn). Cũng gỡ tiền tố "Tiếp tục" (khi đó vô nghĩa).
   - Sau đó bổ sung lại: task **đang thực hiện có `due >= ngày dự kiến`** cũng vào Dự kiến
     và **gắn lại "Tiếp tục..."** cho riêng nhóm này (dựa `not is_planned`, chính xác hơn
     cách cũ là dò trùng tên). Task dự tính giao giữ tên trơn.
   **Vì sao nhớ:** logic `planned_for` / "Tiếp tục" đã đổi 3 lần — đây là bản chốt.

5. **In đậm + emoji cho 2 đầu mục báo cáo team.** Telegram cần `parse_mode` để bold →
   chuyển báo cáo team sang **HTML** (`<b>` + `📋`/`🗓️`), escape nội dung động (`_esc`).
   Thêm tham số `parse_mode` cho `send_long`; các báo cáo khác vẫn plain text.
   **Hệ quả cần nhớ:** thêm chỗ gửi báo cáo team/workload phải truyền `ParseMode.HTML`.

6. **Lệnh `/tai` — tải công việc theo nhân sự.** Mục đích: thấy ai nhẹ tải (giao thêm) /
   ai quá tải. Phân loại task chưa xong theo hạn + ước tính giờ hôm nay (EST chia đều
   trên ngày làm việc của task) + nhãn tải so `daily_capacity_hours`. Mỗi chỉ số một dòng
   cho dễ nhìn. Thêm mục "🆓 Chưa được giao task" từ roster.
   **Logic giờ hôm nay — bản 2 (xếp lịch theo sức chứa).** Ban đầu chia đều EST theo số
   ngày làm việc của task (`_est_hours_today`). Vấn đề: nếu một ngày trong khoảng đã đầy
   (≥ capacity vì task khác) thì không thể chia đều — giờ phải dồn sang ngày trống. Đã đổi
   sang `_person_hours_today`: xếp lịch từng người theo **EDF + water-filling** (lấp ngày
   tải thấp trước, trần `daily_capacity_hours`/ngày), ngày đầy thì tràn sang ngày trống;
   trả về tải hôm nay. Quá hạn → dồn hôm nay; không hạn → rải ~capacity/ngày; T7/CN = 0h.

   **Bản 3 — tính cả ngày đã qua.** Bản 2 chỉ xếp lịch từ hôm nay trở đi nên bỏ sót phần
   task dài ngày đã làm ở những ngày trước. Nay **ngày đã qua "ăn" trước tối đa phần chỗ
   trống hôm đó**, phần EST còn lại mới chia cho hôm nay + tương lai (VD task tạo T2 –
   hạn T4 – EST 6h: T2 kín 8h → T3/T4 mỗi ngày 3h; T2 mới dùng 4h → còn 1h/ngày).
   Hệ quả: `_person_hours_today` phải nhận **cả task đã hoàn thành** (mới biết ngày đã qua
   bận bao nhiêu) → `build_workload_report` truyền `all_by_person`, còn phần đếm/phân loại
   vẫn dùng task đang mở. **Chưa** trừ ngày lễ (chỉ T7/CN).

7. **Nguồn danh sách nhân sự = dropdown cột "Nhân Sự Thực Hiện".** Đọc data validation
   (`ONE_OF_LIST`/`ONE_OF_RANGE`) qua `fetch_sheet_metadata`, bọc `try/except`, fallback
   `config team.members`. Cache 5× `cache_seconds`.

8. **`/cauhinh set` hỗ trợ danh sách.** Để điền `team.members` từ Telegram khi dropdown
   fail. `_parse_value(raw, key)` nhận list khi khóa ∈ `LIST_KEYS`, có dấu phẩy, hoặc
   bọc `[ ]`; `null` → `[]`. Chỉ `schedules.*` mới nạp lại lịch; `team.members` nạp lại roster.

9. **Theo dõi thay đổi trên sheet kế hoạch (`watch.*`).** Nhu cầu: hằng ngày phải mở
   thủ công các file kế hoạch do người khác cập nhật để dò nội dung phát sinh.
   - **Chọn snapshot + diff, không chọn Apps Script webhook.** Webhook cần cài script vào
     từng file (phải có quyền sửa) và bot phải mở cổng HTTP public — chi phí vận hành lớn
     hơn giá trị. Drive Revisions API bị loại vì không diff được cấp ô.
   - **Tách hẳn khỏi luồng báo cáo.** Sheet "Task Đã Điều Phối" do chính chủ cập nhật nên
     không cần theo dõi; `fetch_tasks()` và `google_sheets.*` giữ nguyên, chỉ **thêm**
     `fetch_rows()`.
   - **Khoá định danh không theo vị trí dòng** (Jira → STT → vân tay → nhãn dòng) để sort
     lại sheet không sinh thông báo. Kèm bước dò đổi tên, nếu không việc sửa tên sẽ bị báo
     nhầm thành xoá + thêm mới.
   - **Mỗi file một kiểu** → hai chế độ: `task` (nhận ra ý nghĩa cột) và `generic` (báo
     theo tên cột nguyên văn). Không ép người dùng khai cấu hình trước mới dùng được.
   - **Bộ lọc chỉ chặn ở khâu gửi**, ảnh chụp lưu toàn bộ — nếu lọc từ đầu, hôm sau mở
     rộng bộ lọc sẽ có hàng trăm dòng cũ bị hiểu nhầm là mới.
   - **Ba module logic không import gspread/telegram/pytz** → repo lần đầu có test tự động
     chạy được trên máy dev (`python -m unittest discover -s tests -t .`).
   - **Lần quét đầu của ngày ép mọi thay đổi sang loại "gom"** để thay đổi qua đêm đi
     chung một bản tin sáng thay vì dội tin lúc mở khung giờ.

## Bẫy đã biết (đừng vấp lại)

- **Ngày PTB `0=Chủ Nhật`** (mục 1). Dùng `[1..5]` = T2–T6.
- **Báo cáo team & `/tai` là HTML** → cần `parse_mode=ParseMode.HTML` + escape (mục 5).
- **`config.yaml` mất comment** sau `/cauhinh set` (`yaml.safe_dump`).
- **`.claude/launch.json` trỏ dự án khác** (kiosk-dvc/uvicorn) — không liên quan.
- **`README.md` mục "Logic sinh báo cáo" đã cũ** — tin theo AGENTS.md.
- Máy dev **không cài** gspread/pytz/telegram → test bằng stub module + monkeypatch.
- **`watch.active_days` cũng theo quy ước `0 = Chủ Nhật`** như `schedules.*`.
- **Mất thư mục `state/`** (quên mount) → bot chụp lại từ đầu và im lặng, không dội tin —
  đúng thiết kế, đừng "sửa".

## Việc mở / đề xuất tiếp theo

- **Xác nhận đọc dropdown nhân sự tự động** (cần log lỗi runtime `Không đọc được dropdown
  nhân sự: ...` để chỉnh cho khớp cấu hình sheet thật). Khi chạy được thì `team.members`
  chỉ còn là fallback.
- Cập nhật lại `README.md` mục 5 cho khớp logic hiện tại (chưa làm — ngoài phạm vi yêu cầu).
- Tùy chọn: trừ **ngày lễ** khi tính giờ `/tai`; liệt kê tên task dưới mỗi người trong `/tai`.
- **Đã có test tự động (unittest stdlib)** cho ba module logic: `state_store.py`,
  `change_tracker.py`, `change_reporter.py` (65 test, chạy `python -m unittest discover`).
  **Còn thiếu test** cho `report_generator.py` và `sheets_client.py` (dễ thêm với dữ liệu giả
  khi cần).
