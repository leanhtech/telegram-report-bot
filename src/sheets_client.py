# -*- coding: utf-8 -*-
"""Đọc dữ liệu từ Google Sheet 'Task Đã Điều Phối' qua Service Account.

Cấu trúc cột (theo sheet thực tế):
STT | Tên Task | Link Task Jira (Info Liên Quan) | Loại Task | Dự án |
Nhân Sự Thực Hiện | EST (giờ) | Ngày tạo | Hạn | Ngày hoàn thành |
Trạng thái thực hiện | Ghi chú
"""
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

import gspread
from google.oauth2.service_account import Credentials

from .config import cfg

log = logging.getLogger("report-bot.sheets")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

DATE_FORMATS = ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"]


def _col_letter(n: int) -> str:
    """Số cột (1-based) -> chữ cái cột A1: 1->A, 26->Z, 27->AA."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class Task:
    stt: str = ""
    name: str = ""
    jira: str = ""
    task_type: str = ""       # Loại Task
    project: str = ""         # Dự án
    assignee: str = ""        # Nhân Sự Thực Hiện
    est: str = ""
    created: Optional[date] = None    # Ngày tạo
    due: Optional[date] = None        # Hạn
    done_date: Optional[date] = None  # Ngày hoàn thành
    status: str = ""          # Trạng thái thực hiện
    note: str = ""

    @property
    def is_done(self) -> bool:
        return "hoàn thành" in self.status.lower()

    @property
    def is_planned(self) -> bool:
        """Task dự tính giao / chưa giao."""
        s = self.status.lower()
        return "dự tính" in s or "chưa giao" in s

    def active_on(self, day: date) -> bool:
        """Task có được thực hiện trong ngày `day` không."""
        if self.done_date == day:
            return True
        if self.created and self.created > day:
            return False
        if self.is_done:
            # đã hoàn thành trước ngày `day` -> không tính
            return self.done_date is not None and self.done_date >= day
        # chưa hoàn thành: đang thực hiện nếu đã được tạo trước hoặc trong ngày
        return self.created is not None and self.created <= day and not self.is_planned

    def planned_for(self, day: date) -> bool:
        """Task đưa vào phần 'Dự kiến nội dung thực hiện' cho ngày `day`.

        Gồm hai nhóm:
        - Task 'dự tính giao' (chưa có nhân sự / ngày giao / hạn cụ thể).
        - Task 'đang thực hiện' còn hạn trong hoặc sau `day` (mang sang tiếp tục).
        """
        if self.is_done:
            return False
        if self.is_planned:
            # Dự tính giao thường chưa điền ngày; chỉ loại khi ngày tạo ở tương lai.
            return not (self.created and self.created > day)
        # Đang thực hiện: chỉ đưa vào dự kiến nếu còn hạn (due >= day).
        return self.due is not None and self.due >= day


HEADER_MAP = {
    "stt": "stt",
    "tên task": "name",
    "link task jira (info liên quan)": "jira",
    "link task jira": "jira",
    "loại task": "task_type",
    "dự án": "project",
    "nhân sự thực hiện": "assignee",
    "est (giờ)": "est",
    "ngày tạo": "created",
    "hạn": "due",
    "ngày hoàn thành": "done_date",
    "trạng thái thực hiện": "status",
    "ghi chú": "note",
}

DATE_FIELDS = {"created", "due", "done_date"}


class SheetsClient:
    def __init__(self):
        self._cache: List[Task] = []
        self._cache_at: float = 0.0
        self._members: List[str] = []
        self._members_at: float = 0.0
        self._gc = None

    def _client(self):
        if self._gc is None:
            creds = Credentials.from_service_account_file(
                cfg.get("google_sheets.credentials_file", "credentials.json"),
                scopes=SCOPES,
            )
            self._gc = gspread.authorize(creds)
        return self._gc

    def fetch_tasks(self, force: bool = False) -> List[Task]:
        ttl = int(cfg.get("report.cache_seconds", 120))
        if not force and self._cache and (time.time() - self._cache_at) < ttl:
            return self._cache

        sh = self._client().open_by_key(cfg.get("google_sheets.spreadsheet_id"))
        ws = sh.worksheet(cfg.get("google_sheets.worksheet_name", "Task Đã Điều Phối"))
        rows = ws.get_all_values()
        if not rows:
            return []

        headers = [h.strip().lower() for h in rows[0]]
        tasks: List[Task] = []
        for row in rows[1:]:
            if not any(cell.strip() for cell in row):
                continue
            t = Task()
            for idx, header in enumerate(headers):
                value = row[idx].strip() if idx < len(row) else ""
                attr = HEADER_MAP.get(header)
                if not attr:
                    continue
                if attr in DATE_FIELDS:
                    setattr(t, attr, parse_date(value))
                else:
                    setattr(t, attr, value)
            if t.name:
                tasks.append(t)

        self._cache = tasks
        self._cache_at = time.time()
        return tasks

    # ------------------------------------------------------------------
    # Danh sách nhân sự trong team (lấy từ dropdown cột 'Nhân Sự Thực Hiện')
    # ------------------------------------------------------------------
    def fetch_team_members(self, force: bool = False) -> List[str]:
        """Toàn bộ nhân sự trong team.

        Nguồn chính: dropdown (data validation) của cột 'Nhân Sự Thực Hiện'.
        Nếu không đọc được -> fallback sang cfg 'team.members' (nếu có khai báo).
        """
        ttl = int(cfg.get("report.cache_seconds", 120)) * 5  # roster ít thay đổi
        if not force and self._members and (time.time() - self._members_at) < ttl:
            return self._members

        members: List[str] = []
        try:
            members = self._read_dropdown_members()
        except Exception as e:  # đọc dropdown lỗi -> dùng fallback, không làm hỏng /tai
            log.warning("Không đọc được dropdown nhân sự: %s", e)
        if not members:
            members = [str(x).strip() for x in (cfg.get("team.members") or [])
                       if str(x).strip()]

        members = sorted(set(members), key=str.lower)
        if members:
            self._members, self._members_at = members, time.time()
        return members

    def _read_dropdown_members(self) -> List[str]:
        sh = self._client().open_by_key(cfg.get("google_sheets.spreadsheet_id"))
        name = cfg.get("google_sheets.worksheet_name", "Task Đã Điều Phối")
        ws = sh.worksheet(name)
        headers = [h.strip().lower() for h in ws.row_values(1)]
        try:
            col = headers.index("nhân sự thực hiện") + 1
        except ValueError:
            return []
        letter = _col_letter(col)
        meta = sh.fetch_sheet_metadata({
            "ranges": [f"{name}!{letter}2:{letter}500"],
            "fields": "sheets(data(rowData(values(dataValidation))))",
            "includeGridData": "true",
        })
        for sheet in meta.get("sheets", []):
            for data in sheet.get("data", []):
                for row in data.get("rowData", []):
                    for cell in row.get("values", []):
                        vals = self._members_from_validation(cell.get("dataValidation"), sh)
                        if vals:
                            return vals
        return []

    def _members_from_validation(self, dv, sh) -> List[str]:
        """Rút danh sách nhân sự từ một rule data-validation của ô."""
        if not dv:
            return []
        cond = dv.get("condition") or {}
        values = cond.get("values") or []
        ctype = cond.get("type")
        if ctype == "ONE_OF_LIST":
            # Dropdown liệt kê trực tiếp từng giá trị.
            return [v.get("userEnteredValue", "").strip()
                    for v in values if v.get("userEnteredValue", "").strip()]
        if ctype == "ONE_OF_RANGE" and values:
            # Dropdown trỏ tới một vùng -> đọc giá trị trong vùng đó.
            rng = values[0].get("userEnteredValue", "").lstrip("=").strip()
            if not rng:
                return []
            resp = sh.values_get(rng)
            return [str(c).strip() for r in resp.get("values", []) for c in r
                    if str(c).strip()]
        return []


sheets = SheetsClient()
