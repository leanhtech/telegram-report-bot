# Telegram Report Bot - Bot báo cáo công việc tự động

Bot đọc dữ liệu từ Google Sheet "Task Đã Điều Phối" và:
1. Gửi báo cáo team hàng ngày (Kiosk riêng + các dự án khác) vào nhóm/topic Telegram theo giờ cấu hình
2. Gửi báo cáo công việc từng cá nhân về tài khoản riêng của quản lý vào cuối buổi
3. Trả lời tra cứu tiến độ task khi người dùng tương tác
4. Cho phép cấu hình tham số ngay trên Telegram (giờ gửi, nhóm, topic,...)
5. Tính năng bổ sung: cảnh báo task trễ hạn buổi sáng, tổng kết tuần, tra cứu công việc theo thành viên, làm mới dữ liệu

Toàn bộ báo cáo là plain text, copy sang nơi khác không mất format.

## 1. Chuẩn bị

### 1.1. Tạo bot Telegram
1. Chat với @BotFather trên Telegram, gõ /newbot
2. Đặt tên và username cho bot, nhận về bot_token
3. Nếu gửi vào nhóm: thêm bot vào nhóm, cấp quyền gửi tin nhắn. Với nhóm có topic, bot cần quyền "Manage Topics" hoặc ít nhất gửi được vào topic
4. Lưu ý: bot KHÔNG thể tự nhắn cho bạn trước. Bạn phải bấm Start với bot một lần thì bot mới gửi được báo cáo cá nhân cho bạn

### 1.2. Tạo Service Account Google
1. Vào https://console.cloud.google.com -> tạo project
2. Bật "Google Sheets API"
3. Tạo Service Account -> tạo key dạng JSON -> tải về, đổi tên thành credentials.json, đặt cạnh config.yaml
4. Mở Google Sheet -> Share -> thêm email của service account (dạng xxx@xxx.iam.gserviceaccount.com) với quyền Viewer

### 1.3. Lấy các ID cần thiết
- User ID của bạn: chat với @userinfobot
- Chat ID nhóm và Topic ID: sau khi chạy bot, vào nhóm/topic đó gõ /chatid, bot sẽ trả về đúng chat_id và topic_id

## 2. Cài đặt

```bash
cd telegram-report-bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Tạo file config.yaml từ mẫu rồi điền giá trị (config.yaml không có sẵn trong repo vì chứa secret):

```bash
cp config.example.yaml config.yaml      # Windows: copy config.example.yaml config.yaml
```

Sửa file config.yaml:
- telegram.bot_token: token từ BotFather
- telegram.admin_ids: user ID của bạn
- google_sheets.spreadsheet_id: lấy từ URL sheet (đoạn giữa /d/ và /edit)
- schedules: giờ gửi, chat_id, topic_id cho từng loại báo cáo

## 3. Chạy bot

```bash
python -m src.bot
```

## 3b. Chạy bằng Docker trên Windows (khuyến nghị — tự chạy cùng máy)

Cách này không cần cài Python/venv trên máy mới, và bot tự khởi động lại khi bật máy hoặc khi gặp lỗi.

### Bước 1: Chuẩn bị máy mới
1. Cài Docker Desktop: https://www.docker.com/products/docker-desktop/ (chọn bản Windows), cài xong mở lên một lần cho nó khởi tạo
2. Copy toàn bộ thư mục source sang máy mới (KHÔNG cần copy thư mục `venv`). Bắt buộc phải có đủ:
   - `src/`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`
   - `config.yaml` (đã điền bot_token, admin_ids, spreadsheet_id)
   - `credentials.json` (key Service Account — chú ý tên file phải đúng là `credentials.json`, không phải `credentials.json.json`)

### Bước 2: Build và chạy
Mở PowerShell tại thư mục dự án, chạy:

```powershell
docker compose up -d --build
```

Kiểm tra bot đã chạy chưa:

```powershell
docker compose logs -f     # thấy dòng "Bot đang chạy..." là OK, bấm Ctrl+C để thoát xem log
```

### Bước 3: Cho bot tự chạy khi bật máy
Mở **Docker Desktop -> Settings -> General -> bật "Start Docker Desktop when you sign in to your computer"**.

Xong. Từ giờ: bật máy -> Docker tự chạy -> bot tự chạy theo (nhờ `restart: unless-stopped` trong docker-compose.yml). Không cần mở terminal.

### Các lệnh hay dùng
```powershell
docker compose logs -f        # xem log trực tiếp
docker compose restart        # khởi động lại bot (VD: sau khi sửa config.yaml bằng tay)
docker compose down           # tắt hẳn bot (sẽ không tự chạy lại cho đến khi up lại)
docker compose up -d --build  # build lại sau khi sửa code
```

### Lưu ý quan trọng
- **Một token chỉ được chạy MỘT bot**: nếu máy cũ vẫn đang chạy bot (Python hoặc Docker), phải tắt bên đó trước, nếu không 2 bot sẽ giành tin nhắn của nhau (log báo lỗi `Conflict: terminated by other getUpdates request`). Nếu không nhớ bot cũ chạy ở đâu, chat @BotFather -> `/revoke` lấy token mới rồi sửa vào config.yaml
- `config.yaml` và `credentials.json` được mount từ ngoài vào container, nên sửa file trên máy hoặc dùng lệnh `/cauhinh set` trên Telegram đều ăn ngay vào file thật; sửa file bằng tay thì cần `docker compose restart` để bot đọc lại
- Sửa code trong `src/` thì phải build lại: `docker compose up -d --build`

Chạy nền lâu dài trên server Linux (systemd):

```ini
# /etc/systemd/system/report-bot.service
[Unit]
Description=Telegram Report Bot
After=network.target

[Service]
WorkingDirectory=/duong/dan/telegram-report-bot
ExecStart=/duong/dan/telegram-report-bot/venv/bin/python -m src.bot
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now report-bot
```

## 4. Danh sách lệnh

| Lệnh | Chức năng |
|---|---|
| /baocao | Gửi ngay báo cáo ngày (cả 2 báo cáo) |
| /baocao kiosk | Chỉ báo cáo Kiosk |
| /baocao duan | Chỉ báo cáo các dự án khác |
| /canhan | Báo cáo công việc từng cá nhân hôm nay |
| /tiendo <từ khóa> | Tra cứu tiến độ task, VD: /tiendo đồng bộ học sinh |
| /thanhvien <tên> | Công việc hôm nay của một người |
| /trehan | Task trễ hạn / đến hạn hôm nay |
| /tuan | Tổng kết tuần theo dự án và nhân sự |
| /lammoi | Đọc lại dữ liệu mới nhất từ sheet |
| /chatid | Hiện chat_id, topic_id, user_id hiện tại |
| /cauhinh | (Admin) Xem cấu hình lịch gửi |
| /cauhinh set <khóa> <giá trị> | (Admin) Đổi cấu hình, tự nạp lại lịch |

Ví dụ cấu hình qua chat:
```
/cauhinh set schedules.team_report.time 17:15
/cauhinh set schedules.team_report.chat_id -1001234567890
/cauhinh set schedules.team_report.topic_id 45
/cauhinh set schedules.personal_report.enabled false
```

Gửi riêng báo cáo Kiosk sang group/topic khác (tùy chọn): nếu đặt `kiosk_chat_id` hoặc `kiosk_topic_id` thì báo cáo Kiosk sẽ gửi theo cấu hình riêng đó, báo cáo các dự án khác vẫn gửi vào nhóm team_report. Không đặt thì cả 2 báo cáo gửi chung team_report như mặc định.
```
/cauhinh set schedules.team_report.kiosk_chat_id -1009876543210
/cauhinh set schedules.team_report.kiosk_topic_id 12
```
- Muốn gửi Kiosk vào cùng group nhưng khác topic: chỉ cần đặt `kiosk_topic_id`
- Muốn quay lại gửi chung: `/cauhinh set schedules.team_report.kiosk_chat_id null` và `/cauhinh set schedules.team_report.kiosk_topic_id null`

Trong chat riêng, bạn cũng có thể nhắn tự nhiên như "tiến độ upcode igate" hoặc "báo cáo" mà không cần gõ lệnh.

## 5. Logic sinh báo cáo

- Task "hôm nay": task có ngày hoàn thành = hôm nay, hoặc đã được giao và đang thực hiện
- Task "dự kiến ngày mai": task chưa hoàn thành còn tiếp tục, hoặc task có ngày tạo = ngày mai (kể cả trạng thái "Dự tính giao"). Ngày mai tự bỏ qua T7/CN
- Tên task được làm sạch: bỏ các prefix [TEST], [KIOSK][APP]_,... và tự chèn động từ (Xử lý, Kiểm thử, Tổng hợp, Thực hiện,...) nếu tên task chưa có động từ
- Task lặp lại ở cả hôm nay và ngày mai sẽ tự thêm "Tiếp tục..." ở phần dự kiến

## 6. Theo dõi thay đổi trên file kế hoạch

Bot có thể tự canh các file Google Sheet kế hoạch khác (do đồng nghiệp cập nhật) và
báo khi có nội dung phát sinh hoặc bị sửa.

1. Chia sẻ file sheet cho service account của bot với quyền **Viewer**. Chưa biết địa
   chỉ? Cứ gõ `/nguon them <link>`, bot sẽ báo lại địa chỉ cần share.
2. Trong Telegram, gõ: `/nguon them <link Google Sheet>`
   Muốn đặt tên và chọn tab: `/nguon them <link> | Kế hoạch vnEdu | Sheet1`
3. Bật chức năng: `/theodoi bat`

Các lệnh liên quan:

- `/nguon` — xem các file đang theo dõi, quét lần cuối lúc nào, có lỗi không
- `/nguon tab <id>` — xem các tab; `/nguon tab <id> <tên tab>` để đổi
- `/nguon xoa <id>` — bỏ theo dõi
- `/moi` — xem các thay đổi kể từ bản tin gần nhất

Mặc định bot quét 10 phút/lần trong khung 08:00–18:00 các ngày Thứ Hai–Thứ Sáu; báo ngay
khi có dòng mới, dòng bị xoá, đổi hạn hoặc đổi người phụ trách; các thay đổi còn lại gom
vào bản tin lúc 08:30 và 16:30. Đổi bằng `/cauhinh set watch.<khóa> <giá trị>`.

**Lưu ý khi chạy Docker:** thư mục `state/` phải được mount (đã có sẵn trong
`docker-compose.yml`). Mất thư mục này bot chỉ chụp lại từ đầu, không gửi tin dội.

## 7. Bảo mật

- credentials.json và bot_token là thông tin nhạy cảm, không commit lên git (đã có .gitignore)
- Chỉ user trong admin_ids mới đổi được cấu hình
- Bot chỉ cần quyền Viewer trên sheet
