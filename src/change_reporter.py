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
