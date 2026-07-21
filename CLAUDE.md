# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trên repo này.

## Đọc trước tiên

👉 **[AGENTS.md](AGENTS.md)** là tài liệu chuẩn, đầy đủ (kiến trúc, nghiệp vụ, gotcha).
Đọc nó trước khi sửa code. **[MEMORY.md](MEMORY.md)** ghi các quyết định & bối cảnh.
`README.md` là hướng dẫn cài đặt cho người dùng cuối (một phần mục "Logic sinh báo cáo"
đã cũ — tin theo AGENTS.md).

## Tóm tắt nhanh

Bot Telegram (Python, `python-telegram-bot` 21.10 + `gspread`) đọc Google Sheet
"Task Đã Điều Phối", gửi báo cáo team/cá nhân/deadline/tuần theo lịch và trả lời lệnh.
Mã trong `src/`: `bot.py` (handler + job + `/cauhinh`), `report_generator.py` (dựng
text báo cáo), `sheets_client.py` (`Task` + đọc sheet), `config.py` (đọc/ghi config.yaml).

## Quy ước làm việc

- **Giao tiếp & comment bằng tiếng Việt**, giữ văn phong/độ dày comment như code hiện có.
- **Không** commit/đăng secret: `config.yaml` (bot_token, spreadsheet_id) và
  `credentials.json`. Không dán nội dung của chúng vào chat/PR/artifact.
- Sửa xong: chạy `python -m py_compile src/*.py`. Không có test suite; máy dev **không cài**
  `gspread`/`pytz`/`telegram` → xác minh logic bằng script stub module ngoài +
  monkeypatch `sheets.fetch_tasks`/`fetch_team_members` (đặt file tạm ở scratchpad).
- Thay đổi code/`config.yaml` chỉ có hiệu lực sau khi **khởi động lại bot**
  (`docker compose restart` / `up -d --build`); riêng `/cauhinh set` áp dụng ngay.

## Bẫy hay gặp (chi tiết trong AGENTS.md)

1. **Ngày trong tuần**: PTB ≥ 20 dùng `0=Chủ Nhật`. `days: [1,2,3,4,5]` = T2–T6, `[5]` = T6.
2. **Báo cáo team & `/tai` dùng HTML**: mọi chỗ gửi 2 loại này phải truyền
   `parse_mode=ParseMode.HTML` và escape nội dung động qua `_esc` (nếu không, thẻ `<b>`
   hiện thô).
3. **`config.yaml` mất comment** sau `/cauhinh set` (dùng `yaml.safe_dump`).
4. **Đọc dropdown nhân sự là best-effort** — luôn giữ nhánh fallback `team.members`.
5. `.claude/launch.json` trỏ tới dự án khác (không liên quan) — bỏ qua.

## Môi trường

Windows (PowerShell) · thư mục `C:\Users\LEHOANGANH-HCM-02\Documents\telegram-report-bot`
· **không phải** git repo. Chỉ chạy được server thật khi có credentials + mạng.
