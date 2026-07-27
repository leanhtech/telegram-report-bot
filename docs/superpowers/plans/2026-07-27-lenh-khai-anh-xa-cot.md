# Kế hoạch triển khai — Lệnh khai ánh xạ cột & cột khoá

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khai được `columns` (ánh xạ tên cột → ý nghĩa) và `key_column` của một nguồn theo dõi hoàn toàn bằng lệnh Telegram, không mở `config.yaml`, không restart, và không sinh thông báo giả sau khi đổi.

**Architecture:** Phần logic thuần (`VALID_FIELDS`, `describe_mode`, `missing_for_task`, `match_column`) đặt trong `change_tracker.py` để test được offline. Phần chạm Telegram/sheet ở lại `bot.py`. `cmd_nguon` (đang 164 dòng, 4 nhánh) được tách thành hàm định tuyến + 6 hàm con trước khi thêm 2 nhánh mới.

**Tech Stack:** Python 3.12 · `python-telegram-bot[job-queue]==21.10` · `gspread==6.1.4` · test bằng `unittest` (stdlib, **không thêm dependency**).

Spec: [`docs/superpowers/specs/2026-07-27-lenh-khai-anh-xa-cot-design.md`](../specs/2026-07-27-lenh-khai-anh-xa-cot-design.md)

## Global Constraints

- **Ngôn ngữ:** mọi comment, docstring, chuỗi hiển thị cho người dùng và commit message viết **tiếng Việt**. Thuật ngữ kỹ thuật giữ tiếng Anh. Giữ văn phong của code hiện có.
- **Không thêm dependency mới.** Test dùng `unittest` stdlib.
- **`change_tracker.py` không được import `gspread`, `telegram`, `pytz`, hay `src.sheets_client`** — điều kiện để test chạy được trên máy dev.
- **Chỉ admin** dùng được `/nguon` — điều kiện `is_admin(update)` ở đầu `cmd_nguon` phải giữ nguyên.
- ⚠️ **Đổi `columns` hoặc `key_column` là đổi cách sinh khoá định danh dòng** → **bắt buộc** bỏ ảnh chụp cũ của nguồn đó và lưu state, nếu không lần quét kế tiếp dội một loạt thay đổi giả.
- **Kiểm tra trước khi ghi:** tên cột phải có thật trong sheet, ý nghĩa phải thuộc `VALID_FIELDS`. Sai thì từ chối và **không ghi gì vào config**.
- **Không đụng** `report_generator.py`, `sheets_client.py`, thuật toán so sánh trong `change_tracker` (`detect_mode` chỉ được sửa đúng chỗ nêu ở Task 1), `change_reporter.py`, các job, hay các lệnh khác.
- **Không commit** `config.yaml`, `credentials.json`, thư mục `state/`.
- Máy dev **không cài** `gspread`/`pytz`/`telegram` → không import được `src.bot`. Xác minh bằng `python -m py_compile src/*.py` + đối chiếu diff.
- Nhánh làm việc: `feature/khai-anh-xa-cot` (đã tồn tại, spec đã commit ở `1ae1ec7`).

## Cấu trúc file

| File | Thay đổi |
|---|---|
| `src/change_tracker.py` | Thêm `VALID_FIELDS`, `CORE_FIELDS`, `CORE_REQUIRED`, `describe_mode`, `missing_for_task`, `match_column`; `detect_mode` dùng lại hằng số lõi |
| `src/bot.py` | Tách `cmd_nguon` thành hàm con; thêm `_nguon_cot`, `_nguon_khoa`, `_tim_nguon`, `_doc_headers`, `_bo_anh_chup`, `_mo_ta_anh_xa`; sửa `HELP_TEXT` |
| `tests/test_change_tracker.py` | Thêm class `TestMoTaCheDo` (7 test) |
| `AGENTS.md`, `README.md` | Bổ sung 2 lệnh mới |

Lệnh chạy toàn bộ test (từ thư mục gốc repo):

```bash
python -m unittest discover -s tests -t . -v
```

---

### Task 1: Logic thuần mô tả chế độ (`change_tracker`)

**Files:**
- Modify: `src/change_tracker.py` — sửa `detect_mode` (2 dòng), thêm khối mới vào cuối file
- Test: `tests/test_change_tracker.py` — thêm class test trước `if __name__ == "__main__":`

**Interfaces:**
- Consumes: `FIELD_ALIASES`, `detect_mode`, `_norm` (đã có trong file).
- Produces:
  - `CORE_FIELDS: tuple[str, ...]` = `("assignee", "due", "status")`
  - `CORE_REQUIRED: int` = `2`
  - `VALID_FIELDS: frozenset[str]` = `frozenset(FIELD_ALIASES)`
  - `describe_mode(headers: list[str], columns_override: dict|None = None) -> tuple[str, int, int]` — `(chế độ, số cột đã nhận ra ý nghĩa, tổng số cột)`
  - `missing_for_task(headers: list[str], columns_override: dict|None = None) -> list[str]` — rỗng nghĩa là đã đủ điều kiện chế độ `task`
  - `match_column(headers: list[str], name: str) -> str|None` — tên cột gốc khớp `name`, bỏ qua hoa/thường và khoảng trắng thừa

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_change_tracker.py`, ngay trước `if __name__ == "__main__":`

```python
class TestMoTaCheDo(unittest.TestCase):
    def test_valid_fields_dung_bang_khoa_cua_tu_dien(self):
        # Dẫn xuất, không chép tay -> không bao giờ lệch với FIELD_ALIASES.
        self.assertEqual(ct.VALID_FIELDS, frozenset(ct.FIELD_ALIASES))

    def test_sheet_la_thi_generic_va_khong_nhan_ra_cot_nao(self):
        mode, nhan_ra, tong = ct.describe_mode(GENERIC_HEADERS)
        self.assertEqual(mode, "generic")
        self.assertEqual(nhan_ra, 0)
        self.assertEqual(tong, len(GENERIC_HEADERS))

    def test_khai_du_columns_thi_len_che_do_task(self):
        override = {"Nội dung triển khai": "name", "Bên liên quan": "assignee",
                    "Ghi nhận": "status"}
        mode, nhan_ra, tong = ct.describe_mode(GENERIC_HEADERS, override)
        self.assertEqual(mode, "task")
        self.assertEqual(nhan_ra, 3)
        self.assertEqual(tong, len(GENERIC_HEADERS))

    def test_thieu_ca_ten_viec_lan_cot_loi(self):
        thieu = ct.missing_for_task(GENERIC_HEADERS)
        self.assertIn("name", thieu)
        self.assertTrue(any("thêm 2" in t for t in thieu), thieu)

    def test_chi_con_thieu_mot_cot_loi(self):
        override = {"Nội dung triển khai": "name", "Bên liên quan": "assignee"}
        thieu = ct.missing_for_task(GENERIC_HEADERS, override)
        self.assertNotIn("name", thieu)
        self.assertTrue(any("thêm 1" in t for t in thieu), thieu)

    def test_du_dieu_kien_thi_khong_thieu_gi(self):
        self.assertEqual(ct.missing_for_task(TASK_HEADERS), [])

    def test_khop_ten_cot_bo_qua_hoa_thuong_va_khoang_trang(self):
        self.assertEqual(ct.match_column(GENERIC_HEADERS, "  bên LIÊN quan "),
                         "Bên liên quan")
        self.assertIsNone(ct.match_column(GENERIC_HEADERS, "Không có cột này"))
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

```bash
python -m unittest tests.test_change_tracker.TestMoTaCheDo -v
```

Kỳ vọng: FAIL — `AttributeError: module 'src.change_tracker' has no attribute 'VALID_FIELDS'`.

- [ ] **Step 3: Cho `detect_mode` dùng hằng số lõi**

Thêm hai hằng số ngay **trên** hàm `detect_mode` (sau khối `FIELD_ALIASES` và các helper `_norm`/`_sha`):

```python
# Điều kiện đủ để tin là bảng task: có tên việc + ít nhất 2 trong 3 trường lõi.
CORE_FIELDS = ("assignee", "due", "status")
CORE_REQUIRED = 2
```

Rồi trong `detect_mode`, thay:

```python
    found = set(field_map.values())
    core = found & {"assignee", "due", "status"}
    mode = "task" if ("name" in found and len(core) >= 2) else "generic"
    return mode, field_map
```

thành:

```python
    found = set(field_map.values())
    core = found & set(CORE_FIELDS)
    mode = "task" if ("name" in found and len(core) >= CORE_REQUIRED) else "generic"
    return mode, field_map
```

- [ ] **Step 4: Thêm khối mới vào cuối `src/change_tracker.py`**

```python
# ------------------------------------------------------------------
# Mô tả chế độ đọc của một sheet (phục vụ lệnh /nguon cot)
# ------------------------------------------------------------------
# Dẫn xuất từ FIELD_ALIASES để danh sách ý nghĩa hợp lệ không bao giờ lệch
# với từ điển nhận diện cột.
VALID_FIELDS = frozenset(FIELD_ALIASES)


def match_column(headers: List[str], name: str) -> Optional[str]:
    """Tên cột gốc khớp `name`, bỏ qua hoa/thường và khoảng trắng thừa.

    Để người dùng gõ 'bên liên quan' vẫn khớp cột 'Bên liên quan'.
    """
    for header in headers:
        if _norm(header) == _norm(name):
            return header
    return None


def describe_mode(headers: List[str],
                  columns_override: Optional[Dict[str, str]] = None
                  ) -> Tuple[str, int, int]:
    """(chế độ, số cột đã nhận ra ý nghĩa, tổng số cột)."""
    mode, field_map = detect_mode(headers, columns_override)
    return mode, len(field_map), len(headers)


def missing_for_task(headers: List[str],
                     columns_override: Optional[Dict[str, str]] = None
                     ) -> List[str]:
    """Những gì còn thiếu để sheet đủ điều kiện chạy chế độ 'task'.

    Trả về danh sách rỗng nghĩa là đã đủ. Dùng để nói cho người dùng biết còn
    phải khai thêm gì, thay vì để họ khai vài cột rồi không hiểu sao vẫn generic.
    """
    _mode, field_map = detect_mode(headers, columns_override)
    found = set(field_map.values())
    thieu: List[str] = []
    if "name" not in found:
        thieu.append("name")
    con_thieu = CORE_REQUIRED - len(found & set(CORE_FIELDS))
    if con_thieu > 0:
        thieu.append("thêm %d trong {%s}" % (con_thieu, ", ".join(CORE_FIELDS)))
    return thieu
```

- [ ] **Step 5: Chạy test, phải xanh**

```bash
python -m unittest discover -s tests -t . -v
```

Kỳ vọng: `OK` — 78 test pass (71 cũ + 7 mới). Các test cũ của `detect_mode` phải vẫn xanh, chứng minh việc thay hằng số không đổi hành vi.

- [ ] **Step 6: Commit**

```bash
python -m py_compile src/change_tracker.py
git add src/change_tracker.py tests/test_change_tracker.py
git commit -m "feat(watch): mô tả chế độ đọc và khớp tên cột cho lệnh khai ánh xạ"
```

---

### Task 2: Tách `cmd_nguon` thành hàm con (refactor thuần)

**Files:**
- Modify: `src/bot.py` — thay toàn bộ khối `cmd_nguon` (hiện ở dòng 522–685)

**Interfaces:**
- Consumes: `is_admin`, `cfg`, `state_store`, `watch_state_path`, `now_dt`, `sheets`, `ct`, `_boc_spreadsheet_id`, `_slug` (đã có).
- Produces: `NGUON_CU_PHAP: str` · `_bo_anh_chup(state: dict, sid: str) -> None` · `_nguon_liet_ke(update, sources, state)` · `_nguon_them(update, sources, state, args)` · `_nguon_tab(update, sources, state, args)` · `_nguon_xoa(update, sources, state, args)` — bốn hàm sau đều là `async`, nhận `args` là **nguyên vẹn** `context.args` nên chỉ số phần tử giữ y như code cũ.

> ⚠️ **Đây là refactor thuần — không được đổi một chữ nào trong nội dung trả lời hay thứ tự kiểm tra.** Bê nguyên từng dòng logic sang hàm mới. Người review sẽ đối chiếu diff để xác nhận điều này.

- [ ] **Step 1: Thay khối `cmd_nguon` hiện tại bằng phiên bản đã tách**

Xoá toàn bộ hàm `cmd_nguon` cũ (từ dòng `async def cmd_nguon(...)` tới hết dòng `"/nguon xoa <id>")`), thay bằng:

```python
NGUON_CU_PHAP = (
    "Cú pháp:\n"
    "/nguon\n"
    "/nguon them <link> | Tên hiển thị | Tên tab\n"
    "/nguon tab <id> [tên tab]\n"
    "/nguon xoa <id>"
)


def _bo_anh_chup(state: dict, sid: str) -> None:
    """Bỏ ảnh chụp cũ của một nguồn rồi lưu state.

    Đổi tab / ánh xạ cột / cột khoá đều làm đổi cách sinh khoá định danh dòng,
    nên ảnh chụp cũ không còn khớp. Không bỏ đi thì lần quét kế tiếp sẽ dội một
    loạt thay đổi giả.
    """
    (state.get("sources") or {}).pop(sid, None)
    state_store.save(watch_state_path(), state)


async def _nguon_liet_ke(update: Update, sources: list, state: dict):
    """Liệt kê các file đang theo dõi."""
    if not sources:
        await update.message.reply_text(
            "Chưa theo dõi file nào.\n"
            "Thêm: /nguon them <link Google Sheet>")
        return
    parts = ["Các file đang theo dõi:"]
    for src in sources:
        sid = str(src.get("id"))
        info = (state.get("sources") or {}).get(sid) or {}
        trang_thai = "LỖI: %s" % info["error"] if info.get("error") else "OK"
        parts.append(
            "- %s (%s)\n  tab: %s | chế độ: %s | %s dòng\n  quét lúc: %s | %s"
            % (src.get("name") or sid, sid,
               src.get("worksheet_name") or "(tab đầu tiên)",
               info.get("mode") or "?", info.get("rows", "?"),
               info.get("scanned_at") or "chưa quét", trang_thai))
    parts.append("")
    parts.append("Thêm: /nguon them <link> | Tên hiển thị | Tên tab")
    await update.message.reply_text("\n".join(parts))


async def _nguon_them(update: Update, sources: list, state: dict, args: list):
    """Thêm một file sheet vào danh sách theo dõi."""
    phan = " ".join(args[1:]).split("|")
    sheet_id = _boc_spreadsheet_id(phan[0])
    if not sheet_id:
        await update.message.reply_text(
            "Không nhận ra link/ID sheet. Dán nguyên link trên thanh địa chỉ.")
        return
    ten = phan[1].strip() if len(phan) > 1 and phan[1].strip() else ""
    tab = phan[2].strip() if len(phan) > 2 and phan[2].strip() else ""

    try:
        tabs = sheets.list_worksheets(sheet_id)
    except Exception as e:
        await update.message.reply_text(
            "Không mở được file: %s\n\n"
            "Hãy chia sẻ file cho địa chỉ sau với quyền Viewer rồi thử lại:\n%s"
            % (e, sheets.service_account_email() or "(chưa đọc được credentials)"))
        return

    if tab and tab not in tabs:
        await update.message.reply_text(
            "File không có tab “%s”. Các tab hiện có: %s" % (tab, ", ".join(tabs)))
        return
    if not tab:
        mac_dinh = cfg.get("google_sheets.worksheet_name", "")
        tab = mac_dinh if mac_dinh in tabs else (tabs[0] if tabs else "")

    try:
        headers, rows = sheets.fetch_rows(sheet_id, tab)
    except Exception as e:
        await update.message.reply_text("Đọc được file nhưng lỗi khi đọc tab: %s" % e)
        return

    ten = ten or tab or sheet_id[:8]
    sid = _slug(ten)
    dang_co = {str(s.get("id")) for s in sources}
    goc, dem = sid, 2
    while sid in dang_co:
        sid, dem = "%s%d" % (goc, dem), dem + 1

    mode, field_map = ct.detect_mode(headers)
    snapshot = ct.build_snapshot(rows, headers, field_map, mode)

    sources.append({"id": sid, "name": ten, "spreadsheet_id": sheet_id,
                    "worksheet_name": tab})
    cfg.set("watch.sources", sources)

    # Chụp ảnh đầu tiên và KHÔNG báo gì — nếu không sẽ dội hàng trăm "dòng mới".
    state.setdefault("sources", {})[sid] = {
        "mode": mode, "headers": headers, "field_map": field_map,
        "snapshot": snapshot, "scanned_at": now_dt().isoformat(),
        "rows": len(snapshot), "error": None, "fail_count": 0,
    }
    state_store.save(watch_state_path(), state)

    nhan_ra = sorted(set(field_map.values()))
    parts = [
        "Bắt đầu theo dõi “%s” (id: %s) — %d dòng." % (ten, sid, len(snapshot)),
        "Tab: %s" % tab,
        "Chế độ: %s (%d/%d cột nhận ra ý nghĩa)" % (mode, len(nhan_ra), len(headers)),
        "Các cột trong sheet: %s" % ", ".join(headers),
    ]
    if mode == "generic":
        parts.append("")
        parts.append(
            "Đang chạy chế độ bảng chung — bot báo theo tên cột nguyên văn. "
            "Muốn báo giàu nghĩa hơn thì khai ánh xạ cột trong config.yaml "
            "(watch.sources -> columns).")
    parts.append("")
    parts.append("Thay đổi từ giờ trở đi sẽ được báo.")
    if not cfg.get("watch.enabled", False):
        parts.append("Lưu ý: chức năng đang TẮT — bật bằng /theodoi bat")
    await update.message.reply_text("\n".join(parts))


async def _nguon_tab(update: Update, sources: list, state: dict, args: list):
    """Xem hoặc đổi tab đang theo dõi của một nguồn."""
    sid = args[1]
    src = next((s for s in sources if str(s.get("id")) == sid), None)
    if not src:
        await update.message.reply_text("Không có nguồn id “%s”." % sid)
        return
    try:
        tabs = sheets.list_worksheets(src.get("spreadsheet_id"))
    except Exception as e:
        await update.message.reply_text("Không mở được file: %s" % e)
        return
    if len(args) == 2:
        await update.message.reply_text(
            "Các tab của “%s”:\n- %s\n\nĐổi: /nguon tab %s <tên tab>"
            % (src.get("name") or sid, "\n- ".join(tabs), sid))
        return
    tab_moi = " ".join(args[2:]).strip()
    if tab_moi not in tabs:
        await update.message.reply_text(
            "Không có tab “%s”. Các tab hiện có: %s" % (tab_moi, ", ".join(tabs)))
        return
    src["worksheet_name"] = tab_moi
    cfg.set("watch.sources", sources)
    # Đổi tab = đổi dữ liệu hoàn toàn -> bỏ ảnh chụp cũ, chụp lại, không báo.
    _bo_anh_chup(state, sid)
    await update.message.reply_text(
        "Đã đổi tab của “%s” sang “%s”. Sẽ chụp lại ảnh ở lần quét tới."
        % (src.get("name") or sid, tab_moi))


async def _nguon_xoa(update: Update, sources: list, state: dict, args: list):
    """Bỏ theo dõi một nguồn."""
    sid = args[1]
    con_lai = [s for s in sources if str(s.get("id")) != sid]
    if len(con_lai) == len(sources):
        await update.message.reply_text("Không có nguồn id “%s”." % sid)
        return
    cfg.set("watch.sources", con_lai)
    (state.get("sources") or {}).pop(sid, None)
    state["pending"] = [p for p in (state.get("pending") or [])
                        if p.get("source_id") != sid]
    state_store.save(watch_state_path(), state)
    await update.message.reply_text("Đã bỏ theo dõi nguồn “%s”." % sid)


async def cmd_nguon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quản lý danh sách file sheet đang được theo dõi (chỉ admin)."""
    if not is_admin(update):
        await update.message.reply_text("Bạn không có quyền quản lý nguồn theo dõi.")
        return

    args = context.args or []
    sources = list(cfg.get("watch.sources", []) or [])
    state = state_store.load(watch_state_path())

    if not args:
        await _nguon_liet_ke(update, sources, state)
        return

    lenh = args[0].lower()
    if lenh == "them" and len(args) >= 2:
        await _nguon_them(update, sources, state, args)
        return
    if lenh == "tab" and len(args) >= 2:
        await _nguon_tab(update, sources, state, args)
        return
    if lenh == "xoa" and len(args) >= 2:
        await _nguon_xoa(update, sources, state, args)
        return

    await update.message.reply_text(NGUON_CU_PHAP)
```

- [ ] **Step 2: Xác minh không đổi hành vi**

```bash
python -m py_compile src/*.py && python -m unittest discover -s tests -t .
```

Kỳ vọng: py_compile im lặng; 78 test `OK`.

Rồi đối chiếu bằng mắt: `git diff` phải cho thấy các dòng logic của 4 nhánh cũ chỉ **đổi vị trí và mức thụt lề**, không đổi nội dung — trừ đúng một chỗ: `_nguon_tab` dùng `_bo_anh_chup(state, sid)` thay cho hai dòng `pop` + `save` (tương đương).

- [ ] **Step 3: Commit**

```bash
git add src/bot.py
git commit -m "refactor(watch): tách cmd_nguon thành các hàm con, không đổi hành vi"
```

---

### Task 3: Nhánh `/nguon cot`

**Files:**
- Modify: `src/bot.py` — thêm `_tim_nguon`, `_doc_headers`, `_mo_ta_anh_xa`, `_nguon_cot`; nối nhánh vào `cmd_nguon`; mở rộng `NGUON_CU_PHAP`

**Interfaces:**
- Consumes: `ct.describe_mode`, `ct.missing_for_task`, `ct.match_column`, `ct.VALID_FIELDS` (Task 1) · `_bo_anh_chup`, `NGUON_CU_PHAP` (Task 2) · `sheets.fetch_rows`, `sheets.service_account_email`, `cfg.set`.
- Produces: `_tim_nguon(sources: list, sid: str) -> dict|None` · `_doc_headers(update, src) -> list[str]|None` (async; lỗi thì đã trả lời và trả `None`) · `_mo_ta_anh_xa(src, headers, columns, sid) -> list[str]` · `_nguon_cot(update, sources, state, args)` (async).

- [ ] **Step 1: Thêm ba helper**

Chèn ngay **trên** `_nguon_liet_ke`:

```python
def _tim_nguon(sources: list, sid: str):
    """Nguồn có id `sid`, hoặc None."""
    return next((s for s in sources if str(s.get("id")) == sid), None)


# Sau khi thêm hàm này, sửa `_nguon_tab` dùng nó thay cho dòng `next(...)` viết
# tay, để chỉ còn một chỗ tra cứu nguồn theo id:
#     src = _tim_nguon(sources, sid)


async def _doc_headers(update: Update, src: dict):
    """Tiêu đề cột thật của một nguồn. Lỗi -> đã trả lời người dùng, trả None."""
    try:
        headers, _rows = sheets.fetch_rows(src.get("spreadsheet_id"),
                                           src.get("worksheet_name") or "")
        return headers
    except Exception as e:
        await update.message.reply_text(
            "Không đọc được sheet: %s\n\n"
            "Nếu là lỗi quyền, hãy chia sẻ file cho địa chỉ sau với quyền Viewer:\n%s"
            % (e, sheets.service_account_email() or "(chưa đọc được credentials)"))
        return None


def _mo_ta_anh_xa(src: dict, headers: list, columns: dict, sid: str) -> list:
    """Các dòng mô tả ánh xạ cột hiện tại của một nguồn."""
    mode, nhan_ra, tong = ct.describe_mode(headers, columns)
    dong = ["Ánh xạ cột của “%s” (id: %s)" % (src.get("name") or sid, sid), ""]
    if columns:
        for cot, y_nghia in columns.items():
            dong.append("- %s = %s" % (cot, y_nghia))
    else:
        dong.append("(chưa khai cột nào — bot đang tự đoán)")
    dong.append("")
    dong.append("Cột thật trong sheet: %s" % ", ".join(headers))
    dong.append("Cột khoá: %s" % (src.get("key_column") or "(chưa đặt)"))
    dong.append("Chế độ: %s (%d/%d cột có ý nghĩa)" % (mode, nhan_ra, tong))
    thieu = ct.missing_for_task(headers, columns)
    if thieu:
        dong.append("Còn thiếu để lên chế độ task: %s" % ", ".join(thieu))
    dong.append("")
    dong.append("Khai: /nguon cot %s <Tên cột> = <ý nghĩa>" % sid)
    dong.append("Gỡ:  /nguon cot %s xoa <Tên cột>" % sid)
    dong.append("Ý nghĩa hợp lệ: %s" % ", ".join(sorted(ct.VALID_FIELDS)))
    return dong
```

- [ ] **Step 2: Thêm `_nguon_cot`**

Chèn ngay **dưới** `_nguon_xoa`:

```python
async def _nguon_cot(update: Update, sources: list, state: dict, args: list):
    """Xem / khai / gỡ ánh xạ cột của một nguồn.

    Đổi ánh xạ là đổi cách sinh khoá định danh dòng nên luôn phải bỏ ảnh chụp cũ.
    """
    sid = args[1]
    src = _tim_nguon(sources, sid)
    if not src:
        await update.message.reply_text("Không có nguồn id “%s”." % sid)
        return
    headers = await _doc_headers(update, src)
    if headers is None:
        return

    columns = dict(src.get("columns") or {})
    phan = " ".join(args[2:]).strip()

    # --- Chỉ xem ---
    if not phan:
        await update.message.reply_text(
            "\n".join(_mo_ta_anh_xa(src, headers, columns, sid)))
        return

    truoc = ct.describe_mode(headers, columns)[0]

    # --- Gỡ ánh xạ ---
    if phan.lower().startswith("xoa "):
        ten_cot = phan[4:].strip()
        goc = ct.match_column(list(columns), ten_cot)
        if not goc:
            await update.message.reply_text(
                "Cột “%s” chưa được khai ánh xạ nên không có gì để gỡ." % ten_cot)
            return
        columns.pop(goc)
        src["columns"] = columns
        cfg.set("watch.sources", sources)
        _bo_anh_chup(state, sid)
        sau, nhan_ra, tong = ct.describe_mode(headers, columns)
        await update.message.reply_text(
            "Đã gỡ ánh xạ của “%s”.\n"
            "Đã nhận ra ý nghĩa %d/%d cột.\n"
            "Chế độ: %s → %s\n"
            "Sẽ chụp lại ảnh ở lần quét tới (không báo tin giả)."
            % (goc, nhan_ra, tong, truoc, sau))
        return

    # --- Khai một cột ---
    if "=" not in phan:
        await update.message.reply_text(
            "Cú pháp: /nguon cot %s <Tên cột> = <ý nghĩa>\n"
            "Gỡ:     /nguon cot %s xoa <Tên cột>\n"
            "Xem:    /nguon cot %s" % (sid, sid, sid))
        return
    # Tách ở dấu '=' cuối cùng: tên cột có thể chứa '=', tên trường thì không.
    ten_cot, y_nghia = phan.rsplit("=", 1)
    ten_cot, y_nghia = ten_cot.strip(), y_nghia.strip().lower()

    cot_goc = ct.match_column(headers, ten_cot)
    if not cot_goc:
        await update.message.reply_text(
            "Sheet không có cột “%s”.\nCác cột thật: %s" % (ten_cot, ", ".join(headers)))
        return
    if y_nghia not in ct.VALID_FIELDS:
        await update.message.reply_text(
            "Ý nghĩa “%s” không hợp lệ.\nHợp lệ: %s"
            % (y_nghia, ", ".join(sorted(ct.VALID_FIELDS))))
        return

    columns[cot_goc] = y_nghia
    src["columns"] = columns
    cfg.set("watch.sources", sources)
    _bo_anh_chup(state, sid)

    sau, nhan_ra, tong = ct.describe_mode(headers, columns)
    dong = ["Đã khai “%s” = %s." % (cot_goc, y_nghia),
            "Đã nhận ra ý nghĩa %d/%d cột." % (nhan_ra, tong),
            "Chế độ: %s → %s" % (truoc, sau)]
    thieu = ct.missing_for_task(headers, columns)
    if thieu:
        dong.append("Còn thiếu để lên chế độ task: %s" % ", ".join(thieu))
    dong.append("Sẽ chụp lại ảnh ở lần quét tới (không báo tin giả).")
    await update.message.reply_text("\n".join(dong))
```

- [ ] **Step 3: Nối nhánh vào `cmd_nguon` và mở rộng cú pháp**

Trong `cmd_nguon`, thêm ngay **trước** dòng `await update.message.reply_text(NGUON_CU_PHAP)`:

```python
    if lenh == "cot" and len(args) >= 2:
        await _nguon_cot(update, sources, state, args)
        return
```

Và sửa `NGUON_CU_PHAP`, thêm một dòng trước dòng `/nguon xoa <id>`:

```python
    "/nguon cot <id> [<Tên cột> = <ý nghĩa> | xoa <Tên cột>]\n"
```

- [ ] **Step 4: Xác minh bằng script stub**

Máy dev không cài `telegram`/`gspread` nên không import được `src.bot`. Kiểm phần tách chuỗi và kiểm tra hợp lệ — vốn là chỗ dễ sai nhất — bằng script dùng chính hàm thuần của `change_tracker`:

```python
# scratchpad/kiem_tra_tach_cot.py
from src import change_tracker as ct

HEADERS = ["Mã", "Nội dung triển khai", "Bên liên quan", "Chốt xong trước"]

def tach(phan):
    """Mô phỏng đúng đoạn tách chuỗi trong _nguon_cot."""
    ten_cot, y_nghia = phan.rsplit("=", 1)
    return ten_cot.strip(), y_nghia.strip().lower()

# Tách bình thường
assert tach("Bên liên quan = assignee") == ("Bên liên quan", "assignee")
# Thừa khoảng trắng
assert tach("  Bên liên quan   =   ASSIGNEE  ") == ("Bên liên quan", "assignee")
# Tên cột chứa '=' -> phải tách ở dấu '=' CUỐI
assert tach("Cột a=b = due") == ("Cột a=b", "due")

# Khớp tên cột bỏ qua hoa/thường
assert ct.match_column(HEADERS, "bên liên QUAN") == "Bên liên quan"
assert ct.match_column(HEADERS, "không có") is None

# Ý nghĩa hợp lệ
assert "assignee" in ct.VALID_FIELDS
assert "nguoi_lam" not in ct.VALID_FIELDS

# Khai đủ thì lên chế độ task
cols = {"Nội dung triển khai": "name", "Bên liên quan": "assignee",
        "Chốt xong trước": "due"}
assert ct.describe_mode(HEADERS, cols) == ("task", 3, 4), ct.describe_mode(HEADERS, cols)
assert ct.missing_for_task(HEADERS, cols) == []
# Khai thiếu thì còn báo thiếu
assert ct.missing_for_task(HEADERS, {"Nội dung triển khai": "name"}) == [
    "thêm 2 trong {assignee, due, status}"]
print("OK")
```

```bash
python "C:/Users/LeAnh/AppData/Local/Temp/claude/C--Users-LeAnh-Documents-telegram-report-bot/6620f28f-ea26-4934-acd6-ada4c49cf165/scratchpad/kiem_tra_tach_cot.py"
```

Kỳ vọng: `OK`, không AssertionError.

- [ ] **Step 5: Kiểm tra cú pháp, test, commit**

```bash
python -m py_compile src/*.py && python -m unittest discover -s tests -t .
git add src/bot.py
git commit -m "feat(watch): lệnh /nguon cot khai và gỡ ánh xạ cột"
```

---

### Task 4: Nhánh `/nguon khoa`, HELP_TEXT và tài liệu

**Files:**
- Modify: `src/bot.py` — thêm `_nguon_khoa`, nối nhánh, mở rộng `NGUON_CU_PHAP` và `HELP_TEXT`, sửa gợi ý cuối của `_nguon_them`
- Modify: `AGENTS.md`, `README.md`

**Interfaces:**
- Consumes: `_tim_nguon`, `_doc_headers`, `_bo_anh_chup` (Task 2–3) · `ct.match_column` (Task 1).
- Produces: `_nguon_khoa(update, sources, state, args)` (async).

- [ ] **Step 1: Thêm `_nguon_khoa`**

Chèn ngay **dưới** `_nguon_cot`:

```python
async def _nguon_khoa(update: Update, sources: list, state: dict, args: list):
    """Xem / đặt / bỏ cột khoá định danh của một nguồn.

    Cột khoá quyết định 'dòng nào là dòng nào' qua các lần quét, nên đổi nó cũng
    phải bỏ ảnh chụp cũ như khi đổi ánh xạ cột.
    """
    sid = args[1]
    src = _tim_nguon(sources, sid)
    if not src:
        await update.message.reply_text("Không có nguồn id “%s”." % sid)
        return

    phan = " ".join(args[2:]).strip()
    hien_tai = src.get("key_column") or ""

    # --- Chỉ xem ---
    if not phan:
        await update.message.reply_text(
            "Cột khoá của “%s”: %s\n\n"
            "Đặt: /nguon khoa %s <Tên cột>\n"
            "Bỏ:  /nguon khoa %s xoa"
            % (src.get("name") or sid, hien_tai or "(chưa đặt)", sid, sid))
        return

    # --- Bỏ cột khoá ---
    if phan.lower() == "xoa":
        if not hien_tai:
            await update.message.reply_text("Nguồn này chưa đặt cột khoá.")
            return
        src["key_column"] = ""
        cfg.set("watch.sources", sources)
        _bo_anh_chup(state, sid)
        await update.message.reply_text(
            "Đã bỏ cột khoá của “%s”. Bot quay lại tự suy khoá định danh.\n"
            "Sẽ chụp lại ảnh ở lần quét tới (không báo tin giả)."
            % (src.get("name") or sid))
        return

    # --- Đặt cột khoá ---
    headers = await _doc_headers(update, src)
    if headers is None:
        return
    cot_goc = ct.match_column(headers, phan)
    if not cot_goc:
        await update.message.reply_text(
            "Sheet không có cột “%s”.\nCác cột thật: %s" % (phan, ", ".join(headers)))
        return

    src["key_column"] = cot_goc
    cfg.set("watch.sources", sources)
    _bo_anh_chup(state, sid)
    await update.message.reply_text(
        "Đã đặt cột khoá của “%s” = “%s”.\n"
        "Từ giờ mỗi dòng được nhận diện theo cột này.\n"
        "Sẽ chụp lại ảnh ở lần quét tới (không báo tin giả)."
        % (src.get("name") or sid, cot_goc))
```

- [ ] **Step 2: Nối nhánh và mở rộng cú pháp**

Trong `cmd_nguon`, thêm ngay **sau** nhánh `cot`:

```python
    if lenh == "khoa" and len(args) >= 2:
        await _nguon_khoa(update, sources, state, args)
        return
```

Và thêm một dòng nữa vào `NGUON_CU_PHAP`, ngay sau dòng `cot`:

```python
    "/nguon khoa <id> [<Tên cột> | xoa]\n"
```

- [ ] **Step 3: Sửa gợi ý cuối của `_nguon_them`**

Trong `_nguon_them`, thay đoạn:

```python
        parts.append(
            "Đang chạy chế độ bảng chung — bot báo theo tên cột nguyên văn. "
            "Muốn báo giàu nghĩa hơn thì khai ánh xạ cột trong config.yaml "
            "(watch.sources -> columns).")
```

bằng:

```python
        parts.append(
            "Đang chạy chế độ bảng chung — bot báo theo tên cột nguyên văn, và "
            "đổi hạn / đổi người sẽ KHÔNG được báo ngay mà chỉ vào bản tin gom.")
        parts.append("Muốn báo giàu nghĩa hơn: /nguon cot %s" % sid)
```

- [ ] **Step 4: Cập nhật `HELP_TEXT`**

Trong `HELP_TEXT`, thay hai dòng:

```
/nguon tab <id> [tên tab] - Xem hoặc đổi tab đang theo dõi
/nguon xoa <id> - Bỏ theo dõi một file
```

bằng:

```
/nguon tab <id> [tên tab] - Xem hoặc đổi tab đang theo dõi
/nguon cot <id> - Xem ánh xạ cột; khai: /nguon cot <id> <Tên cột> = <ý nghĩa>
/nguon khoa <id> <Tên cột> - Đặt cột làm khoá nhận diện dòng
/nguon xoa <id> - Bỏ theo dõi một file
```

- [ ] **Step 5: Cập nhật `AGENTS.md`**

Trong mục "## 14. Theo dõi thay đổi trên sheet kế hoạch (`watch.*`)", ở gạch đầu dòng mô tả `bot.py`, thay:

```markdown
- `bot.py` — `job_watch_scan` (run_repeating), `job_watch_digest` (run_daily),
  `/moi`, `/nguon`, `/theodoi`.
```

bằng:

```markdown
- `bot.py` — `job_watch_scan` (run_repeating), `job_watch_digest` (run_daily),
  `/moi`, `/theodoi`, và `/nguon` (tách thành `_nguon_liet_ke/_them/_tab/_cot/_khoa/_xoa`,
  `cmd_nguon` chỉ định tuyến).
```

Và thêm vào cuối danh sách "Điểm dễ vấp":

```markdown
- **Đổi `columns` / `key_column` / tab của một nguồn đều phải gọi `_bo_anh_chup`.**
  Ba thứ này đổi cách sinh khoá định danh dòng; giữ ảnh chụp cũ là lần quét sau dội một
  loạt thêm/xoá giả. Lệnh `/nguon cot` và `/nguon khoa` làm việc đó tự động — đó là lý do
  chúng tồn tại thay vì để người dùng sửa `config.yaml`.
```

- [ ] **Step 6: Cập nhật `README.md`**

Trong mục hướng dẫn theo dõi thay đổi, thêm vào danh sách lệnh liên quan (sau dòng `/nguon tab`):

```markdown
- `/nguon cot <id>` — xem ánh xạ cột; khai bằng `/nguon cot <id> <Tên cột> = <ý nghĩa>`
  (ý nghĩa: `name`, `assignee`, `due`, `status`, `project`...). Khai đủ thì bot chuyển từ
  chế độ bảng chung sang chế độ task: đổi hạn và đổi người phụ trách được **báo ngay**
  thay vì chờ tới bản tin.
- `/nguon khoa <id> <Tên cột>` — chọn cột làm khoá nhận diện dòng (VD cột "Mã")
```

- [ ] **Step 7: Xác minh và commit**

```bash
python -m py_compile src/*.py && python -m unittest discover -s tests -t . && git status --short
```

Kỳ vọng: py_compile im lặng; 78 test `OK`; `git status` chỉ thấy `src/bot.py`, `AGENTS.md`, `README.md` — **không** có `config.yaml`, `credentials.json`, `state/`.

```bash
git add src/bot.py AGENTS.md README.md
git commit -m "feat(watch): lệnh /nguon khoa và cập nhật hướng dẫn"
```

---

## Xác minh thủ công trên bot thật (sau khi merge)

Cần credentials + mạng nên không tự động hoá được:

1. `/nguon cot <id>` trên một nguồn chế độ generic → thấy ánh xạ rỗng, danh sách cột thật, và dòng "Còn thiếu để lên chế độ task".
2. `/nguon cot <id> <cột người> = assignee` → trả lời có `Chế độ: generic → generic` và phần còn thiếu giảm đi.
3. Khai tiếp cho đủ → trả lời `Chế độ: generic → task`, dòng "Còn thiếu" biến mất.
4. Chờ qua một lần quét → **không** có tin thay đổi giả nào.
5. Sửa một ô hạn trên sheet đó → giờ phải nhận **tin báo ngay** (trước đây chỉ vào bản tin).
6. `/nguon cot <id> xoa <cột người>` → chế độ tụt lại, vẫn không có tin giả.
7. `/nguon cot <id> Cột không tồn tại = assignee` → bị từ chối, và `/nguon cot <id>` cho thấy config **không** bị đổi.
8. `/nguon khoa <id> <cột mã>` → nhận xác nhận; lần quét sau không có tin giả.
9. `/nguon`, `/nguon them`, `/nguon tab`, `/nguon xoa` vẫn hoạt động y như trước.
