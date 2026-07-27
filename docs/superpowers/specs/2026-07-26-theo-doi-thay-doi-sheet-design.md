# Spec — Theo dõi & thông báo thay đổi trên Google Sheet kế hoạch

_Ngày: 2026-07-26 · Trạng thái: đã chốt thiết kế, chờ lập kế hoạch triển khai_

## 1. Vấn đề

Hằng ngày phải mở thủ công các file Google Sheet "kế hoạch thực hiện" (do người khác
lập và cập nhật) để dò xem có nội dung phát sinh hay thay đổi gì — tốn thời gian và dễ
bỏ sót. Mong muốn: **bot chủ động báo phần mới và phần bị sửa**, không phải vào sheet
check nữa.

### Không thuộc phạm vi

- Sheet **"Task Đã Điều Phối"** hiện tại **không** được theo dõi thay đổi. File đó do
  chính chủ sở hữu bot chủ động cập nhật nên không có gì để báo. Toàn bộ luồng báo cáo
  hiện có (`/baocao`, `/tai`, `/canhan`, `/trehan`, `/tuan`, 4 job theo lịch) **giữ
  nguyên 100%**.
- Không xác định "ai là người sửa" (cần Drive Activity API + scope mới, và chỉ suy ra
  được ở mức file, không gắn chính xác vào từng ô).
- Không realtime thật qua webhook / Apps Script.
- Không gộp nhiều sheet vào các báo cáo cũ.
- Không trừ ngày lễ.

## 2. Hướng tiếp cận đã chọn

**Bot tự chụp ảnh trạng thái & so sánh (snapshot + diff).** Quét sheet định kỳ, lưu ảnh
chụp xuống đĩa, lần quét sau so với ảnh cũ để tìm dòng mới / dòng mất / ô nào đổi từ gì
sang gì.

Hai hướng đã cân nhắc và loại:

| Hướng | Lý do loại |
|---|---|
| Apps Script `onEdit` đẩy webhook | Phải cài script vào **từng file** và phải có quyền sửa file đó; bot đang chạy polling, không có webserver → phải thêm domain/HTTPS; script hỏng thì im lặng. Chi phí vận hành lớn hơn giá trị thêm. |
| Drive Revisions API | Chỉ cho biết "file có phiên bản mới lúc X", không diff được cấp ô → vẫn phải tự so sánh, tức là làm hướng đã chọn cộng phần thừa. |

Ưu điểm hướng đã chọn: không đụng vào file sheet của người khác, tái dùng `gspread` +
service account sẵn có (chỉ cần cấp **Viewer**), chạy gọn trong kiến trúc job queue hiện
tại. Đánh đổi: trễ tối đa bằng chu kỳ quét (10 phút) — thực tế là điểm cộng vì sửa đi
sửa lại trong một chu kỳ chỉ báo kết quả cuối.

## 3. Kiến trúc

```
Job quét (mỗi 10')  ─→ sheets_client.fetch_rows(spreadsheet_id, worksheet)
                          │
                          ▼
                    change_tracker      (thuần logic, KHÔNG import gspread/telegram)
                      • build_snapshot(rows)      → {khoá: bản ghi}
                      • diff_snapshots(cũ, mới)   → [Change]
                      • match_renames(...)        → ghép cặp xoá+thêm thành đổi tên
                      • apply_filters / classify  → báo ngay | gom bản tin
                          │
                          ▼
                    change_reporter     (thuần logic) → chuỗi HTML đã escape
                          │
                          ▼
                    bot.py → send_long(..., parse_mode=ParseMode.HTML)

                    state_store  ←→  state/watch_state.json
```

### File mới

| File | Trách nhiệm | Phụ thuộc ngoài |
|---|---|---|
| `src/change_tracker.py` | Định danh dòng, so sánh 2 ảnh chụp, dò đổi tên, lọc, phân loại | Không (stdlib) |
| `src/change_reporter.py` | Dựng text HTML cho tin báo ngay & bản tin gom | Không |
| `src/state_store.py` | Đọc/ghi JSON trạng thái, ghi atomic | Không |
| `tests/test_change_tracker.py`, `tests/test_change_reporter.py` | Test bằng `unittest` stdlib | Không |

### File sửa

- `src/sheets_client.py` — **chỉ thêm** `fetch_rows(spreadsheet_id, worksheet_name)` đọc
  bất kỳ file nào (trả về `List[dict]` theo tiêu đề dòng 1) + `list_worksheets()` +
  `service_account_email()`. **Không sửa** `fetch_tasks()` → không rủi ro cho báo cáo cũ.
- `src/bot.py` — job quét, job bản tin, lệnh `/moi`, `/nguon`, `/theodoi`, mở rộng
  `register_jobs` và `HELP_TEXT`, thêm khoá `watch.*` cho `/cauhinh`.
- `config.example.yaml`, `docker-compose.yml`, `.gitignore`, `AGENTS.md`, `MEMORY.md`,
  `README.md`.

### Quyết định thiết kế then chốt

`change_tracker` nhận vào **dict thuần**, không nhận `Task`. Lý do: `sheets_client.py`
`import gspread` ở cấp module, nên chạm vào `Task` là kéo theo gspread — mà máy dev không
cài gspread/pytz/telegram. Tách ra dict thì ba module logic mới test được thật, lần đầu
tiên repo có test tự động chạy được.

## 4. Nguồn theo dõi (`watch.sources`)

Nhánh cấu hình **độc lập** với `google_sheets.*` (vốn dành cho báo cáo).

```yaml
watch:
  enabled: true
  sources:
    - id: vnedu                      # mã ngắn không dấu, dùng làm khoá lưu trạng thái
      name: "Kế hoạch vnEdu"         # tên hiển thị trong thông báo
      spreadsheet_id: "1XyZ..."
      worksheet_name: "Kế hoạch"
      key_column: ""                 # (tùy chọn) cột khoá định danh, xem mục 5
      columns: {}                    # (tùy chọn) ánh xạ cột → trường chuẩn
```

### Hai chế độ đọc, bot tự nhận diện từng file

Các file kế hoạch **mỗi file một kiểu**, nên khi thêm nguồn bot tự chọn:

- **Chế độ `task`** — nhận ra được các cột quen thuộc (tên việc, người làm, hạn, trạng
  thái) qua `HEADER_MAP` sẵn có hoặc qua `columns` khai tay. Thông báo giàu nghĩa:
  `Đồng bộ điểm học kỳ — hạn: 26/07 → 30/07`.
- **Chế độ `generic`** — không nhận ra cột nào. Lấy **ô đầu tiên có nội dung** làm nhãn
  dòng, báo theo **tên cột nguyên văn của sheet**: `Dòng 12 — Nâng cấp máy chủ: cột
  'Tiến độ' đổi 50% → 80%`. Dùng được ngay, không cần cấu hình.

Nâng từ `generic` lên `task` bất cứ lúc nào bằng cách khai `columns`; bot đã in sẵn danh
sách tên cột thật lúc `/nguon them` để copy.

## 5. Định danh dòng & thuật toán so sánh

Google Sheet không có ID dòng → phải tự suy ra dòng nào là dòng nào.

**Khoá định danh, xét theo thứ tự:**

1. `key_column` khai tay cho nguồn đó — chính xác nhất, không bắt buộc.
2. Chế độ `task`: mã/link Jira → STT → vân tay `sha1(tên việc + dự án + ngày tạo)`.
3. Chế độ `generic`: vân tay của **nhãn dòng** (ô đầu tiên có nội dung).
4. Không có gì để bám (dòng trống nhãn): dùng số thứ tự dòng, và **không** báo
   "thêm/xoá" cho nhóm này (tránh nhiễu do chèn/xoá dòng trắng).

Khoá trùng trong cùng một lần quét → gắn hậu tố `#2`, `#3` theo thứ tự xuất hiện.

**Hệ quả có chủ ý:** khoá không phụ thuộc vị trí dòng → **sort lại sheet hoặc chèn dòng
ở giữa thì bot im lặng**. Đây là lý do không dùng số dòng làm khoá chính.

**Dò đổi tên.** Sau khi tính tập "mất" (`removed`) và tập "thêm" (`added`), ghép cặp
trong cùng một nguồn. Hai dòng là cùng một việc bị đổi tên khi:

- các ô giống nhau ≥ **70%**, **hoặc**
- nhãn giống nhau ≥ **60%** (`difflib.SequenceMatcher`) **và** các ô ngoài nhãn còn
  trùng nhau ≥ **50%**.

> Ngưỡng thứ hai ban đầu đặt là "các ô khác trùng khớp hoàn toàn". Đã nới xuống 50% khi
> triển khai: trường hợp rất hay gặp là người ta vừa sửa tên vừa dời hạn cùng lúc — luật
> cũ sẽ báo thành một xoá + một thêm, đọc rối. Đánh đổi: sheet ít cột thì hai dòng có
> nhãn na ná nhau có thể bị gộp nhầm; tin nhắn luôn hiện cả tên cũ lẫn tên mới nên nhìn
> ra ngay.

Ghép tham lam theo điểm cao nhất. Ghép được → báo `đổi tên: A → B` thay vì báo nhầm
thành một xoá + một thêm.

**Cố ý bỏ qua:** dòng trống hoàn toàn; khác biệt chỉ ở khoảng trắng thừa; ô rỗng → rỗng.

**Cố ý báo:** thêm hoặc bớt **cả một cột** của sheet → một dòng riêng, vì đó là dấu hiệu
người ta đổi cấu trúc kế hoạch.

### Cấu trúc `Change`

```python
@dataclass
class Change:
    source_id: str
    kind: str          # "added" | "removed" | "modified" | "renamed" | "column"
    key: str
    label: str         # tên việc / nhãn dòng, để hiển thị
    row: int | None    # số dòng trên sheet, chỉ để tham chiếu
    fields: list[tuple[str, str, str]]   # [(tên cột, giá trị cũ, giá trị mới)]
    record: dict       # bản ghi mới (hoặc bản ghi cũ nếu kind="removed")
```

## 6. Báo ngay, gom bản tin, giờ im lặng

### Phân loại mặc định (đổi được qua `/cauhinh`)

| Báo ngay | Gom vào bản tin |
|---|---|
| Dòng mới, dòng bị xoá | Đổi trạng thái / tiến độ / ngày hoàn thành |
| Đổi hạn / mốc thời gian | Đổi EST, ghi chú, đổi tên |
| Đổi người phụ trách | Thêm/bớt cột, các cột còn lại |

Nguyên tắc: báo ngay dành cho thứ **bắt buộc phải phản ứng** (có việc mới, ai đó dời hạn,
đổi người). Việc chạy đúng tiến độ đọc trong bản tin là đủ. Đây là cách để "vừa báo ngay
vừa gom bản tin" không biến thành "ồn gấp đôi".

### Lịch quét

- Quét mỗi **10 phút**, **08:00–18:00**, **T2–T6** (đều là config).
- Ngoài khung giờ **không quét**.
- **Lần quét đầu tiên của mỗi ngày** phát hiện toàn bộ thay đổi qua đêm. Riêng lần quét
  này, **mọi thay đổi đều bị ép sang loại "gom"** (kể cả loại vốn báo ngay) để chúng đi
  chung một bản tin sáng lúc 08:30, thay vì bắn một loạt tin lúc 08:00.
- Bản tin định kỳ mặc định **08:30** và **16:30**.

> ⚠️ `watch.active_days` dùng **cùng quy ước với các lịch hiện có: `0 = Chủ Nhật`**, nên
> T2–T6 là `[1,2,3,4,5]`. Đây là bẫy đã từng làm bot mất báo cáo Thứ Sáu (xem MEMORY.md
> mục 1). Phải ghi chú ngay tại chỗ trong code và trong `config.example.yaml`.
> Job quét dùng `run_repeating` (không nhận tham số `days`) → tự kiểm tra khung giờ/ngày
> trong hàm, quy đổi `datetime.weekday()` (0=T2) sang quy ước PTB bằng `(wd + 1) % 7`.

### Chống dội tin

Một lần quét ra hơn **15** thay đổi (ai đó dán 50 dòng, kéo fill cả cột) → không liệt kê
hết, gửi một dòng tóm tắt: _"43 thay đổi trong 10 phút qua, chủ yếu ở Kế hoạch vnEdu. Gõ
/moi để xem"_ — rồi đẩy toàn bộ vào hàng chờ.

### Không báo trùng

Thay đổi đã báo ngay **không lặp lại** trong bản tin; bản tin chỉ ghi một dòng
_"(3 thay đổi đã báo ngay trước đó)"_.

### Nơi nhận

Mỗi đích tự chọn nhận gì và lọc gì:

```yaml
watch:
  targets:
    - chat_id: 123456789          # chat riêng
      send: [instant, digest]     # nhận đủ
    - chat_id: -1001234567890     # nhóm team
      topic_id: 12
      send: [digest]              # chỉ bản tin, không làm phiền nhóm
      filters: { projects: [Kiosk] }
  filters:                        # bộ lọc chung; đích không khai thì dùng cái này
    sources: []                   # trống = tất cả; lọc theo id nguồn
    projects: []                  # chỉ có tác dụng ở chế độ task
    assignees: []                 # chỉ có tác dụng ở chế độ task
    keywords: []                  # khớp trên mọi ô — dùng được cho cả chế độ generic
```

Lưu ý về chế độ `generic`: file kiểu này không có khái niệm "dự án" hay "nhân sự", nên
`projects`/`assignees` không áp dụng được. Với các nguồn đó dùng `sources` (lọc cả file)
hoặc `keywords` (khớp chuỗi con, không phân biệt hoa thường, trên mọi ô của bản ghi).
Một thay đổi được gửi khi **thoả mọi nhóm lọc có khai** — nhóm để trống là không lọc.

Lệnh `/moi` chạy độc lập hai kênh trên: gõ lúc nào cũng xem được thay đổi kể từ bản tin
gần nhất, kể cả khi đã tắt hết thông báo tự động.

> **Bộ lọc chỉ chặn ở khâu gửi, không chặn ở khâu chụp ảnh.** Ảnh chụp luôn lưu toàn bộ
> sheet. Nếu lọc từ đầu thì khi mở rộng bộ lọc, hàng trăm dòng cũ sẽ bị hiểu nhầm là mới.

## 7. Quản lý nguồn bằng lệnh `/nguon`

Thêm/bớt file theo dõi **ngay trên Telegram, không restart**. Chỉ admin, giống `/cauhinh`.

```
/nguon                          Liệt kê file đang theo dõi
/nguon them <link sheet>        Thêm file mới (dán nguyên link Google Sheet)
/nguon them <link> | Tên hiển thị | Tên tab
/nguon tab <id>                 Xem các tab trong file
/nguon tab <id> <tên tab>       Đổi tab đang theo dõi
/nguon xoa <id>                 Bỏ theo dõi
```

`/nguon them <link>` làm 5 việc rồi trả lời trong một tin:

1. Bóc `spreadsheet_id` từ link (nhận cả link đầy đủ lẫn id trần).
2. Thử mở file. Không mở được → trả về **email service account** để share quyền Viewer,
   không báo lỗi cụt lủn. (Email service account không phải khoá bí mật; chỉ trả lời
   trong chat riêng với admin. Nội dung `credentials.json` thì không bao giờ.)
3. Chọn tab: ưu tiên tab trùng `worksheet_name` mặc định, không có thì lấy tab đầu tiên
   và **nói rõ đã chọn tab nào** + gợi ý `/nguon tab` để đổi.
4. Đọc dòng tiêu đề, đối chiếu `HEADER_MAP` → chốt chế độ `task`/`generic`. Trả lời dạng
   _"nhận ra 9/11 cột, thiếu Hạn, EST"_ kèm **danh sách tên cột thật** để khai `columns`.
5. Chụp ảnh trạng thái đầu tiên và **không báo gì thêm** — chỉ xác nhận _"Bắt đầu theo
   dõi 'Kế hoạch vnEdu' — 143 dòng. Thay đổi từ giờ trở đi sẽ được báo."_

Kết quả ghi vào `watch.sources` trong `config.yaml` qua `cfg.set`, rồi xoá cache nguồn
trong tiến trình đang chạy → **áp dụng ngay**. Sửa tay `config.yaml` vẫn dùng được (khi
đó mới cần restart).

> `config.yaml` vốn đã mất hết comment sau lần `/cauhinh set` đầu tiên
> (`yaml.safe_dump`). `/nguon` không làm tệ hơn nhưng phải ghi lại trong tài liệu.

## 8. Định dạng tin nhắn

Cả hai loại dùng **HTML** (`parse_mode=ParseMode.HTML`), nội dung động escape qua `_esc`
— cùng quy ước với báo cáo team và `/tai`. Đây là bẫy số 2 trong `AGENTS.md`: thêm chỗ
gửi mà quên `parse_mode` là thẻ `<b>` hiện thô. Tin dài tự cắt qua `send_long`.

**Tin báo ngay:**

```
🔔 Thay đổi kế hoạch · 10:20

📗 Kế hoạch vnEdu
  🆕 Chuẩn hoá dữ liệu giáo viên — Lan · hạn 30/07
  📅 Đồng bộ điểm học kỳ
        hạn: 26/07 → 30/07
  👤 Nâng cấp máy chủ
        phụ trách: Nam → Lan
  🗑️ Đã xoá: Rà soát tài khoản cũ
```

**Bản tin gom:**

```
📬 Bản tin thay đổi · 16:30
Từ 08:30 hôm nay · 2 file · 9 thay đổi

📗 Kế hoạch vnEdu (6)
  ✅ Đồng bộ điểm học kỳ: Đang thực hiện → Hoàn thành
  📝 Nâng cấp máy chủ: Tiến độ 50% → 80%
  ✏️ Đổi tên: Rà soát dữ liệu → Rà soát & làm sạch dữ liệu
  ➕ Sheet có thêm cột "Rủi ro"

📘 Kế hoạch Kiosk (3)
  ...

(3 thay đổi đã báo ngay trước đó)
```

Nguyên tắc: **mỗi thay đổi một dòng, luôn ở dạng `cũ → mới`**. Chế độ `generic` giữ
nguyên văn tên cột của sheet, không dịch — nhìn là biết ngay ô nào trong file.

## 9. Lệnh & cấu hình

| Lệnh | Việc |
|---|---|
| `/moi` | Thay đổi kể từ bản tin gần nhất. Rỗng → _"Không có thay đổi mới kể từ bản tin lúc 08:30"_. |
| `/nguon` | Danh sách file theo dõi: tên, tab, chế độ, số dòng, quét lần cuối, lỗi. |
| `/nguon them\|tab\|xoa` | Quản lý nguồn (mục 7), chỉ admin. |
| `/theodoi bat` / `/theodoi tat` | Bật/tắt nhanh toàn bộ chức năng. |

`/cauhinh` nối dài cho nhánh `watch.*`: `watch.enabled`,
`watch.poll_interval_minutes`, `watch.active_hours`, `watch.active_days`,
`watch.digest_times`, `watch.max_instant_items`, `watch.filters.sources`,
`watch.filters.projects`, `watch.filters.assignees`, `watch.filters.keywords`.
Các khoá lọc và `digest_times` thêm vào `LIST_KEYS` để nhập
kiểu `A, B, C`. Đổi lịch quét → nạp lại job ngay, không restart (giống `schedules.*`).
`HELP_TEXT` cập nhật tương ứng.

## 10. Lưu trạng thái

`state/watch_state.json`, ghi lại sau mỗi lần quét:

```json
{
  "version": 1,
  "sources": {
    "vnedu": {
      "mode": "generic",
      "headers": ["Hạng mục", "Phụ trách", "Tiến độ"],
      "snapshot": { "<khoá>": { "Hạng mục": "...", "Tiến độ": "50%" } },
      "scanned_at": "2026-07-26T10:20:00+07:00",
      "error": null
    }
  },
  "pending": [ { "...": "...", "at": "...", "instant_sent": true } ],
  "last_digest_at": "2026-07-26T08:30:00+07:00"
}
```

- Ghi **atomic**: file tạm rồi `os.replace` → bot bị kill giữa chừng không để lại JSON hỏng.
- File hỏng hoặc sai `version` → bỏ qua, chụp lại từ đầu, báo admin một dòng. **Không bao
  giờ** để file trạng thái lỗi làm bot không khởi động được.
- `pending` xoá sau khi vào bản tin; luôn cắt còn **500 mục mới nhất** phòng khi tắt bản
  tin nhiều ngày.
- `docker-compose.yml` thêm mount `./state:/app/state`; `.gitignore` thêm `state/`.
- **Quên mount:** mỗi lần restart mất ảnh chụp → lần quét kế tiếp không có gì để so → chỉ
  chụp lại và im lặng. Mất lịch sử chứ **không dội tin** — đây là lý do quy tắc "chưa có
  ảnh chụp thì không báo" quan trọng hơn vẻ ngoài của nó.

## 11. Xử lý lỗi

Theo **từng nguồn** — một file hỏng không được làm chết cả job.

- Mất quyền / sai ID / tab bị đổi tên → giữ nguyên ảnh chụp cũ, đánh dấu `error`, nhắn
  admin **đúng một lần** kèm cách khắc phục (share lại cho service account, hoặc
  `/nguon tab` chọn tab mới). Đọc lại được → nhắn _"đã khôi phục"_ và xoá cờ. Không lặp
  lại mỗi 10 phút.
- Lỗi mạng/quota tạm thời → im lặng thử lại vòng sau, chỉ báo sau **3 lần liên tiếp**.
- Toàn bộ vòng lặp quét bọc `try/except` theo từng nguồn + log.
- Quota Google: 6 lần quét/giờ × vài file — không đáng kể so với hạn mức.

## 12. Kiểm thử

`change_tracker`, `change_reporter`, `state_store` không import `gspread`/`telegram`/
`pytz` → chạy được ngay trên máy dev, **không cài thêm gì**:

```bash
python -m unittest discover -s tests
```

Các ca bắt buộc có:

1. Thêm / xoá / sửa cơ bản.
2. **Sort lại sheet → không báo gì.**
3. Chèn dòng ở giữa → chỉ báo dòng mới.
4. Đổi tên được ghép cặp đúng (không thành xoá + thêm).
5. Nhãn trùng nhau → hậu tố `#2` hoạt động.
6. Chế độ `generic` (tên cột lạ hoàn toàn).
7. Thêm / bớt cột của sheet.
8. Bộ lọc chỉ chặn khi gửi, ảnh chụp vẫn đủ.
9. Phân loại báo-ngay / gom đúng bảng mục 6.
10. Quá 15 thay đổi → chuyển sang tin tóm tắt.
11. Lần chạy đầu (chưa có ảnh chụp) → không báo gì.
12. File trạng thái hỏng → khởi động được, chụp lại từ đầu.
13. Lần quét đầu tiên trong ngày → mọi thay đổi bị ép sang loại "gom", không tin báo ngay.
14. Trong/ngoài khung giờ và ngày làm việc → quyết định quét hay không đúng quy ước `0 = CN`.

Phần chạm `gspread`/`telegram` không test tự động được → giữ quy ước hiện có:
`python -m py_compile src/*.py` + script stub module ngoài trong scratchpad.

## 13. Tài liệu cần cập nhật

- `AGENTS.md` — mục mới "Theo dõi thay đổi", bổ sung checklist bẫy.
- `MEMORY.md` — quyết định & lý do (vì sao snapshot chứ không webhook; vì sao khoá không
  theo vị trí dòng; vì sao lọc ở khâu gửi).
- `config.example.yaml` — khối `watch` kèm chú thích quy ước `0 = Chủ Nhật`.
- `README.md` — hướng dẫn thêm file theo dõi cho người dùng cuối.
- `HELP_TEXT` trong `bot.py`.

## 14. Tiêu chí hoàn thành

- Thêm được một file sheet mới vào theo dõi hoàn toàn bằng lệnh Telegram, không restart.
- Sửa một ô trên file đó → trong vòng ≤ 10 phút nhận được tin báo đúng nội dung
  `cũ → mới`, đúng nơi đã cấu hình.
- Sort lại sheet → không nhận được tin nào.
- Bản tin 08:30 và 16:30 gửi đúng giờ, không lặp lại nội dung đã báo ngay.
- `/moi` và `/nguon` trả lời đúng trạng thái.
- `python -m unittest discover -s tests` xanh; `python -m py_compile src/*.py` sạch.
- Các báo cáo cũ hoạt động y như trước.
