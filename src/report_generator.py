# -*- coding: utf-8 -*-
"""Sinh các loại báo cáo cho Telegram.

Báo cáo team dùng HTML (in đậm 2 đầu mục); các báo cáo khác là plain text.

Quy tắc làm sạch tên task:
- Loại bỏ prefix trong ngoặc vuông: [TEST], [KIOSK][APP]_, [HCM iGATE V2],...
- Nếu tên task chưa bắt đầu bằng động từ thì chèn động từ phù hợp
  (Xử lý / Kiểm tra / Thực hiện / Tìm hiểu / Hỗ trợ / Tổng hợp / Báo cáo ...)
"""
import bisect
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from html import escape
from typing import Dict, List

from .config import cfg
from .sheets_client import Task, sheets

# Các động từ phổ biến ở đầu task -> giữ nguyên
LEADING_VERBS = (
    "xử lý", "kiểm tra", "kiểm thử", "thực hiện", "tìm hiểu", "nghiên cứu",
    "hỗ trợ", "tổng hợp", "báo cáo", "trao đổi", "họp", "phối hợp", "rà soát",
    "cập nhật", "bổ sung", "thêm", "xây dựng", "cấu hình", "đồng bộ", "chặn",
    "hướng dẫn", "chuẩn bị", "tối ưu", "điều chỉnh", "đánh giá", "lấy",
    "tập huấn", "triển khai", "viết", "theo dõi", "theo dỗi", "demo", "test",
    "fix", "hiệu chỉnh", "upcode", "lưu trữ", "tích hợp", "đề xuất", "xuất",
)

# Từ khóa -> động từ chèn vào đầu nếu task chưa có động từ
VERB_HINTS = [
    (("lỗi", "bug", "sự cố"), "Xử lý"),
    (("test", "kiểm thử", "testcase"), "Kiểm thử"),
    (("api", "đồng bộ", "tích hợp"), "Thực hiện"),
    (("chức năng", "tính năng", "giao diện", "màn hình"), "Thực hiện"),
    (("báo cáo", "sheet", "số liệu", "thống kê"), "Tổng hợp"),
    (("tài liệu", "phương án", "pa "), "Xây dựng"),
]

BRACKET_PREFIX_RE = re.compile(r"^(\s*\[[^\]]*\]\s*[_\-–:]?\s*)+")


def _lower_first(text: str) -> str:
    """Hạ chữ cái đầu, trừ khi từ đầu là từ viết tắt (VTU, API, PA...)."""
    first_word = text.split(" ", 1)[0]
    if len(first_word) > 1 and first_word.isupper():
        return text
    return text[0].lower() + text[1:]


def clean_task_name(name: str) -> str:
    text = " ".join((name or "").split())
    if cfg.get("report.strip_bracket_prefixes", True):
        text = BRACKET_PREFIX_RE.sub("", text).strip()
        text = text.lstrip("_-–: ").strip()
    if not text:
        return name.strip()

    # Task dạng "Đơn vị/Địa danh - Hành động" -> đảo thành "Hành động (Đơn vị)"
    # VD: "Phường Tam Bình - Điều chỉnh ngày hẹn trả"
    #  -> "Điều chỉnh ngày hẹn trả (Phường Tam Bình)"
    if " - " in text:
        head, tail = text.split(" - ", 1)
        if tail.strip().lower().startswith(LEADING_VERBS) \
                and not head.strip().lower().startswith(LEADING_VERBS):
            text = f"{tail.strip()} ({head.strip()})"

    lower = text.lower()
    if not lower.startswith(LEADING_VERBS):
        verb = "Thực hiện"
        for keywords, v in VERB_HINTS:
            if any(k in lower for k in keywords):
                verb = v
                break
        text = f"{verb} {_lower_first(text)}"

    return text[0].upper() + text[1:]


def _dedupe(lines: List[str]) -> List[str]:
    seen, out = set(), []
    for line in lines:
        key = line.lower()
        if key not in seen:
            seen.add(key)
            out.append(line)
    return out


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%y")


def _split_by_project(tasks: List[Task]):
    kiosk_name = cfg.get("report.kiosk_project_name", "Kiosk").lower()
    kiosk = [t for t in tasks if t.project.strip().lower() == kiosk_name]
    others = [t for t in tasks if t.project.strip().lower() != kiosk_name]
    return kiosk, others


def _next_workday(day: date) -> date:
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:  # bỏ T7, CN
        nxt += timedelta(days=1)
    return nxt


def _lines_for(today_tasks: List[Task], tomorrow_tasks: List[Task]):
    """Sinh (today_lines, tomorrow_lines) đã làm sạch tên + khử trùng lặp.

    Task 'đang thực hiện' mang sang phần dự kiến -> thêm tiền tố 'Tiếp tục'.
    Task 'dự tính giao' là việc mới nên giữ nguyên tên.
    """
    today_lines = _dedupe([clean_task_name(t.name) for t in today_tasks])
    tomorrow_lines = []
    for t in tomorrow_tasks:
        line = clean_task_name(t.name)
        if not t.is_planned:  # đang thực hiện, mang sang tiếp tục
            line = f"Tiếp tục {line[0].lower()}{line[1:]}"
        tomorrow_lines.append(line)
    return today_lines, _dedupe(tomorrow_lines)


def _esc(s) -> str:
    """Escape ký tự đặc biệt cho Telegram HTML (& < >)."""
    return escape(str(s), quote=False)


def _report_header(title: str, today: date) -> str:
    return f"📋 <b>{_esc(title)} ngày {_fmt(today)}:</b>"


def _plan_header(tomorrow: date) -> str:
    return f"🗓️ <b>Dự kiến nội dung thực hiện ngày {_fmt(tomorrow)}:</b>"


def _flat_report(title, today, tomorrow, today_tasks, tomorrow_tasks) -> str:
    """Báo cáo một danh sách phẳng (dùng cho dự án đơn như Kiosk)."""
    today_lines, tomorrow_lines = _lines_for(today_tasks, tomorrow_tasks)
    parts = [_report_header(title, today)]
    parts += [f"- {_esc(l)}" for l in today_lines] or ["- Không có công việc phát sinh"]
    parts.append("")
    parts.append(_plan_header(tomorrow))
    parts += [f"- {_esc(l)}" for l in tomorrow_lines] or ["- Chưa có kế hoạch"]
    return "\n".join(parts)


_NO_PROJECT = "(Chưa phân loại dự án)"


def _project_name(t: Task) -> str:
    return t.project.strip() or _NO_PROJECT


def _grouped_report(title, today, tomorrow, today_tasks, tomorrow_tasks) -> str:
    """Báo cáo gom nội dung theo từng dự án (cho nhóm 'các dự án khác')."""
    today_by_proj, tomorrow_by_proj = defaultdict(list), defaultdict(list)
    for t in today_tasks:
        today_by_proj[_project_name(t)].append(t)
    for t in tomorrow_tasks:
        tomorrow_by_proj[_project_name(t)].append(t)

    # Sắp theo tên; nhóm chưa phân loại luôn xuống cuối.
    projects = sorted(
        set(today_by_proj) | set(tomorrow_by_proj),
        key=lambda p: (p == _NO_PROJECT, p.lower()),
    )
    today_lines, tomorrow_lines = {}, {}
    for p in projects:
        today_lines[p], tomorrow_lines[p] = _lines_for(
            today_by_proj.get(p, []), tomorrow_by_proj.get(p, [])
        )

    def render_section(header: str, lines_by_proj, empty_msg: str):
        block, has_content = [header], False
        for p in projects:
            lines = lines_by_proj[p]
            if not lines:
                continue
            has_content = True
            block.append("")
            block.append(f"📁 {_esc(p)}:")
            block += [f"- {_esc(l)}" for l in lines]
        if not has_content:
            block.append(empty_msg)
        return block

    parts = render_section(
        _report_header(title, today), today_lines, "- Không có công việc phát sinh"
    )
    parts.append("")
    parts += render_section(
        _plan_header(tomorrow), tomorrow_lines, "- Chưa có kế hoạch",
    )
    return "\n".join(parts)


def build_daily_team_reports(today: date) -> Dict[str, str]:
    """Trả về {'kiosk': text, 'others': text}.

    - 'kiosk': một dự án -> danh sách phẳng.
    - 'others': gom nội dung theo từng dự án cho dễ đọc.
    """
    tasks = sheets.fetch_tasks()
    tomorrow = _next_workday(today)
    today_tasks = [t for t in tasks if t.active_on(today)]
    tomorrow_tasks = [t for t in tasks if t.planned_for(tomorrow)]

    kiosk_today, others_today = _split_by_project(today_tasks)
    kiosk_tomorrow, others_tomorrow = _split_by_project(tomorrow_tasks)

    return {
        "kiosk": _flat_report(
            cfg.get("report.kiosk_report_title"), today, tomorrow,
            kiosk_today, kiosk_tomorrow,
        ),
        "others": _grouped_report(
            cfg.get("report.other_report_title"), today, tomorrow,
            others_today, others_tomorrow,
        ),
    }


def build_personal_report(today: date) -> str:
    """Báo cáo công việc từng cá nhân trong ngày, gửi riêng cho quản lý."""
    tasks = [t for t in sheets.fetch_tasks() if t.active_on(today)]
    by_person: Dict[str, List[Task]] = defaultdict(list)
    for t in tasks:
        name = t.assignee.strip() or "(Chưa phân công)"
        by_person[name].append(t)

    parts = [f"Báo cáo công việc cá nhân ngày {_fmt(today)}:"]
    for person in sorted(by_person):
        done = [t for t in by_person[person] if t.done_date == today]
        doing = [t for t in by_person[person] if t not in done]
        parts.append("")
        parts.append(f"{person}:")
        for t in done:
            parts.append(f"- [Hoàn thành] {clean_task_name(t.name)}")
        for t in doing:
            due = f" (hạn {_fmt(t.due)})" if t.due else ""
            parts.append(f"- [Đang thực hiện] {clean_task_name(t.name)}{due}")
    if len(parts) == 1:
        parts.append("- Không có dữ liệu công việc hôm nay")
    return "\n".join(parts)


def build_deadline_alert(today: date) -> str:
    """Cảnh báo task trễ hạn và task đến hạn hôm nay."""
    tasks = sheets.fetch_tasks()
    overdue = [t for t in tasks if not t.is_done and t.due and t.due < today
               and not t.is_planned]
    due_today = [t for t in tasks if not t.is_done and t.due == today]

    if not overdue and not due_today:
        return ""

    parts = [f"Cảnh báo tiến độ ngày {_fmt(today)}:"]
    if overdue:
        parts.append("")
        parts.append("Task TRỄ HẠN:")
        for t in sorted(overdue, key=lambda x: x.due):
            parts.append(f"- {clean_task_name(t.name)} | {t.assignee} | hạn {_fmt(t.due)}")
    if due_today:
        parts.append("")
        parts.append("Task đến hạn HÔM NAY:")
        for t in due_today:
            parts.append(f"- {clean_task_name(t.name)} | {t.assignee}")
    return "\n".join(parts)


def build_weekly_summary(today: date) -> str:
    """Tổng kết tuần: số task hoàn thành / trễ hạn / đang thực hiện theo dự án và cá nhân."""
    start = today - timedelta(days=today.weekday())  # thứ 2 tuần này
    tasks = sheets.fetch_tasks()
    week_tasks = [t for t in tasks if (t.done_date and start <= t.done_date <= today)
                  or (t.created and start <= t.created <= today)]

    by_project = defaultdict(lambda: [0, 0, 0])   # done, doing, late
    by_person = defaultdict(lambda: [0, 0])       # done, doing
    for t in week_tasks:
        p = t.project or "(Khác)"
        a = t.assignee or "(Chưa phân công)"
        if t.is_done:
            by_project[p][0] += 1
            by_person[a][0] += 1
            if "trễ hạn" in t.status.lower():
                by_project[p][2] += 1
        else:
            by_project[p][1] += 1
            by_person[a][1] += 1

    parts = [f"Tổng kết tuần ({_fmt(start)} - {_fmt(today)}):", "", "Theo dự án:"]
    for p, (done, doing, late) in sorted(by_project.items()):
        late_txt = f", {late} trễ hạn" if late else ""
        parts.append(f"- {p}: {done} hoàn thành, {doing} đang thực hiện{late_txt}")
    parts.append("")
    parts.append("Theo nhân sự:")
    for a, (done, doing) in sorted(by_person.items()):
        parts.append(f"- {a}: {done} hoàn thành, {doing} đang thực hiện")
    return "\n".join(parts)


_UNASSIGNED = "(Chưa phân công)"


def _parse_hours(raw) -> float:
    """Lấy số giờ từ cột EST: '8', '8h', '1,5 giờ' -> float. Không đọc được -> 0."""
    s = str(raw or "").strip().replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else 0.0


def _workdays_between(start: date, end: date) -> int:
    """Số ngày làm việc (T2–T6) trong [start, end] tính cả 2 đầu, tối thiểu 1."""
    if end < start:
        start, end = end, start
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return max(n, 1)


def _water_fill(load: List[float], days: List[int], est: float, cap: float) -> None:
    """Rải `est` giờ vào các ngày `days`, lấp ngày đang tải thấp trước, trần `cap`/ngày.

    Nhờ vậy, giờ của một task KHÔNG bị chia đều một cách máy móc: ngày nào đã (gần)
    đầy vì task khác thì phần giờ tự tràn sang ngày còn trống. Khi mọi ngày trong cửa
    sổ đều chạm trần mà vẫn dư -> chia đều phần dư (quá tải thực sự) cho các ngày.
    """
    EPS = 1e-9
    remaining = est
    while remaining > EPS:
        avail = [d for d in days if load[d] < cap - EPS]
        if not avail:  # hết chỗ trống -> quá tải, chia đều phần dư
            share = remaining / len(days)
            for d in days:
                load[d] += share
            return
        base = min(load[d] for d in avail)
        higher = [load[d] for d in avail if load[d] > base + EPS]
        ceil_level = min(min(higher) if higher else cap, cap)
        lowest = [d for d in avail if load[d] <= base + EPS]
        step_total = (ceil_level - base) * len(lowest)
        if step_total <= remaining - EPS:
            for d in lowest:
                load[d] = ceil_level
            remaining -= step_total
        else:  # phần còn lại không đủ nâng hết -> chia đều cho các ngày thấp nhất
            add = remaining / len(lowest)
            for d in lowest:
                load[d] += add
            return


_PAST_LOOKBACK_DAYS = 60      # giới hạn nhìn lại quá khứ khi dựng lưới ngày
_FUTURE_LOOKAHEAD_DAYS = 365  # giới hạn nhìn tới tương lai


def _workday_list(start: date, end: date) -> List[date]:
    """Các ngày làm việc (T2–T6) trong [start, end]."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _person_hours_today(tasks: List[Task], today: date, capacity: float) -> float:
    """Giờ công việc rơi vào HÔM NAY của một người, mô phỏng theo sức chứa từng ngày.

    `tasks` phải là TẤT CẢ task của người đó (kể cả đã hoàn thành) thì mới dựng đúng
    mức bận của những ngày đã qua.

    Nguyên tắc:
    - **Ngày đã qua** trong khoảng của task dài ngày coi như đã được làm hết mức sức
      chứa còn trống hôm đó; chỉ phần EST *còn lại* mới rải cho hôm nay + tương lai.
      VD task tạo T2, hạn T4, EST 6h, chuẩn 8h/ngày — T2 đã kín 8h -> còn 6h chia đều
      T3 & T4 (3h/ngày); T2 mới dùng 4h -> T2 "ăn" 4h, còn 2h chia T3 & T4 (1h/ngày).
    - **Hôm nay + tương lai**: rải cân bằng theo sức chứa (water-filling) — ngày đã đầy
      thì tràn sang ngày trống.
    - Task **đã hoàn thành** chiếm chỗ các ngày [ngày tạo .. ngày hoàn thành].
    - Task **quá hạn** chưa xong -> dồn vào hôm nay. Task **không hạn** -> rải
      ~capacity giờ/ngày. T7/CN hoặc task chưa bắt đầu -> không tính.
    """
    if today.weekday() >= 5:
        return 0.0
    cap = capacity if capacity > 0 else 8.0
    lo = today - timedelta(days=_PAST_LOOKBACK_DAYS)
    hi = today + timedelta(days=_FUTURE_LOOKAHEAD_DAYS)

    entries = []  # (ưu tiên, mốc sắp xếp, est, start, end, mode)
    for t in tasks:
        est = _parse_hours(t.est)
        if est <= 0:
            continue
        if t.is_done:
            end = t.done_date
            if end is None or end > today or end < lo:
                continue                               # không rõ/không hợp lệ
            start, prio, mode = (t.created or end), 0, "done"
        elif t.created and t.created > today:
            continue                                   # chưa bắt đầu
        elif t.due is not None and t.due < today:
            start = end = today                        # quá hạn -> dồn hôm nay
            prio, mode = 1, "open"
        elif t.due is None:
            start = end = today                        # cửa sổ mở rộng bên dưới
            prio, mode = 2, "nodue"
        else:
            start, end = (t.created or today), t.due
            prio, mode = 1, "open"
        start, end = max(start, lo), min(end, hi)
        if end < start:
            end = start
        entries.append((prio, end, est, start, end, mode))
    if not entries:
        return 0.0

    # Lưới ngày làm việc; chừa thêm chỗ cho task không hạn rải ~capacity giờ/ngày
    extra = max((math.ceil(e[2] / cap) for e in entries if e[5] == "nodue"), default=0)
    grid_start = min(min(e[3] for e in entries), today)
    grid_end = max(max(e[4] for e in entries), today) + timedelta(days=extra * 2 + 7)
    days = _workday_list(grid_start, grid_end)
    today_idx = bisect.bisect_left(days, today)
    if today_idx >= len(days) or days[today_idx] != today:
        return 0.0
    last = len(days) - 1

    load = [0.0] * len(days)
    for _, _, est, start, end, mode in sorted(entries, key=lambda e: (e[0], e[1])):
        if mode == "nodue":
            s = today_idx
            e_idx = min(today_idx + max(1, math.ceil(est / cap)) - 1, last)
        else:
            s = min(max(bisect.bisect_left(days, start), 0), last)
            e_idx = min(max(bisect.bisect_right(days, end) - 1, s), last)
        window = list(range(s, e_idx + 1))
        remaining = est

        # Ngày đã qua (task đã xong thì tính cả ngày hoàn thành): lấp tối đa chỗ trống
        greedy = window if mode == "done" else [i for i in window if i < today_idx]
        for i in greedy:
            if remaining <= 1e-9:
                break
            free = cap - load[i]
            if free > 0:
                take = min(free, remaining)
                load[i] += take
                remaining -= take
        if remaining <= 1e-9:
            continue

        # Phần còn lại: rải cân bằng cho hôm nay + tương lai
        rest = window if mode == "done" else [i for i in window if i >= today_idx]
        if rest:
            _water_fill(load, rest, remaining, cap)
        else:
            load[today_idx] += remaining
    return load[today_idx]


def _hnum(x: float) -> str:
    """Hiển thị số giờ gọn: bỏ phần .0 nếu tròn (8.0 -> 8, 2.5 -> 2.5)."""
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _load_badge(hours: float, capacity: float, unassigned: bool) -> str:
    if unassigned:
        return "🗂 cần phân công"
    if hours <= 0:
        return "🟢 trống — giao thêm được"
    if hours <= capacity * 0.5:
        return "🟢 nhẹ tải — giao thêm được"
    if hours <= capacity:
        return "🟡 vừa tải"
    return "🔴 quá tải"


def build_workload_report(today: date) -> str:
    """Tải công việc theo nhân sự (task chưa hoàn thành ở thời điểm hiện tại).

    Phân loại theo hạn (tồn từ trước / đến hạn hôm nay / chưa đến hạn / không hạn)
    và ước tính số giờ dự kiến làm hôm nay để thấy ai nhẹ tải / ai quá tải.
    """
    all_tasks = sheets.fetch_tasks()
    tasks = [t for t in all_tasks if not t.is_done]
    capacity = _parse_hours(cfg.get("report.daily_capacity_hours", 8)) or 8.0

    by_person = defaultdict(list)
    for t in tasks:
        by_person[t.assignee.strip() or _UNASSIGNED].append(t)
    # Tính giờ cần cả task đã hoàn thành để biết những ngày đã qua bận đến đâu
    all_by_person = defaultdict(list)
    for t in all_tasks:
        all_by_person[t.assignee.strip() or _UNASSIGNED].append(t)

    stats = {}
    for name, ts in by_person.items():
        stats[name] = {
            "count": len(ts),
            "overdue": sum(1 for t in ts if t.due and t.due < today),
            "due_today": sum(1 for t in ts if t.due == today),
            "upcoming": sum(1 for t in ts if t.due and t.due > today),
            "no_due": sum(1 for t in ts if not t.due),
            "hours": _person_hours_today(all_by_person[name], today, capacity),
        }

    # Quá tải lên đầu (giờ giảm dần); nhóm chưa phân công xuống cuối.
    order = sorted(
        stats,
        key=lambda n: (n == _UNASSIGNED, -stats[n]["hours"], n.lower()),
    )

    total_tasks = sum(s["count"] for s in stats.values())
    total_hours = sum(s["hours"] for s in stats.values())
    lines = [
        f"📊 <b>Tải công việc theo nhân sự — {_fmt(today)}</b>",
        f"Tổng {total_tasks} task chưa xong · ~{_hnum(total_hours)}h dự kiến hôm nay "
        f"· mức chuẩn {_hnum(capacity)}h/người",
    ]
    for name in order:
        s = stats[name]
        badge = _load_badge(s["hours"], capacity, name == _UNASSIGNED)
        lines.append("")
        lines.append(f"👤 <b>{_esc(name)}</b>")
        lines.append(f"   • Số task chưa xong: {s['count']}")
        lines.append(f"   • Giờ dự kiến hôm nay: ~{_hnum(s['hours'])}h")
        lines.append(f"   • Tình trạng: {badge}")
        lines.append(f"   • Tồn từ trước: {s['overdue']}")
        lines.append(f"   • Đến hạn hôm nay: {s['due_today']}")
        lines.append(f"   • Chưa đến hạn: {s['upcoming']}")
        if s["no_due"]:
            lines.append(f"   • Không hạn: {s['no_due']}")

    if total_tasks == 0:
        lines.append("")
        lines.append("Không có task nào đang mở.")

    # Nhân sự trong team chưa được giao task nào đang mở (còn trống, giao thêm được)
    roster = sheets.fetch_team_members()
    if roster:
        assigned = {t.assignee.strip().lower() for t in tasks if t.assignee.strip()}
        idle = [m for m in roster if m.strip().lower() not in assigned]
        lines.append("")
        if idle:
            lines.append(f"🆓 <b>Chưa được giao task ({len(idle)}):</b>")
            lines += [f"   • {_esc(m)}" for m in idle]
        else:
            lines.append("🆓 <b>Chưa được giao task:</b> không có — cả team đều có việc")
    else:
        lines.append("")
        lines.append(
            "🆓 <i>Chưa lấy được danh sách nhân sự (kiểm tra dropdown cột "
            "'Nhân Sự Thực Hiện' hoặc khai báo team.members trong cấu hình).</i>"
        )
    return "\n".join(lines)


def search_progress(keyword: str, limit: int = 8) -> str:
    """Tra cứu tiến độ task theo từ khóa (tên task, nhân sự, dự án)."""
    kw = keyword.strip().lower()
    if not kw:
        return "Vui lòng nhập từ khóa. Ví dụ: /tiendo kiosk mic"

    words = kw.split()
    matches = []
    for t in sheets.fetch_tasks():
        haystack = f"{t.name} {t.assignee} {t.project} {t.note}".lower()
        if all(w in haystack for w in words):
            matches.append(t)

    if not matches:
        return f"Không tìm thấy task nào khớp với: {keyword}"

    # Ưu tiên task chưa hoàn thành, mới nhất
    matches.sort(key=lambda t: (t.is_done, -(t.created.toordinal() if t.created else 0)))
    header = f"🔎 Tìm thấy {len(matches)} task khớp \"{keyword}\""
    if len(matches) > limit:
        header += f" (hiển thị {limit} task mới nhất)"
    parts = [header]
    for t in matches[:limit]:
        parts.append("")
        parts.append("━━━━━━━━━━━━━━━━━━━━")
        parts.append(f"📌 {clean_task_name(t.name)}")
        if t.project:
            parts.append(f"📁 Dự án: {t.project}")
        parts.append(f"📊 Trạng thái: {t.status or 'Chưa cập nhật'}")
        if t.assignee:
            parts.append(f"👤 Người thực hiện: {t.assignee}")
        if t.due:
            parts.append(f"⏰ Hạn: {_fmt(t.due)}")
        if t.done_date:
            parts.append(f"✅ Hoàn thành: {_fmt(t.done_date)}")
        if t.jira:
            parts.append(f"🔗 Info liên quan: {t.jira}")
        if t.note:
            parts.append("📝 Tiến độ thực hiện:")
            parts.append(_format_note(t.note))
    return "\n".join(parts).rstrip()


def _format_note(note: str, max_len: int = 800) -> str:
    """Trình bày ghi chú tiến độ: mỗi bước một dòng có gạch đầu dòng."""
    truncated = len(note) > max_len
    if truncated:
        note = note[:max_len].rstrip()
    lines = []
    for line in note.split("\n"):
        line = line.strip().lstrip("-+•* ").strip()
        if line:
            lines.append(f"   • {line}")
    if truncated:
        lines.append("   … (ghi chú dài, xem đầy đủ trên sheet)")
    return "\n".join(lines)
