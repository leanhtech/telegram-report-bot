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

    # File có thể bị sửa tay sai kiểu (VD "sources" thành chuỗi) — vẫn qua
    # được kiểm tra version ở trên. Nếu không chặn ở đây, chỗ dùng state sau
    # này (VD state.setdefault("sources", {})[sid] = ...) sẽ ném TypeError từ
    # ngoài phạm vi try/except của từng nguồn, làm hỏng cả lần quét (spec mục 10).
    if not isinstance(base.get("sources"), dict):
        log.warning("Trường 'sources' trong file trạng thái sai kiểu, dùng giá trị mặc định")
        base["sources"] = {}
    if not isinstance(base.get("pending"), list):
        log.warning("Trường 'pending' trong file trạng thái sai kiểu, dùng giá trị mặc định")
        base["pending"] = []
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
