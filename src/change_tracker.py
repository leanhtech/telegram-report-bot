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


# ------------------------------------------------------------------
# Dò đổi tên: ghép cặp một dòng "mất" với một dòng "thêm"
# ------------------------------------------------------------------
RENAME_CELLS_RATIO = 0.7   # tỉ lệ ô giống nhau tối thiểu
RENAME_LABEL_RATIO = 0.6   # độ giống của nhãn khi các ô khác đủ giống nhau
RENAME_OTHERS_RATIO = 0.5   # tỉ lệ tối thiểu các ô ngoài nhãn còn trùng nhau


def _cells_ratio(a: Dict[str, str], b: Dict[str, str]) -> float:
    """Tính tỉ lệ các ô có giá trị giống nhau giữa hai bộ cells."""
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
            ty_le_o_khac = _cells_ratio(_drop_label(cu.cells, cu.label),
                                        _drop_label(moi.cells, moi.label))
            if ty_le_o >= RENAME_CELLS_RATIO or (
                    ty_le_nhan >= RENAME_LABEL_RATIO and ty_le_o_khac >= RENAME_OTHERS_RATIO):
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


def for_digest(changes: List[Change], target_gets_instant: bool) -> Tuple[List[Change], int]:
    """Các thay đổi cần đưa vào bản tin của một đích + số mục đích đó đã nhận trực tiếp.

    Đích có nhận tin báo ngay thì bản tin chỉ nhắc lại phần chưa báo. Đích chỉ
    nhận bản tin thì phải thấy TẤT CẢ, vì nó không hề nhận tin báo ngay nào.
    """
    if not target_gets_instant:
        return list(changes), 0
    con_lai = [c for c in changes if not c.instant_sent]
    return con_lai, len(changes) - len(con_lai)


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
