# AGENTS.md — Hướng dẫn cho AI/agent làm việc trên dự án

> Tài liệu **chuẩn** cho mọi AI agent (Claude Code, Cursor, Copilot, ...). `CLAUDE.md`
> và `MEMORY.md` bổ trợ cho file này. `README.md` là hướng dẫn cài đặt/vận hành cho
> người dùng cuối (không phải cho agent).

## 1. Dự án là gì

**Telegram Report Bot** — bot Python đọc dữ liệu công việc từ Google Sheet
"Task Đã Điều Phối" và tự động:
- Gửi **báo cáo team** hàng ngày vào nhóm/topic Telegram (Kiosk gửi riêng + các dự án khác).
- Gửi **báo cáo cá nhân** cho quản lý, **cảnh báo deadline**, **tổng kết tuần**.
- Trả lời các lệnh tra cứu tiến độ / tải công việc theo yêu cầu.
- Cho phép **đổi cấu hình ngay trên Telegram** (`/cauhinh`).

Ngôn ngữ giao tiếp & comment: **tiếng Việt**. Thuật ngữ kỹ thuật để tiếng Anh.

## 2. Tech stack

- Python 3.12
- `python-telegram-bot[job-queue]==21.10` (APScheduler cho lịch)
- `gspread==6.1.4` + `google-auth` (đọc Google Sheet, service account, **read-only**)
- `PyYAML`, `pytz`
- Triển khai: Docker (`docker-compose.yml`, `Dockerfile`) hoặc `python -m src.bot`

## 3. Cấu trúc mã

```
src/
  bot.py               # Entry point: command handlers, scheduled jobs, /cauhinh, send_long
  config.py            # class Config: đọc/ghi config.yaml, truy cập theo "a.b.c"
  report_generator.py  # Sinh nội dung các báo cáo (thuần logic, không gọi Telegram)
  sheets_client.py     # class Task + SheetsClient: đọc sheet, cache, đọc dropdown nhân sự
config.yaml            # Toàn bộ cấu hình runtime (CHỨA SECRET — xem mục 9)
credentials.json       # Key service account Google (SECRET)
docker-compose.yml     # Mount config.yaml + credentials.json vào container
README.md              # Hướng dẫn cài đặt cho người dùng
```

Luồng: `bot.py` (handler/job) → `report_generator.py` (dựng text) → `sheets_client.py`
(dữ liệu). `report_generator` **không** phụ thuộc `telegram`; test được độc lập.

## 4. Chạy & triển khai

```bash
python -m src.bot                 # chạy trực tiếp
docker compose up -d --build      # build + chạy nền
docker compose restart            # nạp lại sau khi sửa config.yaml bằng tay
docker compose logs -f            # xem log ("Bot đang chạy..." là OK)
```

**Quan trọng:** sửa **code** hoặc **config.yaml bằng tay** → phải **khởi động lại bot**
mới có hiệu lực. Riêng lệnh `/cauhinh set` áp dụng **ngay** (ghi file + nạp lại lịch/roster
trong tiến trình đang chạy). `config.yaml` và `credentials.json` được mount từ ngoài vào
container nên sửa file thật hoặc `/cauhinh` đều ăn vào cùng một file.

## 5. Cấu hình (`config.yaml`)

| Nhánh | Ý nghĩa |
|---|---|
| `telegram.bot_token` | Token bot (SECRET). Không đổi được qua `/cauhinh`. |
| `telegram.admin_ids` | Danh sách user_id được phép `/cauhinh`. |
| `google_sheets.*` | `spreadsheet_id`, `worksheet_name` (="Task Đã Điều Phối"), `credentials_file`. |
| `timezone` | `Asia/Ho_Chi_Minh`. |
| `schedules.<job>` | `enabled`, `time` "HH:MM", `days`, `chat_id`, `topic_id`; riêng `team_report` có `kiosk_chat_id`/`kiosk_topic_id`. |
| `report.*` | `kiosk_project_name`, tiêu đề báo cáo, `strip_bracket_prefixes`, `cache_seconds`, `daily_capacity_hours`. |
| `team.members` | Danh sách nhân sự (fallback khi không đọc được dropdown — xem mục 7). |

`config.py` dùng `yaml.safe_dump` khi ghi → **mọi comment trong config.yaml bị xoá** sau
lần `/cauhinh set` đầu tiên. Đừng dựa vào comment trong file này.

## 6. Lịch tự động (`register_jobs` trong bot.py) — GOTCHA QUAN TRỌNG

4 job: `team_report`, `personal_report`, `deadline_alert`, `weekly_summary` (map trong
dict `JOBS`).

⚠️ **Quy ước ngày của PTB ≥ 20 đã đổi: `0=Chủ Nhật ... 6=Thứ Bảy`** (không phải
0=Thứ Hai như PTB cũ / như `datetime.weekday()`). Nội bộ:
`_CRON_MAPPING = ('sun','mon','tue','wed','thu','fri','sat')`.

Vì vậy trong `config.yaml`:
- `days: [1,2,3,4,5]` = **Thứ 2 → Thứ 6**.
- `weekly_summary days: [5]` = **Thứ 6**.
- Default fallback trong code cũng là `[1,2,3,4,5]`.

Sai lầm kinh điển: dùng `[0,1,2,3,4]` (tưởng T2–T6) → thực tế chạy CN–T5, thừa Chủ Nhật
và **thiếu Thứ 6**. Đừng lặp lại.

## 7. Mô hình dữ liệu & nghiệp vụ (`sheets_client.py`)

`Task` (dataclass) map từ cột sheet qua `HEADER_MAP`: `stt, name, jira, task_type,
project, assignee, est, created, due, done_date, status, note`. Các cột ngày parse qua
`parse_date` (`DATE_FIELDS`).

Trạng thái (dựa trên chuỗi `status`):
- `is_done` = status chứa "hoàn thành".
- `is_planned` = status chứa "dự tính" hoặc "chưa giao" (task **dự tính giao**, thường
  chưa có nhân sự/ngày/hạn).

Phân loại theo ngày:
- `active_on(day)` — task tính vào "hôm nay": hoàn thành đúng `day`, HOẶC (đã tạo ≤ `day`,
  chưa xong, **không** phải dự tính giao).
- `planned_for(day)` — task vào phần "Dự kiến":
  1. Task **dự tính giao** (`is_planned`, ngày tạo không ở tương lai), HOẶC
  2. Task **đang thực hiện** còn hạn: `due >= day`.

**Đọc danh sách nhân sự (`fetch_team_members`)** — nguồn chính là **dropdown (data
validation) của cột "Nhân Sự Thực Hiện"**: đọc qua `fetch_sheet_metadata`, hỗ trợ cả
`ONE_OF_LIST` (liệt kê trực tiếp) và `ONE_OF_RANGE` (trỏ vùng → đọc vùng). Toàn bộ bọc
`try/except`; lỗi → log cảnh báo → **fallback sang `config team.members`**. Roster cache
5× `cache_seconds`.

## 8. Các báo cáo (`report_generator.py`)

`clean_task_name`: bỏ prefix `[...]`, đảo "Đơn vị - Hành động" → "Hành động (Đơn vị)",
tự chèn động từ nếu tên chưa có (dựa `LEADING_VERBS`/`VERB_HINTS`).

- **`build_daily_team_reports(today)` → `{"kiosk", "others"}`**
  - `kiosk` = danh sách phẳng (một dự án). `others` = **gom theo từng dự án** (`📁 Tên:`),
    nhóm "(Chưa phân loại dự án)" xuống cuối.
  - Phần "Dự kiến": task đang thực hiện mang sang có tiền tố **"Tiếp tục..."**; task dự
    tính giao giữ nguyên tên.
  - **Dùng HTML**: 2 đầu mục in đậm + emoji (`📋` báo cáo, `🗓️` dự kiến). Nội dung động
    escape qua `_esc` (`html.escape(quote=False)`).
- **`build_workload_report(today)` (lệnh `/tai`)** — tải công việc theo nhân sự (HTML):
  - Với mỗi người có task chưa xong: đếm `tồn từ trước` (due<today) / `đến hạn hôm nay` /
    `chưa đến hạn` (due>today) / `không hạn`; ước tính **giờ hôm nay**; gắn nhãn tải.
  - `_person_hours_today` (xếp lịch theo **sức chứa/ngày**, không chia đều máy móc):
    mỗi task rải EST vào các ngày làm việc trong hạn, ưu tiên **hạn sớm (EDF)** và **lấp
    ngày còn trống trước** (water-filling qua `_water_fill`), trần `daily_capacity_hours`
    giờ/ngày. Nhờ đó task dài ngày có ngày đã kín (vì task khác) sẽ **dồn giờ sang ngày
    trống** thay vì chia đều lên hôm nay. Quá hạn → dồn hôm nay; không hạn → rải
    ~capacity giờ/ngày (cửa sổ `ceil(EST/capacity)` ngày); T7/CN hoặc chưa tới ngày bắt
    đầu → 0. Trả về tải của **hôm nay** (index 0).
  - Nhãn so với `report.daily_capacity_hours` (mặc định 8h): 🟢 trống/nhẹ · 🟡 vừa · 🔴 quá tải.
  - Sắp quá tải lên đầu; thêm mục **"🆓 Chưa được giao task"** = `fetch_team_members()` trừ
    những người đang có task mở.
- `build_personal_report`, `build_deadline_alert`, `build_weekly_summary`, `search_progress`
  — **plain text** (không HTML).

## 9. Gửi tin nhắn (`send_long` trong bot.py)

`send_long(bot, chat_id, text, topic_id=None, parse_mode=None)` — tự cắt theo dòng khi
vượt `MAX_LEN` (4000).

⚠️ **Chỉ báo cáo team & workload dùng HTML.** Bất kỳ chỗ nào gửi 2 loại này **phải** truyền
`parse_mode=ParseMode.HTML`, và text phải được escape (`_esc`) trong `report_generator`.
Các báo cáo khác để `parse_mode=None` (plain text). Nếu thêm chỗ gửi mới cho báo cáo
HTML mà quên `parse_mode`, thẻ `<b>` sẽ hiện thô.

## 10. Lệnh Telegram

`start, help, baocao [kiosk|duan], canhan, tiendo <kw>, trehan, tai, tuan, thanhvien <tên>,
lamMoi/lammoi, chatid, cauhinh`. Trong chat riêng còn có trả lời tự nhiên (`on_text`:
"tiến độ ...", "báo cáo").

`/cauhinh set <khóa> <giá trị>` (chỉ admin):
- `_parse_value` nhận diện **danh sách** khi khóa ∈ `LIST_KEYS` (`team.members`,
  `telegram.admin_ids`), hoặc có dấu phẩy, hoặc bọc `[ ]`. VD `team.members Thái, Nam, Lan`.
  `null` với khóa list → `[]`.
- Đổi `schedules.*` → nạp lại lịch; đổi `team.members` → nạp lại roster.
- Chặn `telegram.bot_token`, `google_sheets.credentials`.

## 11. Kiểm thử / xác minh

**Chưa có test suite tự động.** Máy dev **không cài** `gspread`/`pytz`/`telegram`, nên:
- Kiểm tra cú pháp: `python -m py_compile src/*.py`.
- Kiểm tra logic: viết script stub các module ngoài (inject `types.ModuleType` cho
  `gspread`, `google.*`, `pytz`, `telegram*`) rồi monkeypatch `sheets.fetch_tasks` /
  `sheets.fetch_team_members` để chạy `report_generator` với dữ liệu giả. Đặt file tạm
  trong thư mục scratchpad.
- Phần đọc dropdown thật (`_read_dropdown_members`) chỉ chạy được khi có gspread +
  credentials → dựa vào `try/except` + fallback, không test offline được.

## 12. An toàn / bảo mật (BẮT BUỘC)

- `config.yaml` chứa `bot_token`, `spreadsheet_id`; `credentials.json` là key service
  account. **Không** commit, **không** dán nội dung secret vào tài liệu/PR/chat.
- Chỉ `admin_ids` mới `/cauhinh`. Bot chỉ cần quyền Viewer trên sheet.

## 13. Bẫy cần nhớ (checklist khi sửa)

1. Ngày trong tuần: PTB `0=CN`. Dùng `[1..5]` cho T2–T6.
2. Thêm chỗ gửi báo cáo team/workload → truyền `parse_mode=ParseMode.HTML` + escape nội dung.
3. `config.yaml` mất comment sau `/cauhinh set` (safe_dump).
4. Đọc dropdown là best-effort; luôn giữ nhánh fallback `team.members`.
5. `.claude/launch.json` hiện trỏ tới **dự án khác** (kiosk-dvc/uvicorn) — không liên quan bot này, bỏ qua.
6. `README.md` mục "5. Logic sinh báo cáo" mô tả logic **cũ** (trước các thay đổi gần đây) — ưu tiên file này.
