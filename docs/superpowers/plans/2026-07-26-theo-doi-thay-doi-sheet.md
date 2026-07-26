# Kế hoạch triển khai — Theo dõi & báo thay đổi trên Google Sheet kế hoạch

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bot tự quét các file Google Sheet kế hoạch do người khác cập nhật, phát hiện dòng mới / dòng bị xoá / ô bị sửa, rồi báo ngay hoặc gom thành bản tin trên Telegram.

**Architecture:** Ba module logic thuần stdlib (`change_tracker`, `change_reporter`, `state_store`) lo phát hiện — trình bày — lưu trạng thái; `sheets_client` chỉ được **thêm** hàm đọc bất kỳ file nào; `bot.py` nối vào job queue. Trạng thái (ảnh chụp sheet + hàng chờ thông báo) nằm ở `state/watch_state.json`. Luồng báo cáo cũ không bị đụng tới.

**Tech Stack:** Python 3.12 · `python-telegram-bot[job-queue]==21.10` · `gspread==6.1.4` · `PyYAML` · `pytz` · test bằng `unittest` (stdlib, **không thêm dependency**).

Spec: [`docs/superpowers/specs/2026-07-26-theo-doi-thay-doi-sheet-design.md`](../specs/2026-07-26-theo-doi-thay-doi-sheet-design.md)

## Global Constraints

- **Ngôn ngữ:** mọi comment, docstring, chuỗi hiển thị cho người dùng và commit message viết **tiếng Việt**. Thuật ngữ kỹ thuật giữ tiếng Anh. Giữ văn phong và độ dày comment như code hiện có.
- **Không thêm dependency mới.** `requirements.txt` giữ nguyên. Test dùng `unittest` của stdlib.
- **`change_tracker.py`, `change_reporter.py`, `state_store.py` TUYỆT ĐỐI không import `gspread`, `telegram`, `pytz`, hay `src.sheets_client`.** Máy dev không cài các thư viện đó; đây là điều kiện để test chạy được. Chúng chỉ được import `src.config` khi thật cần (thực tế: không cần).
- **Ngày trong tuần theo quy ước PTB: `0 = Chủ Nhật … 6 = Thứ Bảy`.** T2–T6 là `[1,2,3,4,5]`. Áp dụng cho cả `watch.active_days`. Đây là bẫy đã làm mất báo cáo Thứ Sáu (MEMORY.md mục 1) — phải có comment tại chỗ ở mọi nơi dùng.
- **Mọi tin nhắn của chức năng này gửi bằng HTML:** phải truyền `parse_mode=ParseMode.HTML` cho `send_long`, và mọi nội dung động phải escape qua `_esc` trong `change_reporter`. Quên `parse_mode` là thẻ `<b>` hiện thô (AGENTS.md bẫy số 2).
- **Không đụng vào** `src/report_generator.py`, `SheetsClient.fetch_tasks`, `SheetsClient.fetch_team_members`, `HEADER_MAP`, hay 4 job cũ trong `JOBS`.
- **Không commit** `config.yaml`, `credentials.json`, thư mục `state/`. Không dán nội dung của chúng vào commit message hay tài liệu.
- **Xác minh cú pháp sau mỗi task:** `python -m py_compile src/*.py`.
- Nhánh làm việc: `feature/theo-doi-thay-doi-sheet` (đã tồn tại, spec đã commit ở `7665f58`).

## Cấu trúc file

| File | Trách nhiệm |
|---|---|
| `src/state_store.py` (mới) | Đọc/ghi JSON trạng thái, ghi atomic, cắt bớt hàng chờ |
| `src/change_tracker.py` (mới) | Nhận diện cột & chế độ, sinh khoá định danh, chụp ảnh, so sánh, dò đổi tên, phân loại, lọc, kiểm tra khung giờ |
| `src/change_reporter.py` (mới) | Dựng chuỗi HTML cho tin báo ngay / bản tin / tin tóm tắt |
| `src/sheets_client.py` (sửa) | **Thêm** `fetch_rows`, `list_worksheets`, `service_account_email` |
| `src/bot.py` (sửa) | Job quét, job bản tin, lệnh `/moi` `/nguon` `/theodoi`, mở rộng `register_jobs` + `/cauhinh` + `HELP_TEXT` |
| `tests/` (mới) | `test_state_store.py`, `test_change_tracker.py`, `test_change_reporter.py` |
| `config.example.yaml`, `docker-compose.yml`, `.gitignore` (sửa) | Khối `watch`, mount `./state`, bỏ qua `state/` |
| `AGENTS.md`, `MEMORY.md`, `README.md` (sửa) | Tài liệu |

Lệnh chạy toàn bộ test (từ thư mục gốc repo):

```bash
python -m unittest discover -s tests -t . -v
```

---

### Task 1: Lưu trạng thái (`state_store`)

**Files:**
- Create: `src/state_store.py`
- Create: `tests/__init__.py` (file rỗng, để `python -m unittest tests.test_x` chạy được)
- Test: `tests/test_state_store.py`

**Interfaces:**
- Consumes: không có (task đầu tiên).
- Produces: `state_store.STATE_VERSION: int` · `state_store.MAX_PENDING: int` · `state_store.default_state() -> dict` · `state_store.load(path: str) -> dict` · `state_store.save(path: str, state: dict) -> None` · `state_store.prune_pending(state: dict) -> None`. Hình dạng state: `{"version": int, "sources": {sid: {...}}, "pending": [dict], "last_scan_at": str|None, "last_digest_at": str|None}`.

- [ ] **Step 1: Tạo `tests/__init__.py` rỗng**

```bash
python -c "open('tests/__init__.py','w').close()" 2>/dev/null || (mkdir tests && python -c "open('tests/__init__.py','w').close()")
```

- [ ] **Step 2: Viết test thất bại**

Tạo `tests/test_state_store.py`:

```python
# -*- coding: utf-8 -*-
"""Test cho src/state_store.py — chạy được không cần gspread/telegram."""
import json
import os
import tempfile
import unittest

from src import state_store


class TestStateStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "watch_state.json")

    def test_file_chua_ton_tai_tra_ve_trang_thai_rong(self):
        state = state_store.load(self.path)
        self.assertEqual(state["version"], state_store.STATE_VERSION)
        self.assertEqual(state["sources"], {})
        self.assertEqual(state["pending"], [])
        self.assertIsNone(state["last_scan_at"])
        self.assertIsNone(state["last_digest_at"])

    def test_file_hong_khong_lam_sap_bot(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ đây không phải json")
        state = state_store.load(self.path)
        self.assertEqual(state["sources"], {})

    def test_sai_version_thi_chup_lai_tu_dau(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": 999, "sources": {"a": {"snapshot": {}}}}, f)
        state = state_store.load(self.path)
        self.assertEqual(state["sources"], {})

    def test_ghi_roi_doc_lai_giu_nguyen_tieng_viet(self):
        state = state_store.default_state()
        state["sources"]["vnedu"] = {"headers": ["Hạng mục"], "snapshot": {}}
        state_store.save(self.path, state)
        again = state_store.load(self.path)
        self.assertEqual(again["sources"]["vnedu"]["headers"], ["Hạng mục"])

    def test_ghi_atomic_khong_de_lai_file_tam(self):
        state_store.save(self.path, state_store.default_state())
        thua = [f for f in os.listdir(self.dir) if f.endswith(".tmp")]
        self.assertEqual(thua, [])

    def test_cat_bot_hang_cho_qua_dai(self):
        state = state_store.default_state()
        state["pending"] = [{"i": i} for i in range(state_store.MAX_PENDING + 50)]
        state_store.save(self.path, state)
        again = state_store.load(self.path)
        self.assertEqual(len(again["pending"]), state_store.MAX_PENDING)
        # giữ lại các mục MỚI nhất
        self.assertEqual(again["pending"][-1]["i"], state_store.MAX_PENDING + 49)

    def test_tu_tao_thu_muc_neu_chua_co(self):
        nested = os.path.join(self.dir, "state", "watch_state.json")
        state_store.save(nested, state_store.default_state())
        self.assertTrue(os.path.exists(nested))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Chạy test để chắc chắn nó fail**

```bash
python -m unittest tests.test_state_store -v
```

Kỳ vọng: FAIL — `ModuleNotFoundError: No module named 'src.state_store'`.

- [ ] **Step 4: Viết `src/state_store.py`**

```python
# -*- coding: utf-8 -*-
"""Lưu/đọc trạng thái theo dõi thay đổi: ảnh chụp sheet + hàng chờ thông báo.

Thuần stdlib — KHÔNG import gspread/telegram/pytz để test chạy được trên máy dev
(xem AGENTS.md mục 11).
"""
import json
import logging
import os
import tempfile
from typing import Any, Dict

log = logging.getLogger("report-bot.state")

STATE_VERSION = 1
MAX_PENDING = 500  # trần hàng chờ, phòng khi tắt bản tin nhiều ngày


def default_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "sources": {},        # {source_id: {mode, headers, field_map, snapshot, ...}}
        "pending": [],        # [Change.to_dict()] chờ vào bản tin
        "last_scan_at": None,
        "last_digest_at": None,
    }


def load(path: str) -> Dict[str, Any]:
    """Đọc trạng thái. File thiếu / hỏng / sai version -> trạng thái rỗng.

    Không bao giờ ném lỗi ra ngoài: một file trạng thái hỏng không được phép
    làm bot không khởi động được (spec mục 10).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return default_state()
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        log.warning("File trạng thái hỏng (%s), chụp lại từ đầu: %s", path, e)
        return default_state()

    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        log.warning("File trạng thái sai version, chụp lại từ đầu")
        return default_state()

    base = default_state()
    base.update(data)
    return base


def prune_pending(state: Dict[str, Any]) -> None:
    """Cắt hàng chờ còn MAX_PENDING mục mới nhất."""
    pending = state.get("pending") or []
    if len(pending) > MAX_PENDING:
        state["pending"] = pending[-MAX_PENDING:]


def save(path: str, state: Dict[str, Any]) -> None:
    """Ghi atomic: ghi file tạm cùng thư mục rồi os.replace.

    Bot bị kill giữa chừng sẽ không để lại JSON hỏng.
    """
    state["version"] = STATE_VERSION
    prune_pending(state)
    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".watch_state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
```

- [ ] **Step 5: Chạy test, phải xanh**

```bash
python -m unittest tests.test_state_store -v
```

Kỳ vọng: `OK` — 7 test pass.

- [ ] **Step 6: Commit**

```bash
git add src/state_store.py tests/__init__.py tests/test_state_store.py
git commit -m "feat(watch): lưu trạng thái theo dõi thay đổi (ghi atomic, chịu file hỏng)"
```

---

### Task 2: Nhận diện cột, khoá định danh, chụp ảnh (`change_tracker` phần 1)

**Files:**
- Create: `src/change_tracker.py`
- Test: `tests/test_change_tracker.py`

**Interfaces:**
- Consumes: không có.
- Produces:
  - `FIELD_ALIASES: dict[str, list[str]]`
  - `detect_mode(headers: list[str], columns_override: dict|None = None) -> tuple[str, dict]` — trả `("task"|"generic", field_map)`, `field_map` là `{tên cột gốc: tên trường chuẩn}`
  - `column_for(field_map: dict, field_name: str) -> str|None`
  - `row_label(cells: dict, headers: list[str], field_map: dict) -> str`
  - `make_key(cells, headers, field_map, mode, key_column="", row=0) -> str`
  - `build_snapshot(rows: list[dict], headers, field_map, mode, key_column="") -> dict` — `rows` dạng `[{"row": int, "cells": {header: value}}]`, trả `{key: {"row": int, "cells": {...}}}`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_change_tracker.py`:

```python
# -*- coding: utf-8 -*-
"""Test cho src/change_tracker.py — chạy được không cần gspread/telegram."""
import unittest

from src import change_tracker as ct

# Sheet kiểu "task": nhận diện được tên việc + người + hạn + trạng thái
TASK_HEADERS = ["STT", "Tên Task", "Dự án", "Nhân Sự Thực Hiện", "Hạn",
                "Trạng thái thực hiện"]
# Sheet kiểu tự do: không cột nào khớp từ điển
GENERIC_HEADERS = ["Mã", "Nội dung triển khai", "Bên liên quan", "Ghi nhận"]


def row(n, **cells):
    return {"row": n, "cells": cells}


class TestNhanDienCot(unittest.TestCase):
    def test_sheet_task_duoc_nhan_dien(self):
        mode, field_map = ct.detect_mode(TASK_HEADERS)
        self.assertEqual(mode, "task")
        self.assertEqual(field_map["Tên Task"], "name")
        self.assertEqual(field_map["Hạn"], "due")
        self.assertEqual(ct.column_for(field_map, "assignee"), "Nhân Sự Thực Hiện")

    def test_sheet_la_hoan_toan_thi_ve_che_do_generic(self):
        mode, field_map = ct.detect_mode(GENERIC_HEADERS)
        self.assertEqual(mode, "generic")
        self.assertEqual(field_map, {})

    def test_khai_columns_nang_generic_len_task(self):
        override = {"Nội dung triển khai": "name", "Bên liên quan": "assignee",
                    "Ghi nhận": "status"}
        mode, field_map = ct.detect_mode(GENERIC_HEADERS, override)
        self.assertEqual(mode, "task")
        self.assertEqual(ct.column_for(field_map, "name"), "Nội dung triển khai")

    def test_chi_co_ten_viec_thi_van_la_generic(self):
        # cần name + ít nhất 2 trong {assignee, due, status} mới đủ tin cậy
        mode, _ = ct.detect_mode(["Tên Task", "Mã", "Ghi nhận khác"])
        self.assertEqual(mode, "generic")


class TestNhanDong(unittest.TestCase):
    def test_che_do_task_lay_ten_task_lam_nhan(self):
        _, fm = ct.detect_mode(TASK_HEADERS)
        cells = {"STT": "1", "Tên Task": "Đồng bộ điểm", "Dự án": "vnEdu",
                 "Nhân Sự Thực Hiện": "Nam", "Hạn": "26/07",
                 "Trạng thái thực hiện": "Đang thực hiện"}
        self.assertEqual(ct.row_label(cells, TASK_HEADERS, fm), "Đồng bộ điểm")

    def test_che_do_generic_lay_o_dau_tien_co_noi_dung(self):
        _, fm = ct.detect_mode(GENERIC_HEADERS)
        cells = {"Mã": "", "Nội dung triển khai": "Nâng cấp máy chủ",
                 "Bên liên quan": "Nam", "Ghi nhận": ""}
        self.assertEqual(ct.row_label(cells, GENERIC_HEADERS, fm), "Nâng cấp máy chủ")


class TestKhoaDinhDanh(unittest.TestCase):
    def setUp(self):
        self.mode, self.fm = ct.detect_mode(TASK_HEADERS)

    def _key(self, cells, **kw):
        return ct.make_key(cells, TASK_HEADERS, self.fm, self.mode, **kw)

    def test_key_column_khai_tay_duoc_uu_tien(self):
        cells = {"STT": "7", "Tên Task": "A", "Dự án": "", "Nhân Sự Thực Hiện": "",
                 "Hạn": "", "Trạng thái thực hiện": ""}
        self.assertEqual(self._key(cells, key_column="STT"), "k:7")

    def test_doi_ten_viec_nhung_giu_stt_thi_khoa_khong_doi(self):
        a = {"STT": "3", "Tên Task": "Rà soát dữ liệu", "Dự án": "vnEdu",
             "Nhân Sự Thực Hiện": "Nam", "Hạn": "", "Trạng thái thực hiện": ""}
        b = dict(a, **{"Tên Task": "Rà soát & làm sạch dữ liệu"})
        self.assertEqual(self._key(a), self._key(b))

    def test_khong_co_stt_thi_dung_van_tay_ten_du_an(self):
        a = {"STT": "", "Tên Task": "Đồng bộ điểm", "Dự án": "vnEdu",
             "Nhân Sự Thực Hiện": "Nam", "Hạn": "26/07",
             "Trạng thái thực hiện": "Đang thực hiện"}
        b = dict(a, **{"Nhân Sự Thực Hiện": "Lan", "Hạn": "30/07"})
        # đổi người và hạn không được làm đổi khoá
        self.assertEqual(self._key(a), self._key(b))
        self.assertTrue(self._key(a).startswith("fp:"))


class TestChupAnh(unittest.TestCase):
    def setUp(self):
        self.mode, self.fm = ct.detect_mode(TASK_HEADERS)

    def _snap(self, rows):
        return ct.build_snapshot(rows, TASK_HEADERS, self.fm, self.mode)

    def test_bo_qua_dong_trong_hoan_toan(self):
        rows = [row(2, **{h: "" for h in TASK_HEADERS}),
                row(3, **{"STT": "1", "Tên Task": "A", "Dự án": "", "Nhân Sự Thực Hiện": "",
                          "Hạn": "", "Trạng thái thực hiện": ""})]
        self.assertEqual(len(self._snap(rows)), 1)

    def test_khoa_trung_duoc_gan_hau_to(self):
        base = {"STT": "", "Dự án": "", "Nhân Sự Thực Hiện": "", "Hạn": "",
                "Trạng thái thực hiện": ""}
        rows = [row(2, **dict(base, **{"Tên Task": "Họp tuần"})),
                row(3, **dict(base, **{"Tên Task": "Họp tuần"}))]
        keys = list(self._snap(rows))
        self.assertEqual(len(keys), 2)
        self.assertTrue(any(k.endswith("#2") for k in keys))

    def test_gia_tri_duoc_strip_khoang_trang(self):
        rows = [row(2, **{"STT": " 1 ", "Tên Task": " A ", "Dự án": "", "Nhân Sự Thực Hiện": "",
                          "Hạn": "", "Trạng thái thực hiện": ""})]
        entry = list(self._snap(rows).values())[0]
        self.assertEqual(entry["cells"]["Tên Task"], "A")
        self.assertEqual(entry["row"], 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

```bash
python -m unittest tests.test_change_tracker -v
```

Kỳ vọng: FAIL — `ModuleNotFoundError: No module named 'src.change_tracker'`.

- [ ] **Step 3: Viết `src/change_tracker.py` (phần 1)**

```python
# -*- coding: utf-8 -*-
"""Phát hiện thay đổi giữa hai lần chụp ảnh (snapshot) của một worksheet.

Thuần stdlib — KHÔNG import gspread/telegram/pytz, và KHÔNG import sheets_client
(file đó import gspread ở cấp module). Vì vậy module này nhận vào dict thuần chứ
không nhận Task. Đây là điều kiện để test chạy được trên máy dev (AGENTS.md mục 11).
"""
import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

# ------------------------------------------------------------------
# Nhận diện cột & chế độ đọc
# ------------------------------------------------------------------
# Mỗi file kế hoạch một kiểu, nên bot đoán ý nghĩa cột qua từ điển này.
# Không khớp -> chạy chế độ 'generic' (báo theo tên cột nguyên văn của sheet).
FIELD_ALIASES = {
    "name": ["tên task", "tên công việc", "công việc", "nội dung công việc",
             "nội dung", "hạng mục", "đầu việc", "tên"],
    "assignee": ["nhân sự thực hiện", "người thực hiện", "người phụ trách",
                 "phụ trách", "nhân sự"],
    "due": ["hạn", "hạn hoàn thành", "thời hạn", "deadline", "ngày kết thúc"],
    "status": ["trạng thái thực hiện", "trạng thái", "tình trạng", "tiến độ"],
    "project": ["dự án", "mảng", "nhóm dự án"],
    "jira": ["link task jira (info liên quan)", "link task jira", "jira", "mã task"],
    "stt": ["stt", "số thứ tự"],
    "created": ["ngày tạo", "ngày giao", "ngày bắt đầu"],
    "est": ["est (giờ)", "est", "ước lượng", "ước lượng (giờ)"],
    "done_date": ["ngày hoàn thành"],
    "note": ["ghi chú", "note"],
}


def _norm(text: str) -> str:
    """Chuẩn hoá tên cột để so khớp: thường hoá, gộp khoảng trắng."""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def detect_mode(headers: List[str],
                columns_override: Optional[Dict[str, str]] = None
                ) -> Tuple[str, Dict[str, str]]:
    """Đoán chế độ đọc của một sheet.

    Trả về (mode, field_map) với field_map = {tên cột gốc: tên trường chuẩn}.
    'task' khi nhận ra cột tên việc VÀ ít nhất 2 trong {assignee, due, status};
    ngược lại 'generic'.
    """
    field_map: Dict[str, str] = {}
    taken = set()
    for header in headers:
        key = _norm(header)
        for name, aliases in FIELD_ALIASES.items():
            if name in taken:
                continue
            if key in aliases:
                field_map[header] = name
                taken.add(name)
                break

    # Khai tay trong config đè lên kết quả đoán.
    for col, name in (columns_override or {}).items():
        for header in headers:
            if _norm(header) == _norm(col):
                field_map[header] = name

    found = set(field_map.values())
    core = found & {"assignee", "due", "status"}
    mode = "task" if ("name" in found and len(core) >= 2) else "generic"
    return mode, field_map


def column_for(field_map: Dict[str, str], field_name: str) -> Optional[str]:
    """Tên cột gốc ứng với một trường chuẩn (None nếu sheet không có)."""
    for col, name in (field_map or {}).items():
        if name == field_name:
            return col
    return None


def _value(cells: Dict[str, str], field_map: Dict[str, str], field_name: str) -> str:
    col = column_for(field_map, field_name)
    return (cells.get(col) or "").strip() if col else ""


def row_label(cells: Dict[str, str], headers: List[str],
              field_map: Dict[str, str]) -> str:
    """Nhãn hiển thị của một dòng: tên việc, hoặc ô đầu tiên có nội dung."""
    name = _value(cells, field_map, "name")
    if name:
        return name
    for header in headers:
        value = (cells.get(header) or "").strip()
        if value:
            return value
    return ""


# ------------------------------------------------------------------
# Khoá định danh & chụp ảnh
# ------------------------------------------------------------------
def make_key(cells: Dict[str, str], headers: List[str], field_map: Dict[str, str],
             mode: str, key_column: str = "", row: int = 0) -> str:
    """Khoá nhận diện một dòng qua các lần quét.

    Thứ tự ưu tiên: cột khoá khai tay -> (chế độ task) Jira -> STT -> vân tay
    tên+dự án+ngày tạo -> (chế độ generic) vân tay nhãn dòng -> số dòng.

    Khoá KHÔNG phụ thuộc vị trí dòng, nên sort lại sheet hay chèn dòng ở giữa
    đều không sinh thông báo (spec mục 5).
    """
    if key_column:
        for header in headers:
            if _norm(header) == _norm(key_column):
                value = (cells.get(header) or "").strip()
                if value:
                    return "k:" + value.lower()

    if mode == "task":
        jira = _value(cells, field_map, "jira")
        if jira:
            return "jira:" + re.sub(r"\s+", "", jira.lower())
        stt = _value(cells, field_map, "stt")
        if stt:
            return "stt:%s:%s" % (_value(cells, field_map, "project").lower(), stt.lower())
        finger = "|".join([_value(cells, field_map, "name"),
                           _value(cells, field_map, "project"),
                           _value(cells, field_map, "created")])
        return "fp:" + _sha(finger.lower())

    label = row_label(cells, headers, field_map)
    if label:
        return "lb:" + _sha(label.lower())
    return "row:%d" % row


def build_snapshot(rows: List[Dict[str, Any]], headers: List[str],
                   field_map: Dict[str, str], mode: str,
                   key_column: str = "") -> Dict[str, Dict[str, Any]]:
    """Chụp ảnh một worksheet.

    rows: [{"row": <số dòng trên sheet>, "cells": {tên cột: giá trị}}]
    Trả về {khoá: {"row": int, "cells": {...}}}. Dòng trống hoàn toàn bị bỏ qua;
    khoá trùng trong cùng lần quét được gắn hậu tố #2, #3.
    """
    snapshot: Dict[str, Dict[str, Any]] = {}
    seen: Dict[str, int] = {}
    for item in rows:
        raw = item.get("cells") or {}
        cells = {h: (raw.get(h) or "").strip() for h in headers}
        if not any(cells.values()):
            continue
        key = make_key(cells, headers, field_map, mode, key_column, item.get("row", 0))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = "%s#%d" % (key, seen[key])
        snapshot[key] = {"row": item.get("row", 0), "cells": cells}
    return snapshot
```

- [ ] **Step 4: Chạy test, phải xanh**

```bash
python -m unittest tests.test_change_tracker -v
```

Kỳ vọng: `OK` — 12 test pass.

- [ ] **Step 5: Kiểm tra cú pháp và commit**

```bash
python -m py_compile src/change_tracker.py
git add src/change_tracker.py tests/test_change_tracker.py
git commit -m "feat(watch): nhận diện cột, khoá định danh dòng và chụp ảnh worksheet"
```

---

### Task 3: So sánh hai ảnh chụp (`change_tracker` phần 2)

**Files:**
- Modify: `src/change_tracker.py` (thêm vào cuối)
- Test: `tests/test_change_tracker.py` (thêm class test)

**Interfaces:**
- Consumes: `build_snapshot`, `detect_mode`, `row_label` (Task 2).
- Produces:
  - `@dataclass Change` với các trường `source_id, kind, key, label, old_label, row, fields, cells, at, instant_sent` và hai method `to_dict() -> dict`, `Change.from_dict(d) -> Change`. `kind` ∈ `{"added","removed","modified","renamed","column"}`. `fields` là `list[list[str]]` dạng `[[tên cột, giá trị cũ, giá trị mới]]` (dùng list chứ không dùng tuple để JSON round-trip được).
  - `diff_snapshots(old_state: dict, new_state: dict, source_id: str) -> list[Change]` — `old_state`/`new_state` dạng `{"headers": [...], "field_map": {...}, "snapshot": {...}}`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_change_tracker.py`, ngay trước `if __name__ == "__main__":`

```python
class TestSoSanh(unittest.TestCase):
    def setUp(self):
        self.mode, self.fm = ct.detect_mode(TASK_HEADERS)

    def _state(self, rows, headers=None):
        headers = headers or TASK_HEADERS
        mode, fm = ct.detect_mode(headers)
        return {"headers": headers, "field_map": fm,
                "snapshot": ct.build_snapshot(rows, headers, fm, mode)}

    def _rows(self, *specs):
        out = []
        for i, spec in enumerate(specs, start=2):
            base = {h: "" for h in TASK_HEADERS}
            base.update(spec)
            out.append(row(i, **base))
        return out

    def test_them_dong_moi(self):
        cu = self._state(self._rows({"STT": "1", "Tên Task": "A"}))
        moi = self._state(self._rows({"STT": "1", "Tên Task": "A"},
                                     {"STT": "2", "Tên Task": "B"}))
        changes = ct.diff_snapshots(cu, moi, "vnedu")
        self.assertEqual([c.kind for c in changes], ["added"])
        self.assertEqual(changes[0].label, "B")
        self.assertEqual(changes[0].source_id, "vnedu")

    def test_xoa_dong(self):
        cu = self._state(self._rows({"STT": "1", "Tên Task": "A"},
                                    {"STT": "2", "Tên Task": "B"}))
        moi = self._state(self._rows({"STT": "1", "Tên Task": "A"}))
        changes = ct.diff_snapshots(cu, moi, "vnedu")
        self.assertEqual([c.kind for c in changes], ["removed"])
        self.assertEqual(changes[0].label, "B")

    def test_sua_o_bao_dung_cu_va_moi(self):
        cu = self._state(self._rows({"STT": "1", "Tên Task": "A", "Hạn": "26/07"}))
        moi = self._state(self._rows({"STT": "1", "Tên Task": "A", "Hạn": "30/07"}))
        changes = ct.diff_snapshots(cu, moi, "vnedu")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "modified")
        self.assertEqual(changes[0].fields, [["Hạn", "26/07", "30/07"]])

    def test_sort_lai_sheet_thi_khong_bao_gi(self):
        a = {"STT": "1", "Tên Task": "A"}
        b = {"STT": "2", "Tên Task": "B"}
        cu = self._state(self._rows(a, b))
        moi = self._state(self._rows(b, a))     # đảo thứ tự
        self.assertEqual(ct.diff_snapshots(cu, moi, "vnedu"), [])

    def test_chen_dong_giua_chung_chi_bao_dong_moi(self):
        a = {"STT": "1", "Tên Task": "A"}
        b = {"STT": "2", "Tên Task": "B"}
        c = {"STT": "3", "Tên Task": "C"}
        cu = self._state(self._rows(a, c))
        moi = self._state(self._rows(a, b, c))
        changes = ct.diff_snapshots(cu, moi, "vnedu")
        self.assertEqual([(x.kind, x.label) for x in changes], [("added", "B")])

    def test_khac_biet_chi_o_khoang_trang_thi_bo_qua(self):
        cu = self._state(self._rows({"STT": "1", "Tên Task": "A", "Hạn": "26/07"}))
        moi = self._state(self._rows({"STT": "1", "Tên Task": "A", "Hạn": " 26/07 "}))
        self.assertEqual(ct.diff_snapshots(cu, moi, "vnedu"), [])

    def test_them_cot_moi_duoc_bao(self):
        cu = self._state(self._rows({"STT": "1", "Tên Task": "A"}))
        headers_moi = TASK_HEADERS + ["Rủi ro"]
        rows_moi = [row(2, **dict({h: "" for h in headers_moi},
                                  **{"STT": "1", "Tên Task": "A"}))]
        moi = self._state(rows_moi, headers_moi)
        changes = ct.diff_snapshots(cu, moi, "vnedu")
        cot = [c for c in changes if c.kind == "column"]
        self.assertEqual(len(cot), 1)
        self.assertEqual(cot[0].label, "Rủi ro")

    def test_bot_cot_duoc_bao(self):
        headers_cu = TASK_HEADERS + ["Rủi ro"]
        rows_cu = [row(2, **dict({h: "" for h in headers_cu},
                                 **{"STT": "1", "Tên Task": "A"}))]
        cu = self._state(rows_cu, headers_cu)
        moi = self._state(self._rows({"STT": "1", "Tên Task": "A"}))
        cot = [c for c in ct.diff_snapshots(cu, moi, "vnedu") if c.kind == "column"]
        self.assertEqual(len(cot), 1)
        self.assertEqual(cot[0].fields, [["Rủi ro", "(đã xoá)", ""]])

    def test_chua_co_anh_chup_cu_thi_moi_dong_deu_la_added(self):
        # Bootstrap: so với ảnh chụp rỗng thì mọi dòng đều thành "added". Vì vậy
        # nơi gọi (bot._scan_source) BẮT BUỘC phải bỏ qua lần quét đầu tiên —
        # nếu không sẽ dội hàng trăm tin "dòng mới" (spec mục 10).
        moi = self._state(self._rows({"STT": "1", "Tên Task": "A"},
                                     {"STT": "2", "Tên Task": "B"}))
        rong = {"headers": [], "field_map": {}, "snapshot": {}}
        changes = ct.diff_snapshots(rong, moi, "vnedu")
        self.assertEqual([c.kind for c in changes if c.kind != "column"],
                         ["added", "added"])

    def test_change_json_round_trip(self):
        ch = ct.Change(source_id="vnedu", kind="modified", key="k:1", label="A",
                       fields=[["Hạn", "26/07", "30/07"]], cells={"Hạn": "30/07"})
        lai = ct.Change.from_dict(ch.to_dict())
        self.assertEqual(lai.fields, [["Hạn", "26/07", "30/07"]])
        self.assertEqual(lai.kind, "modified")
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

```bash
python -m unittest tests.test_change_tracker.TestSoSanh -v
```

Kỳ vọng: FAIL — `AttributeError: module 'src.change_tracker' has no attribute 'Change'`.

- [ ] **Step 3: Thêm code vào cuối `src/change_tracker.py`**

```python
# ------------------------------------------------------------------
# Một thay đổi & phép so sánh hai ảnh chụp
# ------------------------------------------------------------------
@dataclass
class Change:
    """Một thay đổi phát hiện được giữa hai lần quét.

    fields dùng list-lồng-list (không dùng tuple) để JSON round-trip được khi
    nằm trong hàng chờ của state_store.
    """
    source_id: str = ""
    kind: str = ""            # added | removed | modified | renamed | column
    key: str = ""
    label: str = ""
    old_label: str = ""       # chỉ dùng cho kind="renamed"
    row: Optional[int] = None
    fields: List[List[str]] = field(default_factory=list)
    cells: Dict[str, str] = field(default_factory=dict)
    at: str = ""              # thời điểm phát hiện (ISO), do bot.py điền
    instant_sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Change":
        known = Change.__dataclass_fields__
        return Change(**{k: v for k, v in (data or {}).items() if k in known})


def diff_snapshots(old_state: Dict[str, Any], new_state: Dict[str, Any],
                   source_id: str) -> List[Change]:
    """So hai ảnh chụp của cùng một nguồn.

    old_state / new_state: {"headers": [...], "field_map": {...}, "snapshot": {...}}
    Dòng có khoá dạng "row:" (không có gì để bám) không báo thêm/xoá, tránh
    nhiễu khi ai đó chèn hay xoá dòng trắng.
    """
    changes: List[Change] = []
    old_headers = old_state.get("headers") or []
    new_headers = new_state.get("headers") or []
    field_map = new_state.get("field_map") or {}

    for col in new_headers:
        if col not in old_headers:
            changes.append(Change(source_id=source_id, kind="column",
                                  key="col:" + col, label=col,
                                  fields=[[col, "", "(cột mới)"]]))
    for col in old_headers:
        if col not in new_headers:
            changes.append(Change(source_id=source_id, kind="column",
                                  key="col:" + col, label=col,
                                  fields=[[col, "(đã xoá)", ""]]))

    shared = [h for h in new_headers if h in old_headers]
    old_snap = old_state.get("snapshot") or {}
    new_snap = new_state.get("snapshot") or {}

    for key, entry in new_snap.items():
        cells = entry.get("cells") or {}
        if key in old_snap:
            truoc = old_snap[key].get("cells") or {}
            diffs = [[col, truoc.get(col, ""), cells.get(col, "")]
                     for col in shared
                     if (truoc.get(col, "") or "").strip()
                     != (cells.get(col, "") or "").strip()]
            if diffs:
                changes.append(Change(source_id=source_id, kind="modified", key=key,
                                      label=row_label(cells, new_headers, field_map),
                                      row=entry.get("row"), fields=diffs, cells=cells))
        elif not key.startswith("row:"):
            changes.append(Change(source_id=source_id, kind="added", key=key,
                                  label=row_label(cells, new_headers, field_map),
                                  row=entry.get("row"), cells=cells))

    old_field_map = old_state.get("field_map") or {}
    for key, entry in old_snap.items():
        if key not in new_snap and not key.startswith("row:"):
            cells = entry.get("cells") or {}
            changes.append(Change(source_id=source_id, kind="removed", key=key,
                                  label=row_label(cells, old_headers, old_field_map),
                                  row=entry.get("row"), cells=cells))
    return changes
```

- [ ] **Step 4: Chạy test, phải xanh**

```bash
python -m unittest tests.test_change_tracker -v
```

Kỳ vọng: `OK` — 22 test pass.

- [ ] **Step 5: Commit**

```bash
python -m py_compile src/change_tracker.py
git add src/change_tracker.py tests/test_change_tracker.py
git commit -m "feat(watch): so sánh hai ảnh chụp, phát hiện thêm/xoá/sửa dòng và cột"
```

---

### Task 4: Dò đổi tên (`change_tracker` phần 3)

**Files:**
- Modify: `src/change_tracker.py` (thêm vào cuối)
- Test: `tests/test_change_tracker.py` (thêm class test)

**Interfaces:**
- Consumes: `Change`, `diff_snapshots` (Task 3).
- Produces: `RENAME_CELLS_RATIO = 0.7` · `RENAME_LABEL_RATIO = 0.6` · `match_renames(changes: list[Change]) -> list[Change]` — trả danh sách mới, các cặp removed+added được ghép thành một `Change(kind="renamed")` với `old_label` là tên cũ.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_change_tracker.py`:

```python
class TestDoDoiTen(unittest.TestCase):
    def _doi(self, kind, label, cells, old_label=""):
        return ct.Change(source_id="vnedu", kind=kind, key="k:" + label,
                         label=label, old_label=old_label, cells=cells)

    def test_ghep_cap_khi_cac_o_khac_giu_nguyen(self):
        cu = {"Tên Task": "Rà soát dữ liệu", "Nhân Sự Thực Hiện": "Nam", "Hạn": "26/07"}
        moi = {"Tên Task": "Rà soát & làm sạch dữ liệu", "Nhân Sự Thực Hiện": "Nam",
               "Hạn": "26/07"}
        changes = [self._doi("removed", "Rà soát dữ liệu", cu),
                   self._doi("added", "Rà soát & làm sạch dữ liệu", moi)]
        ket_qua = ct.match_renames(changes)
        self.assertEqual([c.kind for c in ket_qua], ["renamed"])
        self.assertEqual(ket_qua[0].old_label, "Rà soát dữ liệu")
        self.assertEqual(ket_qua[0].label, "Rà soát & làm sạch dữ liệu")

    def test_hai_viec_khac_han_thi_khong_ghep(self):
        changes = [
            self._doi("removed", "Nâng cấp máy chủ",
                      {"Tên Task": "Nâng cấp máy chủ", "Nhân Sự Thực Hiện": "Nam"}),
            self._doi("added", "Viết tài liệu bàn giao",
                      {"Tên Task": "Viết tài liệu bàn giao", "Nhân Sự Thực Hiện": "Lan"}),
        ]
        self.assertEqual(sorted(c.kind for c in ct.match_renames(changes)),
                         ["added", "removed"])

    def test_khong_ghep_cheo_hai_nguon_khac_nhau(self):
        cells = {"Tên Task": "A", "Nhân Sự Thực Hiện": "Nam"}
        a = self._doi("removed", "A", cells)
        b = self._doi("added", "A2", dict(cells, **{"Tên Task": "A2"}))
        b.source_id = "kiosk"
        self.assertEqual(sorted(c.kind for c in ct.match_renames([a, b])),
                         ["added", "removed"])

    def test_giu_nguyen_cac_thay_doi_khac(self):
        modified = ct.Change(source_id="vnedu", kind="modified", key="k:1", label="X",
                             fields=[["Hạn", "26/07", "30/07"]])
        ket_qua = ct.match_renames([modified])
        self.assertEqual(len(ket_qua), 1)
        self.assertEqual(ket_qua[0].kind, "modified")

    def test_doi_ten_kem_doi_han_van_giu_lai_diff_o(self):
        cu = {"Tên Task": "Rà soát dữ liệu", "Nhân Sự Thực Hiện": "Nam", "Hạn": "26/07"}
        moi = {"Tên Task": "Rà soát dữ liệu HK1", "Nhân Sự Thực Hiện": "Nam",
               "Hạn": "30/07"}
        ket_qua = ct.match_renames([self._doi("removed", "Rà soát dữ liệu", cu),
                                    self._doi("added", "Rà soát dữ liệu HK1", moi)])
        self.assertEqual(ket_qua[0].kind, "renamed")
        self.assertIn(["Hạn", "26/07", "30/07"], ket_qua[0].fields)
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

```bash
python -m unittest tests.test_change_tracker.TestDoDoiTen -v
```

Kỳ vọng: FAIL — `AttributeError: module 'src.change_tracker' has no attribute 'match_renames'`.

- [ ] **Step 3: Thêm code vào cuối `src/change_tracker.py`**

```python
# ------------------------------------------------------------------
# Dò đổi tên: ghép cặp một dòng "mất" với một dòng "thêm"
# ------------------------------------------------------------------
RENAME_CELLS_RATIO = 0.7   # tỉ lệ ô giống nhau tối thiểu
RENAME_LABEL_RATIO = 0.6   # độ giống của nhãn khi các ô khác trùng khớp


def _cells_ratio(a: Dict[str, str], b: Dict[str, str]) -> float:
    keys = set(a or {}) | set(b or {})
    if not keys:
        return 0.0
    giong = sum(1 for k in keys
                if (a.get(k, "") or "").strip() == (b.get(k, "") or "").strip())
    return giong / len(keys)


def _drop_label(cells: Dict[str, str], label: str) -> Dict[str, str]:
    """Bỏ ô đang giữ nhãn, để so phần còn lại của dòng."""
    return {k: v for k, v in (cells or {}).items() if (v or "").strip() != label}


def match_renames(changes: List[Change]) -> List[Change]:
    """Ghép removed + added thành renamed khi hai dòng thực ra là một.

    Nếu không ghép, việc sửa tên một dòng sẽ bị báo nhầm thành 'đã xoá' cộng
    'thêm mới' (spec mục 5).
    """
    removed = [c for c in changes if c.kind == "removed"]
    added = [c for c in changes if c.kind == "added"]
    if not removed or not added:
        return list(changes)

    ung_vien = []
    for cu in removed:
        for moi in added:
            if cu.source_id != moi.source_id:
                continue
            ty_le_o = _cells_ratio(cu.cells, moi.cells)
            ty_le_nhan = SequenceMatcher(None, (cu.label or "").lower(),
                                         (moi.label or "").lower()).ratio()
            khac_giong_het = _cells_ratio(_drop_label(cu.cells, cu.label),
                                          _drop_label(moi.cells, moi.label)) == 1.0
            if ty_le_o >= RENAME_CELLS_RATIO or (
                    ty_le_nhan >= RENAME_LABEL_RATIO and khac_giong_het):
                ung_vien.append((max(ty_le_o, ty_le_nhan), cu, moi))

    ung_vien.sort(key=lambda x: x[0], reverse=True)
    da_dung_cu, da_dung_moi, ghep = set(), set(), {}
    for _, cu, moi in ung_vien:
        if id(cu) in da_dung_cu or id(moi) in da_dung_moi:
            continue
        da_dung_cu.add(id(cu))
        da_dung_moi.add(id(moi))
        diffs = [[col, cu.cells.get(col, ""), moi.cells.get(col, "")]
                 for col in moi.cells
                 if (cu.cells.get(col, "") or "").strip()
                 != (moi.cells.get(col, "") or "").strip()]
        ghep[id(moi)] = Change(source_id=moi.source_id, kind="renamed", key=moi.key,
                               label=moi.label, old_label=cu.label, row=moi.row,
                               fields=diffs, cells=moi.cells)

    ket_qua = []
    for ch in changes:
        if ch.kind == "removed" and id(ch) in da_dung_cu:
            continue
        ket_qua.append(ghep.get(id(ch), ch))
    return ket_qua
```

- [ ] **Step 4: Chạy test, phải xanh**

```bash
python -m unittest tests.test_change_tracker -v
```

Kỳ vọng: `OK` — 27 test pass.

- [ ] **Step 5: Commit**

```bash
python -m py_compile src/change_tracker.py
git add src/change_tracker.py tests/test_change_tracker.py
git commit -m "feat(watch): dò đổi tên để không báo nhầm thành xoá + thêm mới"
```

---

### Task 5: Phân loại, bộ lọc, khung giờ (`change_tracker` phần 4)

**Files:**
- Modify: `src/change_tracker.py` (thêm vào cuối)
- Test: `tests/test_change_tracker.py` (thêm class test)

**Interfaces:**
- Consumes: `Change` (Task 3), `column_for` (Task 2).
- Produces:
  - `DEFAULT_INSTANT_KINDS = ["added", "removed"]` · `DEFAULT_INSTANT_FIELDS = ["due", "assignee"]`
  - `classify(change, instant_kinds=None, instant_fields=None, field_map=None) -> str` — trả `"instant"` hoặc `"digest"`
  - `passes_filters(change, filters: dict|None, field_map: dict|None = None) -> bool`
  - `in_active_window(now: datetime, active_days=None, active_hours="08:00-18:00") -> bool`
  - `is_first_scan_of_day(last_scan_at: str|None, now: datetime) -> bool`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_change_tracker.py` (và thêm `from datetime import datetime` vào đầu file):

```python
class TestPhanLoai(unittest.TestCase):
    def setUp(self):
        _, self.fm = ct.detect_mode(TASK_HEADERS)

    def test_dong_moi_bao_ngay(self):
        ch = ct.Change(kind="added", label="A")
        self.assertEqual(ct.classify(ch, field_map=self.fm), "instant")

    def test_doi_han_bao_ngay(self):
        ch = ct.Change(kind="modified", fields=[["Hạn", "26/07", "30/07"]])
        self.assertEqual(ct.classify(ch, field_map=self.fm), "instant")

    def test_doi_trang_thai_gom_vao_ban_tin(self):
        ch = ct.Change(kind="modified",
                       fields=[["Trạng thái thực hiện", "Đang thực hiện", "Hoàn thành"]])
        self.assertEqual(ct.classify(ch, field_map=self.fm), "digest")

    def test_cau_hinh_de_dua_trang_thai_len_bao_ngay(self):
        ch = ct.Change(kind="modified",
                       fields=[["Trạng thái thực hiện", "A", "B"]])
        self.assertEqual(
            ct.classify(ch, instant_fields=["status"], field_map=self.fm), "instant")


class TestBoLoc(unittest.TestCase):
    def setUp(self):
        _, self.fm = ct.detect_mode(TASK_HEADERS)
        self.ch = ct.Change(source_id="vnedu", kind="added", label="Đồng bộ điểm",
                            cells={"Tên Task": "Đồng bộ điểm", "Dự án": "vnEdu",
                                   "Nhân Sự Thực Hiện": "Nam"})

    def test_khong_khai_gi_thi_qua_het(self):
        self.assertTrue(ct.passes_filters(self.ch, {}, self.fm))
        self.assertTrue(ct.passes_filters(self.ch, None, self.fm))

    def test_loc_theo_nguon(self):
        self.assertTrue(ct.passes_filters(self.ch, {"sources": ["vnedu"]}, self.fm))
        self.assertFalse(ct.passes_filters(self.ch, {"sources": ["kiosk"]}, self.fm))

    def test_loc_theo_nhan_su(self):
        self.assertTrue(ct.passes_filters(self.ch, {"assignees": ["Nam"]}, self.fm))
        self.assertFalse(ct.passes_filters(self.ch, {"assignees": ["Lan"]}, self.fm))

    def test_loc_tu_khoa_dung_duoc_cho_che_do_generic(self):
        generic = ct.Change(source_id="kh", kind="added", label="Nâng cấp máy chủ",
                            cells={"Nội dung": "Nâng cấp máy chủ", "Ghi nhận": "50%"})
        self.assertTrue(ct.passes_filters(generic, {"keywords": ["máy chủ"]}, {}))
        self.assertFalse(ct.passes_filters(generic, {"keywords": ["hoá đơn"]}, {}))

    def test_thay_doi_cot_chi_chiu_loc_nguon(self):
        cot = ct.Change(source_id="vnedu", kind="column", label="Rủi ro")
        self.assertTrue(ct.passes_filters(cot, {"assignees": ["Lan"]}, self.fm))
        self.assertFalse(ct.passes_filters(cot, {"sources": ["kiosk"]}, self.fm))


class TestKhungGio(unittest.TestCase):
    def test_trong_gio_hanh_chinh_thu_hai(self):
        # 2026-07-27 là Thứ Hai
        now = datetime(2026, 7, 27, 10, 20)
        self.assertTrue(ct.in_active_window(now, [1, 2, 3, 4, 5], "08:00-18:00"))

    def test_ngoai_khung_gio(self):
        self.assertFalse(
            ct.in_active_window(datetime(2026, 7, 27, 21, 0), [1, 2, 3, 4, 5], "08:00-18:00"))

    def test_thu_bay_khong_quet_voi_cau_hinh_t2_t6(self):
        # 2026-08-01 là Thứ Bảy -> PTB day = 6, không nằm trong [1..5]
        self.assertFalse(
            ct.in_active_window(datetime(2026, 8, 1, 10, 0), [1, 2, 3, 4, 5], "08:00-18:00"))

    def test_chu_nhat_la_so_0_theo_quy_uoc_ptb(self):
        # 2026-08-02 là Chủ Nhật
        self.assertTrue(ct.in_active_window(datetime(2026, 8, 2, 10, 0), [0], "08:00-18:00"))

    def test_active_hours_sai_dinh_dang_thi_coi_nhu_ca_ngay(self):
        self.assertTrue(ct.in_active_window(datetime(2026, 7, 27, 23, 0),
                                            [1, 2, 3, 4, 5], "linh tinh"))


class TestLanQuetDauNgay(unittest.TestCase):
    def test_lan_quet_dau_tuyet_doi_khong_tinh(self):
        self.assertFalse(ct.is_first_scan_of_day(None, datetime(2026, 7, 27, 8, 0)))

    def test_quet_dau_tien_cua_ngay_moi(self):
        self.assertTrue(ct.is_first_scan_of_day("2026-07-26T17:50:00",
                                                datetime(2026, 7, 27, 8, 0)))

    def test_cac_lan_quet_sau_trong_ngay(self):
        self.assertFalse(ct.is_first_scan_of_day("2026-07-27T08:00:00",
                                                 datetime(2026, 7, 27, 10, 20)))
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

```bash
python -m unittest tests.test_change_tracker.TestPhanLoai -v
```

Kỳ vọng: FAIL — `AttributeError: module 'src.change_tracker' has no attribute 'classify'`.

- [ ] **Step 3: Thêm code vào cuối `src/change_tracker.py`**

```python
# ------------------------------------------------------------------
# Phân loại báo ngay / gom bản tin, bộ lọc, khung giờ quét
# ------------------------------------------------------------------
# Báo ngay dành cho thứ bắt buộc phải phản ứng; việc chạy đúng tiến độ đọc
# trong bản tin là đủ (spec mục 6).
DEFAULT_INSTANT_KINDS = ["added", "removed"]
DEFAULT_INSTANT_FIELDS = ["due", "assignee"]


def classify(change: Change, instant_kinds: Optional[List[str]] = None,
             instant_fields: Optional[List[str]] = None,
             field_map: Optional[Dict[str, str]] = None) -> str:
    """'instant' nếu thay đổi cần báo ngay, ngược lại 'digest'."""
    kinds = list(instant_kinds) if instant_kinds else DEFAULT_INSTANT_KINDS
    fields_ = list(instant_fields) if instant_fields else DEFAULT_INSTANT_FIELDS
    if change.kind in kinds:
        return "instant"
    if change.kind in ("modified", "renamed"):
        fmap = field_map or {}
        for col, _cu, _moi in change.fields or []:
            if fmap.get(col) in fields_:
                return "instant"
    return "digest"


def _wanted(filters: Dict[str, Any], key: str) -> List[str]:
    return [str(x).strip().lower() for x in (filters.get(key) or []) if str(x).strip()]


def passes_filters(change: Change, filters: Optional[Dict[str, Any]],
                   field_map: Optional[Dict[str, str]] = None) -> bool:
    """Thay đổi có được gửi đi không.

    Bộ lọc CHỈ chặn ở khâu gửi, không chặn ở khâu chụp ảnh — nếu lọc từ đầu thì
    khi mở rộng bộ lọc, hàng trăm dòng cũ sẽ bị hiểu nhầm là mới (spec mục 6).
    """
    filters = filters or {}
    fmap = field_map or {}

    nguon = _wanted(filters, "sources")
    if nguon and (change.source_id or "").lower() not in nguon:
        return False
    if change.kind == "column":
        # Thay đổi cấu trúc sheet không gắn với dự án/nhân sự nào.
        return True

    for field_name, filter_key in (("project", "projects"), ("assignee", "assignees")):
        muon = _wanted(filters, filter_key)
        if not muon:
            continue
        col = column_for(fmap, field_name)
        gia_tri = (change.cells.get(col, "") if col else "").strip().lower()
        if not any(m in gia_tri for m in muon):
            return False

    tu_khoa = _wanted(filters, "keywords")
    if tu_khoa:
        blob = " ".join(list((change.cells or {}).values()) + [change.label or ""]).lower()
        if not any(k in blob for k in tu_khoa):
            return False
    return True


def in_active_window(now: datetime, active_days: Optional[List[int]] = None,
                     active_hours: str = "08:00-18:00") -> bool:
    """Có quét vào thời điểm `now` không.

    ⚠️ active_days theo quy ước python-telegram-bot: 0=Chủ Nhật … 6=Thứ Bảy.
    Vì vậy T2–T6 là [1,2,3,4,5] — KHÔNG phải [0,1,2,3,4] (MEMORY.md mục 1).
    datetime.weekday() dùng 0=Thứ Hai nên phải quy đổi (wd + 1) % 7.
    """
    days = list(active_days) if active_days else [1, 2, 3, 4, 5]
    if ((now.weekday() + 1) % 7) not in days:
        return False
    try:
        dau, cuoi = str(active_hours).split("-")
        gio_dau, phut_dau = (int(x) for x in dau.strip().split(":"))
        gio_cuoi, phut_cuoi = (int(x) for x in cuoi.strip().split(":"))
    except (ValueError, AttributeError):
        return True     # cấu hình sai -> quét cả ngày còn hơn im lặng
    phut = now.hour * 60 + now.minute
    return gio_dau * 60 + phut_dau <= phut < gio_cuoi * 60 + phut_cuoi


def is_first_scan_of_day(last_scan_at: Optional[str], now: datetime) -> bool:
    """Đây có phải lần quét đầu tiên của một ngày mới không.

    Lần quét đầu ngày ép mọi thay đổi sang loại 'gom' để chúng đi chung một bản
    tin sáng, thay vì bắn một loạt tin lúc 08:00 (spec mục 6).
    Lần quét đầu tiên tuyệt đối (chưa có mốc cũ) trả False: khi đó chưa có ảnh
    chụp nên cũng không có gì để báo.
    """
    if not last_scan_at:
        return False
    try:
        truoc = datetime.fromisoformat(last_scan_at)
    except (ValueError, TypeError):
        return False
    return truoc.date() != now.date()
```

- [ ] **Step 4: Chạy test, phải xanh**

```bash
python -m unittest discover -s tests -t . -v
```

Kỳ vọng: `OK` — 51 test pass (7 state_store + 44 change_tracker).

- [ ] **Step 5: Commit**

```bash
python -m py_compile src/change_tracker.py
git add src/change_tracker.py tests/test_change_tracker.py
git commit -m "feat(watch): phân loại báo ngay/gom, bộ lọc gửi và khung giờ quét"
```

---

### Task 6: Dựng tin nhắn (`change_reporter`)

**Files:**
- Create: `src/change_reporter.py`
- Test: `tests/test_change_reporter.py`

**Interfaces:**
- Consumes: `change_tracker.Change`, `change_tracker.column_for`.
- Produces:
  - `format_instant(changes, sources_meta, field_maps, hhmm) -> str`
  - `format_digest(changes, sources_meta, field_maps, hhmm, since_text="", already_sent=0) -> str`
  - `format_overflow(changes, sources_meta, hhmm) -> str`
  - Trong đó `sources_meta: dict[str, str]` là `{source_id: tên hiển thị}`, `field_maps: dict[str, dict]` là `{source_id: field_map}`. Rỗng đầu vào -> trả chuỗi rỗng `""`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_change_reporter.py`:

```python
# -*- coding: utf-8 -*-
"""Test cho src/change_reporter.py — chạy được không cần telegram."""
import unittest

from src import change_reporter as cr
from src import change_tracker as ct

SOURCES = {"vnedu": "Kế hoạch vnEdu", "kiosk": "Kế hoạch Kiosk"}
HEADERS = ["Tên Task", "Nhân Sự Thực Hiện", "Hạn", "Trạng thái thực hiện"]
_, FIELD_MAP = ct.detect_mode(HEADERS)
FIELD_MAPS = {"vnedu": FIELD_MAP, "kiosk": FIELD_MAP}


def them(label, **cells):
    return ct.Change(source_id="vnedu", kind="added", label=label, cells=cells)


class TestTinBaoNgay(unittest.TestCase):
    def test_rong_thi_tra_chuoi_rong(self):
        self.assertEqual(cr.format_instant([], SOURCES, FIELD_MAPS, "10:20"), "")

    def test_co_tieu_de_va_ten_nguon(self):
        text = cr.format_instant([them("Chuẩn hoá dữ liệu")], SOURCES, FIELD_MAPS, "10:20")
        self.assertIn("10:20", text)
        self.assertIn("Kế hoạch vnEdu", text)
        self.assertIn("Chuẩn hoá dữ liệu", text)

    def test_dong_moi_kem_nguoi_va_han(self):
        ch = them("Chuẩn hoá dữ liệu", **{"Tên Task": "Chuẩn hoá dữ liệu",
                                          "Nhân Sự Thực Hiện": "Lan", "Hạn": "30/07"})
        text = cr.format_instant([ch], SOURCES, FIELD_MAPS, "10:20")
        self.assertIn("Lan", text)
        self.assertIn("30/07", text)

    def test_doi_han_hien_cu_sang_moi(self):
        ch = ct.Change(source_id="vnedu", kind="modified", label="Đồng bộ điểm",
                       fields=[["Hạn", "26/07", "30/07"]])
        text = cr.format_instant([ch], SOURCES, FIELD_MAPS, "10:20")
        self.assertIn("26/07", text)
        self.assertIn("30/07", text)
        self.assertIn("→", text)

    def test_xoa_dong(self):
        ch = ct.Change(source_id="vnedu", kind="removed", label="Rà soát tài khoản cũ")
        self.assertIn("Rà soát tài khoản cũ",
                      cr.format_instant([ch], SOURCES, FIELD_MAPS, "10:20"))

    def test_doi_ten_hien_ca_hai_ten(self):
        ch = ct.Change(source_id="vnedu", kind="renamed", label="Rà soát & làm sạch",
                       old_label="Rà soát dữ liệu")
        text = cr.format_instant([ch], SOURCES, FIELD_MAPS, "10:20")
        self.assertIn("Rà soát dữ liệu", text)
        self.assertIn("Rà soát &amp; làm sạch", text)   # đã escape

    def test_escape_ky_tu_html(self):
        ch = them("<b>Không được in đậm</b>")
        text = cr.format_instant([ch], SOURCES, FIELD_MAPS, "10:20")
        self.assertNotIn("<b>Không", text)
        self.assertIn("&lt;b&gt;", text)

    def test_gom_theo_tung_nguon(self):
        a = them("A")
        b = ct.Change(source_id="kiosk", kind="added", label="B")
        text = cr.format_instant([a, b], SOURCES, FIELD_MAPS, "10:20")
        self.assertIn("Kế hoạch vnEdu", text)
        self.assertIn("Kế hoạch Kiosk", text)

    def test_nguon_khong_khai_ten_thi_dung_id(self):
        ch = ct.Change(source_id="la_hoac", kind="added", label="X")
        self.assertIn("la_hoac", cr.format_instant([ch], SOURCES, FIELD_MAPS, "10:20"))


class TestBanTin(unittest.TestCase):
    def test_co_so_luong_va_moc_thoi_gian(self):
        text = cr.format_digest([them("A"), them("B")], SOURCES, FIELD_MAPS,
                                "16:30", "Từ 08:30 hôm nay", 0)
        self.assertIn("16:30", text)
        self.assertIn("Từ 08:30 hôm nay", text)
        self.assertIn("2", text)

    def test_ghi_chu_so_thay_doi_da_bao_ngay(self):
        text = cr.format_digest([them("A")], SOURCES, FIELD_MAPS, "16:30", "", 3)
        self.assertIn("3", text)
        self.assertIn("đã báo", text.lower())

    def test_khong_ghi_chu_khi_chua_bao_ngay_cai_nao(self):
        text = cr.format_digest([them("A")], SOURCES, FIELD_MAPS, "16:30", "", 0)
        self.assertNotIn("đã báo", text.lower())

    def test_them_cot_moi(self):
        ch = ct.Change(source_id="vnedu", kind="column", label="Rủi ro",
                       fields=[["Rủi ro", "", "(cột mới)"]])
        self.assertIn("Rủi ro", cr.format_digest([ch], SOURCES, FIELD_MAPS, "16:30"))


class TestTinTomTat(unittest.TestCase):
    def test_neu_ten_nguon_nhieu_thay_doi_nhat_va_goi_y_lenh(self):
        changes = [them("A") for _ in range(40)] + [
            ct.Change(source_id="kiosk", kind="added", label="B")]
        text = cr.format_overflow(changes, SOURCES, "10:20")
        self.assertIn("41", text)
        self.assertIn("Kế hoạch vnEdu", text)
        self.assertIn("/moi", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

```bash
python -m unittest tests.test_change_reporter -v
```

Kỳ vọng: FAIL — `ModuleNotFoundError: No module named 'src.change_reporter'`.

- [ ] **Step 3: Viết `src/change_reporter.py`**

```python
# -*- coding: utf-8 -*-
"""Dựng nội dung tin nhắn thông báo thay đổi (HTML cho Telegram).

Thuần stdlib — KHÔNG import telegram/gspread, để test được trên máy dev.
Mọi nội dung động phải đi qua _esc: các tin này luôn được gửi với
parse_mode=ParseMode.HTML (AGENTS.md bẫy số 2).
"""
import html
from collections import OrderedDict
from typing import Dict, List, Optional

from .change_tracker import Change, column_for

KIND_ICONS = {
    "added": "🆕",
    "removed": "🗑️",
    "renamed": "✏️",
    "modified": "📝",
    "column": "➕",
}
FIELD_ICONS = {"due": "📅", "assignee": "👤", "status": "✅"}

MAX_VALUE_LEN = 60   # cắt bớt giá trị dài cho dễ đọc


def _esc(text) -> str:
    return html.escape(str(text or ""), quote=False)


def _gon(value: str) -> str:
    value = (str(value or "")).strip()
    if not value:
        return "(trống)"
    if len(value) > MAX_VALUE_LEN:
        value = value[:MAX_VALUE_LEN - 1] + "…"
    return value


def _nhom_theo_nguon(changes: List[Change]) -> "OrderedDict[str, List[Change]]":
    nhom: "OrderedDict[str, List[Change]]" = OrderedDict()
    for ch in changes:
        nhom.setdefault(ch.source_id, []).append(ch)
    return nhom


def _ten_nguon(source_id: str, sources_meta: Optional[Dict[str, str]]) -> str:
    return (sources_meta or {}).get(source_id) or source_id


def _dong_them(ch: Change, field_map: Dict[str, str]) -> str:
    """Dòng cho một mục mới: tên việc — người · hạn."""
    phu = []
    for field_name, mau in (("assignee", "%s"), ("due", "hạn %s")):
        col = column_for(field_map or {}, field_name)
        value = (ch.cells.get(col, "") if col else "").strip()
        if value:
            phu.append(mau % _esc(value))
    duoi = (" — " + " · ".join(phu)) if phu else ""
    return "  🆕 %s%s" % (_esc(ch.label), duoi)


def _dong_thay_doi(ch: Change, field_map: Dict[str, str]) -> List[str]:
    """Các dòng cho một thay đổi bất kỳ."""
    fmap = field_map or {}
    if ch.kind == "added":
        return [_dong_them(ch, fmap)]
    if ch.kind == "removed":
        return ["  🗑️ Đã xoá: %s" % _esc(ch.label)]
    if ch.kind == "column":
        moi = any((m or "").strip() == "(cột mới)" for _c, _c2, m in ch.fields or [])
        mau = "  ➕ Sheet có thêm cột \"%s\"" if moi else "  ➖ Sheet đã bỏ cột \"%s\""
        return [mau % _esc(ch.label)]

    dong = []
    if ch.kind == "renamed":
        dong.append("  ✏️ Đổi tên: %s → %s" % (_esc(ch.old_label), _esc(ch.label)))
        con_lai = [f for f in (ch.fields or [])
                   if (f[2] or "").strip() != (ch.label or "").strip()]
    else:
        con_lai = list(ch.fields or [])

    if ch.kind == "modified" and len(con_lai) == 1:
        col, cu, moi = con_lai[0]
        icon = FIELD_ICONS.get(fmap.get(col), KIND_ICONS["modified"])
        return ["  %s %s — %s: %s → %s" % (icon, _esc(ch.label), _esc(col),
                                           _esc(_gon(cu)), _esc(_gon(moi)))]
    if ch.kind == "modified":
        dong.append("  %s %s" % (KIND_ICONS["modified"], _esc(ch.label)))
    for col, cu, moi in con_lai:
        dong.append("        %s: %s → %s" % (_esc(col), _esc(_gon(cu)), _esc(_gon(moi))))
    return dong


def _than_bai(changes: List[Change], sources_meta, field_maps) -> List[str]:
    phan = []
    for source_id, nhom in _nhom_theo_nguon(changes).items():
        phan.append("")
        phan.append("📗 <b>%s</b> (%d)" % (_esc(_ten_nguon(source_id, sources_meta)),
                                           len(nhom)))
        for ch in nhom:
            phan.extend(_dong_thay_doi(ch, (field_maps or {}).get(source_id, {})))
    return phan


def format_instant(changes: List[Change], sources_meta: Dict[str, str],
                   field_maps: Dict[str, dict], hhmm: str) -> str:
    """Tin báo ngay."""
    if not changes:
        return ""
    dong = ["🔔 <b>Thay đổi kế hoạch</b> · %s" % _esc(hhmm)]
    dong.extend(_than_bai(changes, sources_meta, field_maps))
    return "\n".join(dong)


def format_digest(changes: List[Change], sources_meta: Dict[str, str],
                  field_maps: Dict[str, dict], hhmm: str,
                  since_text: str = "", already_sent: int = 0) -> str:
    """Bản tin gom."""
    if not changes:
        return ""
    so_nguon = len(_nhom_theo_nguon(changes))
    phu = "%d file · %d thay đổi" % (so_nguon, len(changes))
    if since_text:
        phu = "%s · %s" % (_esc(since_text), phu)
    dong = ["📬 <b>Bản tin thay đổi</b> · %s" % _esc(hhmm), phu]
    dong.extend(_than_bai(changes, sources_meta, field_maps))
    if already_sent:
        dong.append("")
        dong.append("(%d thay đổi đã báo ngay trước đó)" % already_sent)
    return "\n".join(dong)


def format_overflow(changes: List[Change], sources_meta: Dict[str, str],
                    hhmm: str) -> str:
    """Tin tóm tắt khi một lần quét ra quá nhiều thay đổi."""
    if not changes:
        return ""
    nhom = _nhom_theo_nguon(changes)
    nhieu_nhat = max(nhom, key=lambda k: len(nhom[k]))
    return ("🔔 <b>%d thay đổi</b> vừa được ghi nhận lúc %s, chủ yếu ở <b>%s</b>.\n"
            "Gõ /moi để xem chi tiết." % (len(changes), _esc(hhmm),
                                          _esc(_ten_nguon(nhieu_nhat, sources_meta))))
```

- [ ] **Step 4: Chạy test, phải xanh**

```bash
python -m unittest discover -s tests -t . -v
```

Kỳ vọng: `OK` — 65 test pass.

- [ ] **Step 5: Commit**

```bash
python -m py_compile src/change_reporter.py
git add src/change_reporter.py tests/test_change_reporter.py
git commit -m "feat(watch): dựng tin báo ngay, bản tin gom và tin tóm tắt (HTML)"
```

---

### Task 7: Đọc bất kỳ file sheet nào (`sheets_client`)

**Files:**
- Modify: `src/sheets_client.py` — thêm `import json` ở đầu; thêm 3 method vào cuối class `SheetsClient` (sau `_members_from_validation`, trước dòng `sheets = SheetsClient()`)

**Interfaces:**
- Consumes: `SheetsClient._client()` (đã có), `_col_letter` (đã có).
- Produces:
  - `sheets.fetch_rows(spreadsheet_id: str, worksheet_name: str = "") -> tuple[list[str], list[dict]]` — rows dạng `[{"row": int, "cells": {header: value}}]`, khớp đúng đầu vào của `change_tracker.build_snapshot`
  - `sheets.list_worksheets(spreadsheet_id: str) -> list[str]`
  - `sheets.service_account_email() -> str`

> Ba method này gọi gspread nên **không** test tự động được trên máy dev (AGENTS.md mục 11). Xác minh bằng `py_compile` + script stub như Step 3.

- [ ] **Step 1: Thêm `import json` vào `src/sheets_client.py`**

Sửa khối import ở đầu file, từ:

```python
import logging
import time
```

thành:

```python
import json
import logging
import time
```

- [ ] **Step 2: Thêm 3 method vào cuối class `SheetsClient`**

Chèn ngay trước dòng cuối cùng của file (`sheets = SheetsClient()`), thụt lề bên trong class:

```python
    # ------------------------------------------------------------------
    # Đọc bất kỳ file/tab nào (phục vụ chức năng theo dõi thay đổi)
    # ------------------------------------------------------------------
    def fetch_rows(self, spreadsheet_id: str, worksheet_name: str = ""):
        """Đọc một worksheet bất kỳ -> (headers, rows).

        rows: [{"row": <số dòng trên sheet>, "cells": {tên cột: giá trị}}] —
        đúng dạng change_tracker.build_snapshot cần. Không dùng cache của
        fetch_tasks: job theo dõi tự quyết chu kỳ đọc.

        Tên cột trống được đặt tên theo chữ cái cột; tên cột trùng nhau được
        gắn hậu tố, vì change_tracker dùng tên cột làm khoá của từng ô.
        """
        sh = self._client().open_by_key(spreadsheet_id)
        ws = sh.worksheet(worksheet_name) if worksheet_name else sh.get_worksheet(0)
        values = ws.get_all_values()
        if not values:
            return [], []

        headers, dem = [], {}
        for idx, raw in enumerate(values[0], start=1):
            name = (raw or "").strip() or "Cột %s" % _col_letter(idx)
            dem[name] = dem.get(name, 0) + 1
            if dem[name] > 1:
                name = "%s (%d)" % (name, dem[name])
            headers.append(name)

        rows = []
        for so_dong, raw in enumerate(values[1:], start=2):
            cells = {h: (raw[i].strip() if i < len(raw) else "")
                     for i, h in enumerate(headers)}
            if not any(cells.values()):
                continue
            rows.append({"row": so_dong, "cells": cells})
        return headers, rows

    def list_worksheets(self, spreadsheet_id: str):
        """Tên các tab trong một file (cho lệnh /nguon tab)."""
        return [ws.title for ws in self._client().open_by_key(spreadsheet_id).worksheets()]

    def service_account_email(self) -> str:
        """Email service account — để hướng dẫn share file. KHÔNG phải khoá bí mật.

        Chỉ trả lời trong chat riêng với admin; nội dung credentials.json thì không
        bao giờ đưa ra ngoài.
        """
        path = cfg.get("google_sheets.credentials_file", "credentials.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("client_email", "")
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Không đọc được email service account: %s", e)
            return ""
```

- [ ] **Step 3: Xác minh bằng script stub (máy dev không có gspread)**

Tạo file tạm trong scratchpad rồi chạy — script này giả lập gspread để kiểm tra riêng phần bóc tách headers/rows:

```python
# scratchpad/kiem_tra_fetch_rows.py
import sys, types

# Stub các module ngoài (quy ước xác minh trong AGENTS.md mục 11)
for ten in ("gspread", "google", "google.oauth2", "google.oauth2.service_account"):
    sys.modules.setdefault(ten, types.ModuleType(ten))
sys.modules["google.oauth2.service_account"].Credentials = type(
    "C", (), {"from_service_account_file": staticmethod(lambda *a, **k: None)})
sys.modules["gspread"].authorize = lambda *a, **k: None

from src.sheets_client import SheetsClient

class FakeWs:
    def get_all_values(self):
        return [["Tên Task", "", "Hạn", "Hạn"],
                ["Đồng bộ điểm", "x", " 26/07 ", "30/07"],
                ["", "", "", ""],
                ["Nâng cấp"]]

class FakeSh:
    def worksheet(self, name): return FakeWs()
    def get_worksheet(self, i): return FakeWs()

client = SheetsClient()
client._client = lambda: type("G", (), {"open_by_key": lambda self, k: FakeSh()})()
headers, rows = client.fetch_rows("id", "tab")
print("headers:", headers)
print("rows:", rows)
assert headers == ["Tên Task", "Cột B", "Hạn", "Hạn (2)"], headers
assert len(rows) == 2, rows                       # dòng trống bị bỏ
assert rows[0]["row"] == 2
assert rows[0]["cells"]["Hạn"] == "26/07"         # đã strip
assert rows[1]["cells"]["Hạn"] == ""              # dòng thiếu ô -> chuỗi rỗng
print("OK")
```

Chạy từ thư mục gốc repo:

```bash
python "C:/Users/LeAnh/AppData/Local/Temp/claude/C--Users-LeAnh-Documents-telegram-report-bot/6620f28f-ea26-4934-acd6-ada4c49cf165/scratchpad/kiem_tra_fetch_rows.py"
```

Kỳ vọng: in `headers`, `rows` rồi `OK`, không AssertionError.

- [ ] **Step 4: Kiểm tra cú pháp và test cũ không vỡ**

```bash
python -m py_compile src/*.py && python -m unittest discover -s tests -t . -v
```

Kỳ vọng: py_compile im lặng; test `OK` — 65 test.

- [ ] **Step 5: Commit**

```bash
git add src/sheets_client.py
git commit -m "feat(watch): đọc được worksheet bất kỳ, liệt kê tab và email service account"
```

---

### Task 8: Job quét định kỳ + cấu hình + volume

**Files:**
- Modify: `src/bot.py` — thêm import, hằng số, hàm helper, `job_watch_scan`, `register_watch_jobs`; gọi từ `register_jobs`
- Modify: `config.example.yaml` — thêm khối `watch`
- Modify: `docker-compose.yml` — mount `./state`
- Modify: `.gitignore` — bỏ qua `state/`

**Interfaces:**
- Consumes: `state_store.load/save/default_state` (T1) · `ct.detect_mode/build_snapshot/diff_snapshots/match_renames/classify/passes_filters/in_active_window/is_first_scan_of_day/Change` (T2–T5) · `cr.format_instant/format_overflow` (T6) · `sheets.fetch_rows` (T7) · `send_long`, `tz()`, `register_jobs` (đã có).
- Produces: `watch_state_path() -> str` · `now_dt() -> datetime` · `_scan_source(src: dict, state: dict, now) -> tuple[list[Change], Exception|None]` · `_field_maps(state: dict) -> dict` · `_sources_meta() -> dict` · `_send_watch(context, mode, changes, field_maps, now, since_text="", already=0)` · `job_watch_scan(context)` · `register_watch_jobs(app)`.

- [ ] **Step 1: Thêm import và helper vào `src/bot.py`**

Sửa khối import, từ:

```python
from .config import cfg
from . import report_generator as rg
from .sheets_client import sheets
```

thành:

```python
from .config import cfg
from . import change_reporter as cr
from . import change_tracker as ct
from . import report_generator as rg
from . import state_store
from .sheets_client import sheets
```

Ngay sau `MAX_LEN = 4000`, thêm:

```python
WATCH_STATE_FILE = "state/watch_state.json"   # ghi đè bằng watch.state_file
```

Ngay sau hàm `today()`, thêm:

```python
def now_dt() -> datetime:
    """Thời điểm hiện tại theo múi giờ cấu hình."""
    return datetime.now(tz())


def watch_state_path() -> str:
    return cfg.get("watch.state_file", WATCH_STATE_FILE)


def _sources_meta() -> dict:
    """{id nguồn: tên hiển thị} cho phần dựng tin."""
    meta = {}
    for src in cfg.get("watch.sources", []) or []:
        sid = str(src.get("id") or "").strip()
        if sid:
            meta[sid] = src.get("name") or sid
    return meta


def _field_maps(state: dict) -> dict:
    """{id nguồn: field_map} lấy từ trạng thái đã lưu."""
    return {sid: (info or {}).get("field_map") or {}
            for sid, info in (state.get("sources") or {}).items()}
```

- [ ] **Step 2: Thêm phần quét vào `src/bot.py`**

Chèn ngay trước dòng `JOBS = {` (tức sau `job_weekly_summary`):

```python
# ============================================================
# THEO DÕI THAY ĐỔI TRÊN CÁC SHEET KẾ HOẠCH
# ============================================================
def _scan_source(src: dict, state: dict, now):
    """Quét một nguồn, cập nhật ảnh chụp trong `state`.

    Trả về (danh sách Change, lỗi hoặc None). Không gửi tin nhắn — việc gửi do
    job quyết định sau khi đã gom đủ mọi nguồn.
    """
    sid = str(src.get("id") or "").strip()
    truoc = (state.get("sources") or {}).get(sid) or {}
    try:
        headers, rows = sheets.fetch_rows(src.get("spreadsheet_id"),
                                          src.get("worksheet_name") or "")
    except Exception as e:   # một nguồn hỏng không được làm chết cả job
        return [], e

    mode, field_map = ct.detect_mode(headers, src.get("columns"))
    snapshot = ct.build_snapshot(rows, headers, field_map, mode,
                                 src.get("key_column", "") or "")
    hien_tai = {
        "mode": mode, "headers": headers, "field_map": field_map,
        "snapshot": snapshot, "scanned_at": now.isoformat(),
        "rows": len(snapshot), "error": None, "fail_count": 0,
    }

    changes = []
    if truoc.get("snapshot"):
        changes = ct.match_renames(ct.diff_snapshots(truoc, hien_tai, sid))
    else:
        log.info("Nguồn %s: chụp ảnh lần đầu (%d dòng), chưa báo gì", sid, len(snapshot))

    state.setdefault("sources", {})[sid] = hien_tai
    return changes, None


async def _bao_loi_nguon(context, state: dict, src: dict, err) -> None:
    """Báo admin đúng một lần cho mỗi nguồn hỏng, và báo khi khôi phục."""
    sid = str(src.get("id") or "").strip()
    info = state.setdefault("sources", {}).setdefault(sid, {})
    ten = src.get("name") or sid

    if err is None:
        if info.get("error"):
            info["error"], info["fail_count"] = None, 0
            await _nhan_admin(context, "✅ Đã đọc lại được nguồn “%s”." % ten)
        return

    info["fail_count"] = int(info.get("fail_count") or 0) + 1
    info["scanned_at"] = info.get("scanned_at")
    # Lỗi mạng/quota tạm thời: im lặng thử lại, chỉ báo sau 3 lần liên tiếp.
    if info.get("error") or info["fail_count"] < 3:
        if not info.get("error"):
            log.warning("Nguồn %s lỗi lần %d: %s", sid, info["fail_count"], err)
            return
        return
    info["error"] = str(err)
    await _nhan_admin(
        context,
        "⚠️ Không đọc được nguồn “%s”: %s\n\n"
        "Kiểm tra: đã chia sẻ file cho %s quyền Viewer chưa, "
        "và tab “%s” còn tồn tại không (dùng /nguon tab %s để xem)."
        % (ten, err, sheets.service_account_email() or "(service account)",
           src.get("worksheet_name") or "(tab đầu tiên)", sid))


async def _nhan_admin(context, text: str) -> None:
    for admin_id in cfg.admin_ids:
        try:
            await context.bot.send_message(admin_id, text)
        except Exception as e:
            log.warning("Không gửi được tin cho admin %s: %s", admin_id, e)


async def _send_watch(context, mode: str, changes, field_maps, now,
                      since_text: str = "", already: int = 0) -> None:
    """Gửi thay đổi tới các đích đã cấu hình, mỗi đích một bộ lọc riêng."""
    if not changes:
        return
    meta = _sources_meta()
    hhmm = now.strftime("%H:%M")
    max_items = int(cfg.get("watch.max_instant_items", 15) or 15)
    chung = cfg.get("watch.filters") or {}

    for target in cfg.get("watch.targets", []) or []:
        nhan = target.get("send") or ["instant", "digest"]
        if mode not in nhan:
            continue
        loc = target.get("filters") or chung
        chon = [c for c in changes
                if ct.passes_filters(c, loc, field_maps.get(c.source_id))]
        if not chon:
            continue
        if mode == "instant" and len(chon) > max_items:
            text = cr.format_overflow(chon, meta, hhmm)
        elif mode == "instant":
            text = cr.format_instant(chon, meta, field_maps, hhmm)
        else:
            text = cr.format_digest(chon, meta, field_maps, hhmm, since_text, already)
        await send_long(context.bot, target.get("chat_id"), text,
                        target.get("topic_id"), parse_mode=ParseMode.HTML)


async def job_watch_scan(context: ContextTypes.DEFAULT_TYPE):
    """Quét định kỳ các sheet kế hoạch, báo ngay phần cần phản ứng."""
    if not cfg.get("watch.enabled", False):
        return
    now = now_dt()
    if not ct.in_active_window(now, cfg.get("watch.active_days"),
                               cfg.get("watch.active_hours", "08:00-18:00")):
        return

    state = state_store.load(watch_state_path())
    # Lần quét đầu của ngày mới gom hết thay đổi qua đêm vào bản tin sáng,
    # thay vì bắn một loạt tin lúc mở khung giờ.
    ep_gom = ct.is_first_scan_of_day(state.get("last_scan_at"), now)

    moi = []
    for src in cfg.get("watch.sources", []) or []:
        if not str(src.get("id") or "").strip():
            log.warning("Bỏ qua nguồn thiếu 'id' trong watch.sources")
            continue
        changes, err = _scan_source(src, state, now)
        await _bao_loi_nguon(context, state, src, err)
        moi.extend(changes)

    field_maps = _field_maps(state)
    for ch in moi:
        ch.at = now.isoformat()
        loai = "digest" if ep_gom else ct.classify(
            ch, cfg.get("watch.instant_kinds"), cfg.get("watch.instant_fields"),
            field_maps.get(ch.source_id))
        ch.instant_sent = (loai == "instant")

    state.setdefault("pending", []).extend(c.to_dict() for c in moi)
    state["last_scan_at"] = now.isoformat()
    state_store.save(watch_state_path(), state)

    ngay = [c for c in moi if c.instant_sent]
    if ngay:
        await _send_watch(context, "instant", ngay, field_maps, now)
        log.info("Đã báo ngay %d thay đổi", len(ngay))
```

- [ ] **Step 3: Đăng ký job trong `register_jobs`**

Thêm hàm mới ngay sau `register_jobs`:

```python
def register_watch_jobs(app: Application):
    """Job quét định kỳ cho chức năng theo dõi thay đổi."""
    if not cfg.get("watch.enabled", False):
        return
    phut = max(1, int(cfg.get("watch.poll_interval_minutes", 10) or 10))
    app.job_queue.run_repeating(job_watch_scan, interval=phut * 60, first=30,
                                name="watch_scan")
    log.info("Đã lên lịch quét thay đổi mỗi %d phút", phut)
```

Và ở **cuối** thân hàm `register_jobs` (sau vòng `for name, callback in JOBS.items():`), thêm dòng:

```python
    register_watch_jobs(app)
```

- [ ] **Step 4: Thêm khối `watch` vào `config.example.yaml`**

Chèn vào cuối file:

```yaml
# ------------------------------------------------------------------
# Theo dõi thay đổi trên các file sheet KẾ HOẠCH (khác sheet báo cáo ở trên).
# Thêm/bớt nguồn ngay trên Telegram bằng lệnh /nguon — không cần sửa file này.
# ------------------------------------------------------------------
watch:
  enabled: false                    # bật bằng /theodoi bat
  poll_interval_minutes: 10
  # LƯU Ý: cùng quy ước với schedules ở trên — 0=Chủ Nhật ... 6=Thứ Bảy.
  # => [1, 2, 3, 4, 5] = Thứ Hai -> Thứ Sáu.
  active_days: [1, 2, 3, 4, 5]
  active_hours: '08:00-18:00'       # ngoài khung giờ không quét
  digest_times: ['08:30', '16:30']  # giờ gửi bản tin gom
  max_instant_items: 15             # quá ngưỡng thì gửi tin tóm tắt
  state_file: state/watch_state.json
  instant_kinds: [added, removed]   # loại thay đổi báo ngay
  instant_fields: [due, assignee]   # trường đổi thì báo ngay
  sources: []                       # do /nguon them điền vào
  targets:
    - chat_id: 123456789            # chat riêng: nhận đủ
      send: [instant, digest]
    - chat_id: -1000000000000       # nhóm team: chỉ bản tin
      topic_id: 0
      send: [digest]
  filters:                          # trống = không lọc
    sources: []
    projects: []                    # chỉ có tác dụng ở chế độ task
    assignees: []                   # chỉ có tác dụng ở chế độ task
    keywords: []                    # khớp mọi ô — dùng được cho chế độ generic
```

- [ ] **Step 5: Mount thư mục trạng thái trong `docker-compose.yml`**

Sửa khối `volumes`, từ:

```yaml
    volumes:
      # mount rw để lệnh /cauhinh set lưu được thay đổi vào config.yaml
      - ./config.yaml:/app/config.yaml
      - ./credentials.json:/app/credentials.json:ro
```

thành:

```yaml
    volumes:
      # mount rw để lệnh /cauhinh set lưu được thay đổi vào config.yaml
      - ./config.yaml:/app/config.yaml
      - ./credentials.json:/app/credentials.json:ro
      # ảnh chụp sheet của chức năng theo dõi thay đổi — mất thư mục này thì
      # bot chỉ chụp lại từ đầu (im lặng), không dội tin
      - ./state:/app/state
```

- [ ] **Step 6: Bỏ qua `state/` trong `.gitignore`**

Thêm vào cuối mục "Secrets":

```
# Trạng thái theo dõi thay đổi (ảnh chụp sheet) — không commit
state/
```

- [ ] **Step 7: Kiểm tra cú pháp và test**

```bash
python -m py_compile src/*.py && python -m unittest discover -s tests -t . && python -c "import yaml; d=yaml.safe_load(open('config.example.yaml',encoding='utf-8')); print(d['watch']['active_days'], d['watch']['digest_times'])"
```

Kỳ vọng: py_compile im lặng · test `OK` · in ra `[1, 2, 3, 4, 5] ['08:30', '16:30']`.

- [ ] **Step 8: Commit**

```bash
git add src/bot.py config.example.yaml docker-compose.yml .gitignore
git commit -m "feat(watch): job quét định kỳ, báo ngay thay đổi và cấu hình mẫu"
```

---

### Task 9: Bản tin gom + lệnh `/moi`

**Files:**
- Modify: `src/bot.py` — thêm `job_watch_digest`, `_mo_ta_tu_luc`, `cmd_moi`; đăng ký job bản tin và handler

**Interfaces:**
- Consumes: `_send_watch`, `_field_maps`, `watch_state_path`, `now_dt`, `register_watch_jobs` (T8) · `state_store` (T1) · `ct.Change.from_dict` (T3) · `cr.format_digest` (T6).
- Produces: `_mo_ta_tu_luc(last_digest_at: str|None, now) -> str` · `job_watch_digest(context)` · `cmd_moi(update, context)`.

- [ ] **Step 1: Thêm bản tin gom vào `src/bot.py`**

Chèn ngay sau `job_watch_scan`:

```python
def _mo_ta_tu_luc(last_digest_at, now) -> str:
    """Mô tả khoảng thời gian của bản tin, VD 'Từ 08:30 hôm nay'."""
    if not last_digest_at:
        return "Từ lần chạy gần nhất"
    try:
        truoc = datetime.fromisoformat(last_digest_at)
    except (ValueError, TypeError):
        return "Từ lần chạy gần nhất"
    if truoc.date() == now.date():
        return "Từ %s hôm nay" % truoc.strftime("%H:%M")
    return "Từ %s" % truoc.strftime("%H:%M %d/%m")


async def job_watch_digest(context: ContextTypes.DEFAULT_TYPE):
    """Gom các thay đổi chưa báo ngay thành một bản tin."""
    if not cfg.get("watch.enabled", False):
        return
    now = now_dt()
    state = state_store.load(watch_state_path())
    cho = [ct.Change.from_dict(d) for d in (state.get("pending") or [])]
    gom = [c for c in cho if not c.instant_sent]
    da_bao = len(cho) - len(gom)

    if gom:
        await _send_watch(context, "digest", gom, _field_maps(state), now,
                          _mo_ta_tu_luc(state.get("last_digest_at"), now), da_bao)
        log.info("Đã gửi bản tin thay đổi (%d mục)", len(gom))

    state["pending"] = []
    state["last_digest_at"] = now.isoformat()
    state_store.save(watch_state_path(), state)
```

- [ ] **Step 2: Đăng ký job bản tin trong `register_watch_jobs`**

Thêm vào cuối thân hàm `register_watch_jobs`, sau dòng `log.info("Đã lên lịch quét...")`:

```python
    # PTB >=20: 0=Chủ Nhật ... 6=Thứ Bảy. [1..5] = Thứ Hai -> Thứ Sáu.
    days = tuple(cfg.get("watch.active_days", [1, 2, 3, 4, 5]) or [1, 2, 3, 4, 5])
    for hhmm in cfg.get("watch.digest_times", ["08:30", "16:30"]) or []:
        try:
            hh, mm = map(int, str(hhmm).split(":"))
        except ValueError:
            log.warning("Giờ bản tin không hợp lệ: %s", hhmm)
            continue
        app.job_queue.run_daily(job_watch_digest, time=dtime(hh, mm, tzinfo=tz()),
                                days=days, name="watch_digest_%02d%02d" % (hh, mm))
        log.info("Đã lên lịch bản tin thay đổi lúc %02d:%02d các ngày %s", hh, mm, days)
```

- [ ] **Step 3: Thêm lệnh `/moi`**

Chèn ngay sau `cmd_tai`:

```python
async def cmd_moi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem các thay đổi kể từ bản tin gần nhất (không xoá hàng chờ)."""
    now = now_dt()
    state = state_store.load(watch_state_path())
    cho = [ct.Change.from_dict(d) for d in (state.get("pending") or [])]
    if not cho:
        moc = state.get("last_digest_at")
        khi = ""
        if moc:
            try:
                khi = " lúc %s" % datetime.fromisoformat(moc).strftime("%H:%M")
            except (ValueError, TypeError):
                khi = ""
        await update.message.reply_text("Không có thay đổi mới kể từ bản tin%s." % khi)
        return

    gom = [c for c in cho if not c.instant_sent]
    text = cr.format_digest(gom or cho, _sources_meta(), _field_maps(state),
                            now.strftime("%H:%M"),
                            _mo_ta_tu_luc(state.get("last_digest_at"), now),
                            len(cho) - len(gom) if gom else 0)
    await send_long(context.bot, update.effective_chat.id, text,
                    update.message.message_thread_id, parse_mode=ParseMode.HTML)
```

- [ ] **Step 4: Đăng ký handler trong `main()`**

Thêm ngay sau dòng `app.add_handler(CommandHandler("tai", cmd_tai))`:

```python
    app.add_handler(CommandHandler("moi", cmd_moi))
```

- [ ] **Step 5: Xác minh bằng script stub**

Tạo và chạy script kiểm tra `_mo_ta_tu_luc` cùng luồng gom/không-gom (không cần telegram vì chỉ gọi hàm thuần):

```python
# scratchpad/kiem_tra_digest.py
import os, sys, tempfile
from datetime import datetime

from src import change_tracker as ct
from src import change_reporter as cr
from src import state_store

# Hàng chờ: 1 mục đã báo ngay + 2 mục chờ gom
pending = [
    ct.Change(source_id="vnedu", kind="added", label="A", instant_sent=True).to_dict(),
    ct.Change(source_id="vnedu", kind="modified", label="B",
              fields=[["Trạng thái thực hiện", "Đang thực hiện", "Hoàn thành"]]).to_dict(),
    ct.Change(source_id="vnedu", kind="column", label="Rủi ro",
              fields=[["Rủi ro", "", "(cột mới)"]]).to_dict(),
]
path = os.path.join(tempfile.mkdtemp(), "watch_state.json")
state = state_store.default_state()
state["pending"] = pending
state["last_digest_at"] = "2026-07-27T08:30:00"
state_store.save(path, state)

lai = state_store.load(path)
cho = [ct.Change.from_dict(d) for d in lai["pending"]]
gom = [c for c in cho if not c.instant_sent]
assert len(gom) == 2, gom
text = cr.format_digest(gom, {"vnedu": "Kế hoạch vnEdu"}, {"vnedu": {}},
                        "16:30", "Từ 08:30 hôm nay", len(cho) - len(gom))
print(text)
assert "Kế hoạch vnEdu" in text
assert "1 thay đổi đã báo ngay trước đó" in text
assert "Rủi ro" in text
print("OK")
```

```bash
python "C:/Users/LeAnh/AppData/Local/Temp/claude/C--Users-LeAnh-Documents-telegram-report-bot/6620f28f-ea26-4934-acd6-ada4c49cf165/scratchpad/kiem_tra_digest.py"
```

Kỳ vọng: in bản tin rồi `OK`.

- [ ] **Step 6: Kiểm tra cú pháp, test, commit**

```bash
python -m py_compile src/*.py && python -m unittest discover -s tests -t .
git add src/bot.py
git commit -m "feat(watch): bản tin gom theo giờ và lệnh /moi"
```

---

### Task 10: Lệnh `/nguon`, `/theodoi` và mở rộng `/cauhinh`

**Files:**
- Modify: `src/bot.py` — thêm `cmd_nguon`, `cmd_theodoi`, hàm bóc id sheet, cập nhật `LIST_KEYS`, `HELP_TEXT`, `cmd_cauhinh`, `main()`

**Interfaces:**
- Consumes: `sheets.fetch_rows/list_worksheets/service_account_email` (T7) · `ct.detect_mode/build_snapshot` (T2) · `state_store` (T1) · `watch_state_path`, `now_dt`, `register_jobs` (T8).
- Produces: `SHEET_ID_RE` · `_boc_spreadsheet_id(raw: str) -> str` · `_slug(text: str) -> str` · `cmd_nguon(update, context)` · `cmd_theodoi(update, context)`.

- [ ] **Step 1: Thêm helper bóc link sheet**

Chèn ngay trước `def _parse_scalar(raw: str):`:

```python
# Link sheet dạng https://docs.google.com/spreadsheets/d/<ID>/edit#gid=0
SHEET_ID_RE = re.compile(r"/d/([a-zA-Z0-9-_]{20,})")


def _boc_spreadsheet_id(raw: str) -> str:
    """Lấy spreadsheet_id từ link đầy đủ hoặc từ id dán trần."""
    raw = (raw or "").strip()
    khop = SHEET_ID_RE.search(raw)
    if khop:
        return khop.group(1)
    return raw if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", raw) else ""


def _slug(text: str) -> str:
    """Sinh id ngắn không dấu từ tên hiển thị."""
    bang = str.maketrans(
        "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
        "ùúủũụưừứửữựỳýỷỹỵđ",
        "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooo"
        "uuuuuuuuuuuyyyyyd")
    s = re.sub(r"[^a-z0-9]+", "_", text.lower().translate(bang)).strip("_")
    return s[:20] or "nguon"
```

Và thêm `import re` vào khối import đầu file (sau `import logging`).

- [ ] **Step 2: Thêm lệnh `/nguon`**

Chèn ngay sau `cmd_moi`:

```python
async def cmd_nguon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quản lý danh sách file sheet đang được theo dõi (chỉ admin)."""
    if not is_admin(update):
        await update.message.reply_text("Bạn không có quyền quản lý nguồn theo dõi.")
        return

    args = context.args or []
    sources = list(cfg.get("watch.sources", []) or [])
    state = state_store.load(watch_state_path())

    # --- Liệt kê ---
    if not args:
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
        return

    lenh = args[0].lower()

    # --- Thêm nguồn ---
    if lenh == "them" and len(args) >= 2:
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
        return

    # --- Xem / đổi tab ---
    if lenh == "tab" and len(args) >= 2:
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
        (state.get("sources") or {}).pop(sid, None)
        state_store.save(watch_state_path(), state)
        await update.message.reply_text(
            "Đã đổi tab của “%s” sang “%s”. Sẽ chụp lại ảnh ở lần quét tới."
            % (src.get("name") or sid, tab_moi))
        return

    # --- Xoá nguồn ---
    if lenh == "xoa" and len(args) >= 2:
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
        return

    await update.message.reply_text(
        "Cú pháp:\n"
        "/nguon\n"
        "/nguon them <link> | Tên hiển thị | Tên tab\n"
        "/nguon tab <id> [tên tab]\n"
        "/nguon xoa <id>")


async def cmd_theodoi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bật/tắt nhanh chức năng theo dõi thay đổi (chỉ admin)."""
    if not is_admin(update):
        await update.message.reply_text("Bạn không có quyền đổi cấu hình bot.")
        return
    arg = (context.args[0].lower() if context.args else "")
    if arg in ("bat", "bật", "on", "true"):
        cfg.set("watch.enabled", True)
        register_jobs(context.application)
        await update.message.reply_text("Đã BẬT theo dõi thay đổi.")
    elif arg in ("tat", "tắt", "off", "false"):
        cfg.set("watch.enabled", False)
        register_jobs(context.application)
        await update.message.reply_text("Đã TẮT theo dõi thay đổi.")
    else:
        trang_thai = "BẬT" if cfg.get("watch.enabled", False) else "TẮT"
        await update.message.reply_text(
            "Theo dõi thay đổi đang %s.\nĐổi: /theodoi bat | /theodoi tat" % trang_thai)
```

- [ ] **Step 3: Cho `/cauhinh` nạp lại lịch khi đổi `watch.*` và nhận khoá dạng danh sách**

Sửa `LIST_KEYS`, từ:

```python
LIST_KEYS = {"team.members", "telegram.admin_ids"}
```

thành:

```python
LIST_KEYS = {"team.members", "telegram.admin_ids", "watch.digest_times",
             "watch.active_days", "watch.instant_kinds", "watch.instant_fields",
             "watch.filters.sources", "watch.filters.projects",
             "watch.filters.assignees", "watch.filters.keywords"}
```

Trong `cmd_cauhinh`, sửa nhánh nạp lại, từ:

```python
        if key.startswith("schedules."):
            register_jobs(context.application)
            note = "\nLịch gửi đã được nạp lại."
```

thành:

```python
        if key.startswith("schedules.") or key.startswith("watch."):
            register_jobs(context.application)
            note = "\nLịch gửi đã được nạp lại."
```

Và chặn sửa `watch.sources` bằng `/cauhinh` (dùng `/nguon` cho an toàn) — sửa dòng chặn khoá, từ:

```python
        if key.startswith(("telegram.bot_token", "google_sheets.credentials")):
            await update.message.reply_text("Không cho phép đổi khóa này qua chat.")
            return
```

thành:

```python
        if key.startswith(("telegram.bot_token", "google_sheets.credentials")):
            await update.message.reply_text("Không cho phép đổi khóa này qua chat.")
            return
        if key == "watch.sources":
            await update.message.reply_text(
                "Dùng /nguon them | /nguon xoa để quản lý danh sách file theo dõi.")
            return
```

- [ ] **Step 4: Cập nhật `HELP_TEXT`**

Thêm vào `HELP_TEXT`, ngay sau dòng `/tuan - Tổng kết tuần`:

```
/moi - Thay đổi trên các sheet kế hoạch kể từ bản tin gần nhất
```

Và thêm vào cuối phần lệnh admin (sau dòng `/chatid - ...`):

```
/nguon - Các file sheet kế hoạch đang được theo dõi
/nguon them <link> | Tên hiển thị | Tên tab - Thêm file để theo dõi thay đổi
/nguon tab <id> [tên tab] - Xem hoặc đổi tab đang theo dõi
/nguon xoa <id> - Bỏ theo dõi một file
/theodoi bat | tat - Bật/tắt theo dõi thay đổi
  Cấu hình thêm: /cauhinh set watch.poll_interval_minutes 10
  VD: /cauhinh set watch.active_hours 08:00-18:00
  VD: /cauhinh set watch.digest_times 08:30, 16:30
  VD: /cauhinh set watch.instant_fields due, assignee, status
```

- [ ] **Step 5: Đăng ký handler trong `main()`**

Thêm ngay sau dòng `app.add_handler(CommandHandler("moi", cmd_moi))`:

```python
    app.add_handler(CommandHandler("nguon", cmd_nguon))
    app.add_handler(CommandHandler("theodoi", cmd_theodoi))
```

- [ ] **Step 6: Xác minh bóc link bằng script stub**

```python
# scratchpad/kiem_tra_boc_link.py
import sys, types
for ten in ("gspread", "google", "google.oauth2", "google.oauth2.service_account",
            "pytz", "telegram", "telegram.constants", "telegram.ext"):
    sys.modules.setdefault(ten, types.ModuleType(ten))

import re
SHEET_ID_RE = re.compile(r"/d/([a-zA-Z0-9-_]{20,})")

def _boc(raw):
    raw = (raw or "").strip()
    k = SHEET_ID_RE.search(raw)
    if k:
        return k.group(1)
    return raw if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", raw) else ""

ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
assert _boc("https://docs.google.com/spreadsheets/d/%s/edit#gid=0" % ID) == ID
assert _boc(ID) == ID
assert _boc("linh tinh") == ""
print("OK")
```

```bash
python "C:/Users/LeAnh/AppData/Local/Temp/claude/C--Users-LeAnh-Documents-telegram-report-bot/6620f28f-ea26-4934-acd6-ada4c49cf165/scratchpad/kiem_tra_boc_link.py"
```

Kỳ vọng: `OK`.

- [ ] **Step 7: Kiểm tra cú pháp, test, commit**

```bash
python -m py_compile src/*.py && python -m unittest discover -s tests -t .
git add src/bot.py
git commit -m "feat(watch): lệnh /nguon quản lý file theo dõi, /theodoi bật tắt, mở rộng /cauhinh"
```

---

### Task 11: Tài liệu & rà soát cuối

**Files:**
- Modify: `AGENTS.md`, `MEMORY.md`, `README.md`

**Interfaces:**
- Consumes: toàn bộ Task 1–10.
- Produces: không có code mới.

- [ ] **Step 1: Thêm mục mới vào `AGENTS.md`**

Chèn một mục **"14. Theo dõi thay đổi trên sheet kế hoạch"** ngay trước mục "13. Bẫy cần nhớ", nội dung:

```markdown
## 14. Theo dõi thay đổi trên sheet kế hoạch (`watch.*`)

Nhánh **độc lập** với báo cáo: theo dõi các file sheet kế hoạch do người khác cập nhật,
báo dòng mới / dòng bị xoá / ô bị sửa. Sheet "Task Đã Điều Phối" **không** nằm trong
phạm vi này.

- `change_tracker.py` — nhận diện cột (`detect_mode` → chế độ `task`/`generic`), khoá
  định danh (`make_key`), chụp ảnh (`build_snapshot`), so sánh (`diff_snapshots`), dò đổi
  tên (`match_renames`), phân loại (`classify`), lọc (`passes_filters`), khung giờ
  (`in_active_window`, `is_first_scan_of_day`).
- `change_reporter.py` — dựng HTML (`format_instant`, `format_digest`, `format_overflow`).
- `state_store.py` — `state/watch_state.json`, ghi atomic, chịu được file hỏng.
- `sheets_client.fetch_rows/list_worksheets/service_account_email` — đọc file bất kỳ.
- `bot.py` — `job_watch_scan` (run_repeating), `job_watch_digest` (run_daily),
  `/moi`, `/nguon`, `/theodoi`.

**Ba module đầu KHÔNG được import gspread/telegram/pytz** — đó là điều kiện để
`python -m unittest discover -s tests -t .` chạy được trên máy dev.

Điểm dễ vấp:
- **Khoá định danh không theo vị trí dòng** → sort lại sheet không sinh thông báo. Đừng
  "sửa" thành số dòng.
- **Bộ lọc chỉ chặn ở khâu gửi**, ảnh chụp luôn lưu toàn bộ sheet. Lọc từ đầu sẽ khiến
  việc mở rộng bộ lọc bị hiểu nhầm thành hàng loạt "dòng mới".
- **Chưa có ảnh chụp thì không báo gì** (bootstrap). Bỏ quy tắc này là dội hàng trăm tin.
- `watch.active_days` dùng đúng quy ước PTB `0 = Chủ Nhật`.
- Tin của chức năng này là HTML → luôn `parse_mode=ParseMode.HTML` + `_esc`.
```

- [ ] **Step 2: Thêm mục vào `MEMORY.md`**

Thêm mục 9 vào phần "Quyết định & lý do", và cập nhật dòng "_Cập nhật gần nhất_" thành `2026-07-26`:

```markdown
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
```

Và thêm vào phần "Bẫy đã biết":

```markdown
- **`watch.active_days` cũng theo quy ước `0 = Chủ Nhật`** như `schedules.*`.
- **Mất thư mục `state/`** (quên mount) → bot chụp lại từ đầu và im lặng, không dội tin —
  đúng thiết kế, đừng "sửa".
```

- [ ] **Step 3: Thêm mục hướng dẫn vào `README.md`**

Chèn một mục mới ở cuối phần hướng dẫn sử dụng:

```markdown
## Theo dõi thay đổi trên file kế hoạch

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
```

- [ ] **Step 4: Chạy toàn bộ kiểm tra lần cuối**

```bash
python -m py_compile src/*.py && python -m unittest discover -s tests -t . -v
```

Kỳ vọng: py_compile im lặng; test `OK` — 65 test.

- [ ] **Step 5: Kiểm tra không lỡ tay commit secret**

```bash
git status --short && git log --oneline main..HEAD --stat | head -60
```

Kỳ vọng: **không** thấy `config.yaml`, `credentials.json`, hay `state/` trong danh sách file đã commit.

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md MEMORY.md README.md
git commit -m "docs: hướng dẫn và ghi chú quyết định cho chức năng theo dõi thay đổi"
```

---

## Xác minh thủ công trên bot thật (sau khi merge)

Không tự động hoá được vì cần credentials + mạng. Chạy theo thứ tự:

1. `docker compose up -d --build` → `docker compose logs -f` thấy "Bot đang chạy...".
2. `/nguon them <link một file kế hoạch thật>` → bot trả lời số dòng, tên tab, chế độ, danh sách cột.
3. `/theodoi bat` → `/nguon` thấy nguồn ở trạng thái OK.
4. Sửa một ô hạn trên sheet đó → trong ≤ 10 phút nhận tin báo ngay đúng `cũ → mới`.
5. Sort lại sheet → **không** nhận tin nào.
6. Đổi một ô trạng thái → không có tin ngay; `/moi` thấy nó trong hàng chờ; đến 16:30 nhận bản tin.
7. Bỏ quyền chia sẻ file → sau 3 vòng quét, admin nhận đúng một tin cảnh báo (không lặp).
8. `/baocao`, `/tai`, `/canhan` vẫn chạy như trước.
