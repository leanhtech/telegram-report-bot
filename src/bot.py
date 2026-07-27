# -*- coding: utf-8 -*-
"""Telegram Report Bot - Báo cáo công việc tự động từ Google Sheets.

Chạy: python -m src.bot
"""
import logging
from datetime import date, datetime, time as dtime

import pytz
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
)

from .config import cfg
from . import change_reporter as cr
from . import change_tracker as ct
from . import report_generator as rg
from . import state_store
from .sheets_client import sheets

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("report-bot")

MAX_LEN = 4000  # Telegram giới hạn 4096 ký tự / tin nhắn
WATCH_STATE_FILE = "state/watch_state.json"   # ghi đè bằng watch.state_file


def tz():
    return pytz.timezone(cfg.timezone)


def today() -> date:
    return datetime.now(tz()).date()


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


def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in cfg.admin_ids


async def send_long(bot, chat_id, text, topic_id=None, parse_mode=None):
    """Gửi tin nhắn dài, tự cắt theo dòng nếu vượt giới hạn Telegram."""
    if not text:
        return
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX_LEN:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    chunks.append(current)
    for chunk in chunks:
        await bot.send_message(
            chat_id=chat_id, text=chunk,
            message_thread_id=topic_id if topic_id else None,
            parse_mode=parse_mode,
        )


# ============================================================
# JOB TỰ ĐỘNG (SCHEDULED)
# ============================================================
async def job_team_report(context: ContextTypes.DEFAULT_TYPE):
    sched = cfg.get("schedules.team_report", {})
    reports = rg.build_daily_team_reports(today())
    chat_id, topic_id = sched.get("chat_id"), sched.get("topic_id")
    # Báo cáo Kiosk gửi riêng nếu có kiosk_chat_id / kiosk_topic_id,
    # không cấu hình thì gửi chung vào nhóm team_report như mặc định
    if sched.get("kiosk_chat_id") or sched.get("kiosk_topic_id"):
        kiosk_chat = sched.get("kiosk_chat_id") or chat_id
        kiosk_topic = sched.get("kiosk_topic_id")
    else:
        kiosk_chat, kiosk_topic = chat_id, topic_id
    await send_long(context.bot, kiosk_chat, reports["kiosk"], kiosk_topic,
                    parse_mode=ParseMode.HTML)
    await send_long(context.bot, chat_id, reports["others"], topic_id,
                    parse_mode=ParseMode.HTML)
    log.info("Đã gửi báo cáo team (kiosk -> %s)", kiosk_chat)


async def job_personal_report(context: ContextTypes.DEFAULT_TYPE):
    sched = cfg.get("schedules.personal_report", {})
    text = rg.build_personal_report(today())
    await send_long(context.bot, sched.get("chat_id"), text)
    log.info("Đã gửi báo cáo cá nhân")


async def job_deadline_alert(context: ContextTypes.DEFAULT_TYPE):
    sched = cfg.get("schedules.deadline_alert", {})
    text = rg.build_deadline_alert(today())
    if text:
        await send_long(context.bot, sched.get("chat_id"), text)
        log.info("Đã gửi cảnh báo deadline")


async def job_weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    sched = cfg.get("schedules.weekly_summary", {})
    text = rg.build_weekly_summary(today())
    await send_long(context.bot, sched.get("chat_id"), text, sched.get("topic_id"))
    log.info("Đã gửi tổng kết tuần")


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
    # Bọc try quanh toàn bộ quá trình đọc + dựng ảnh chụp + so khớp: nếu bất
    # kỳ bước nào lỗi (kể cả dữ liệu sheet bất thường khiến detect_mode/
    # build_snapshot/diff_snapshots/match_renames raise), coi như cả lần quét
    # nguồn này thất bại và KHÔNG động vào `state` — để vòng sau thử lại từ
    # ảnh chụp cũ, thay vì lỡ ghi đè ảnh chụp dở dang.
    try:
        headers, rows = sheets.fetch_rows(src.get("spreadsheet_id"),
                                          src.get("worksheet_name") or "")

        mode, field_map = ct.detect_mode(headers, src.get("columns"))
        snapshot = ct.build_snapshot(rows, headers, field_map, mode,
                                     src.get("key_column", "") or "")
        # Giữ nguyên error/fail_count của lần trước: việc xoá cờ lỗi (và báo
        # "đã khôi phục") là của _bao_loi_nguon, không phải của hàm này.
        hien_tai = {
            "mode": mode, "headers": headers, "field_map": field_map,
            "snapshot": snapshot, "scanned_at": now.isoformat(),
            "rows": len(snapshot), "error": truoc.get("error"),
            "fail_count": truoc.get("fail_count", 0),
        }

        changes = []
        if truoc.get("snapshot"):
            changes = ct.match_renames(ct.diff_snapshots(truoc, hien_tai, sid))
        else:
            log.info("Nguồn %s: chụp ảnh lần đầu (%d dòng), chưa báo gì", sid, len(snapshot))
    except Exception as e:   # một nguồn hỏng không được làm chết cả job
        return [], e

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
    if info.get("error"):
        return      # đã báo rồi, không nhắc lại mỗi 10 phút
    if info["fail_count"] < 3:
        # Lỗi mạng/quota tạm thời: im lặng thử lại vòng sau.
        log.warning("Nguồn %s lỗi lần %d: %s", sid, info["fail_count"], err)
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

    # Gửi trước, lưu sau: nếu gửi hỏng thì hạ cờ instant_sent để các thay đổi đó
    # rơi vào bản tin gom, không biến mất trong im lặng.
    ngay = [c for c in moi if c.instant_sent]
    if ngay:
        try:
            await _send_watch(context, "instant", ngay, field_maps, now)
            log.info("Đã báo ngay %d thay đổi", len(ngay))
        except Exception as e:
            log.warning("Gửi tin báo ngay thất bại, chuyển sang bản tin gom: %s", e)
            for ch in ngay:
                ch.instant_sent = False

    state.setdefault("pending", []).extend(c.to_dict() for c in moi)
    state["last_scan_at"] = now.isoformat()
    state_store.save(watch_state_path(), state)


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


JOBS = {
    "team_report": job_team_report,
    "personal_report": job_personal_report,
    "deadline_alert": job_deadline_alert,
    "weekly_summary": job_weekly_summary,
}


def register_jobs(app: Application):
    """Đăng ký lại toàn bộ job theo config hiện tại."""
    for job in app.job_queue.jobs():
        job.schedule_removal()

    for name, callback in JOBS.items():
        sched = cfg.get(f"schedules.{name}", {}) or {}
        if not sched.get("enabled"):
            continue
        try:
            hh, mm = map(int, str(sched.get("time", "17:00")).split(":"))
        except ValueError:
            log.warning("Giờ không hợp lệ cho %s, bỏ qua", name)
            continue
        # PTB >=20: 0=Chủ Nhật ... 6=Thứ Bảy. [1..5] = Thứ Hai -> Thứ Sáu.
        days = tuple(sched.get("days", [1, 2, 3, 4, 5]))
        app.job_queue.run_daily(
            callback, time=dtime(hh, mm, tzinfo=tz()), days=days, name=name,
        )
        log.info("Đã lên lịch %s lúc %02d:%02d các ngày %s", name, hh, mm, days)

    register_watch_jobs(app)


def register_watch_jobs(app: Application):
    """Job quét định kỳ cho chức năng theo dõi thay đổi."""
    if not cfg.get("watch.enabled", False):
        return
    phut = max(1, int(cfg.get("watch.poll_interval_minutes", 10) or 10))
    app.job_queue.run_repeating(job_watch_scan, interval=phut * 60, first=30,
                                name="watch_scan")
    log.info("Đã lên lịch quét thay đổi mỗi %d phút", phut)

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


# ============================================================
# COMMAND HANDLERS
# ============================================================
HELP_TEXT = """Danh sách lệnh:

/baocao - Gửi ngay báo cáo ngày (Kiosk + các dự án)
/baocao kiosk - Chỉ báo cáo Kiosk
/baocao duan - Chỉ báo cáo các dự án khác
/canhan - Báo cáo công việc từng cá nhân hôm nay
/tiendo <từ khóa> - Tra cứu tiến độ task (VD: /tiendo đồng bộ học sinh)
/trehan - Danh sách task trễ hạn / đến hạn hôm nay
/tai - Tải công việc theo nhân sự (ai nhẹ tải / ai quá tải)
/tuan - Tổng kết tuần
/thanhvien <tên> - Công việc hôm nay của một người (VD: /thanhvien Thái)
/lamMoi - Xóa cache, đọc lại dữ liệu mới nhất từ sheet

Lệnh cấu hình (chỉ admin):
/cauhinh - Xem cấu hình hiện tại
/cauhinh set <khóa> <giá trị> - Cập nhật cấu hình
  VD: /cauhinh set schedules.team_report.time 17:15
  VD: /cauhinh set schedules.team_report.chat_id -1001234567890
  VD: /cauhinh set schedules.team_report.topic_id 45
  VD: /cauhinh set schedules.personal_report.enabled false
  Gửi riêng báo cáo Kiosk sang group/topic khác (không đặt thì gửi chung team_report):
  VD: /cauhinh set schedules.team_report.kiosk_chat_id -1009876543210
  VD: /cauhinh set schedules.team_report.kiosk_topic_id 12
  Bỏ gửi riêng: /cauhinh set schedules.team_report.kiosk_chat_id null
  Khai báo nhân sự cho /tai (khi không đọc được dropdown):
  VD: /cauhinh set team.members Thái, Nam, Lan, Hùng
/chatid - Hiện chat_id và topic_id của cuộc trò chuyện hiện tại"""


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Xin chào! Tôi là bot báo cáo công việc của team.\n\n" + HELP_TEXT
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def cmd_baocao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    which = (context.args[0].lower() if context.args else "all")
    reports = rg.build_daily_team_reports(today())
    chat_id = update.effective_chat.id
    topic_id = update.message.message_thread_id
    if which in ("all", "kiosk"):
        await send_long(context.bot, chat_id, reports["kiosk"], topic_id,
                        parse_mode=ParseMode.HTML)
    if which in ("all", "duan", "khac"):
        await send_long(context.bot, chat_id, reports["others"], topic_id,
                        parse_mode=ParseMode.HTML)


async def cmd_canhan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = rg.build_personal_report(today())
    await send_long(context.bot, update.effective_chat.id, text,
                    update.message.message_thread_id)


async def cmd_tiendo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = " ".join(context.args)
    text = rg.search_progress(keyword)
    await send_long(context.bot, update.effective_chat.id, text,
                    update.message.message_thread_id)


async def cmd_trehan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = rg.build_deadline_alert(today()) or "Không có task trễ hạn hoặc đến hạn hôm nay."
    await send_long(context.bot, update.effective_chat.id, text,
                    update.message.message_thread_id)


async def cmd_tuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = rg.build_weekly_summary(today())
    await send_long(context.bot, update.effective_chat.id, text,
                    update.message.message_thread_id)


async def cmd_tai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = rg.build_workload_report(today())
    await send_long(context.bot, update.effective_chat.id, text,
                    update.message.message_thread_id, parse_mode=ParseMode.HTML)


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


async def cmd_thanhvien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args).strip().lower()
    if not name:
        await update.message.reply_text("Vui lòng nhập tên. VD: /thanhvien Thái")
        return
    tasks = [t for t in sheets.fetch_tasks()
             if t.active_on(today()) and name in t.assignee.lower()]
    if not tasks:
        await update.message.reply_text(f"Không tìm thấy công việc hôm nay của: {name}")
        return
    parts = [f"Công việc hôm nay của {tasks[0].assignee}:"]
    for t in tasks:
        status = "Hoàn thành" if t.done_date == today() else "Đang thực hiện"
        parts.append(f"- [{status}] {rg.clean_task_name(t.name)}")
    await send_long(context.bot, update.effective_chat.id, "\n".join(parts),
                    update.message.message_thread_id)


async def cmd_lammoi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sheets.fetch_tasks(force=True)
    await update.message.reply_text("Đã làm mới dữ liệu từ Google Sheet.")


async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    lines = [f"chat_id: {update.effective_chat.id}"]
    if msg.message_thread_id:
        lines.append(f"topic_id: {msg.message_thread_id}")
    lines.append(f"user_id của bạn: {update.effective_user.id}")
    await msg.reply_text("\n".join(lines))


def _parse_scalar(raw: str):
    low = raw.lower()
    if low in ("true", "on", "bat", "bật"):
        return True
    if low in ("false", "off", "tat", "tắt"):
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


# Các khóa luôn nhận giá trị dạng danh sách (các phần tử cách nhau bằng dấu phẩy).
LIST_KEYS = {"team.members", "telegram.admin_ids"}


def _parse_value(raw: str, key: str = ""):
    """Chuyển chuỗi người dùng nhập thành giá trị config.

    Nhận dạng danh sách khi: khóa thuộc LIST_KEYS, hoặc chuỗi có dấu phẩy,
    hoặc bọc trong [ ]. VD: 'An, Bình, Cường' -> ['An', 'Bình', 'Cường'].
    """
    raw = raw.strip()
    is_list = (
        key in LIST_KEYS or "," in raw
        or (raw.startswith("[") and raw.endswith("]"))
    )
    if not is_list:
        return _parse_scalar(raw)
    inner = raw[1:-1] if raw.startswith("[") and raw.endswith("]") else raw
    items = [_parse_scalar(p.strip()) for p in inner.split(",") if p.strip()]
    return [v for v in items if v is not None]


async def cmd_cauhinh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Bạn không có quyền cấu hình bot.")
        return

    args = context.args
    if not args:
        parts = ["Cấu hình lịch gửi hiện tại:"]
        for name in JOBS:
            s = cfg.get(f"schedules.{name}", {}) or {}
            state = "BẬT" if s.get("enabled") else "TẮT"
            line = (
                f"- {name}: {state} | {s.get('time')} | ngày {s.get('days')} "
                f"| chat_id {s.get('chat_id')} | topic {s.get('topic_id')}"
            )
            if name == "team_report":
                if s.get("kiosk_chat_id") or s.get("kiosk_topic_id"):
                    line += (
                        f"\n  Kiosk gửi riêng: chat_id "
                        f"{s.get('kiosk_chat_id') or s.get('chat_id')} "
                        f"| topic {s.get('kiosk_topic_id')}"
                    )
                else:
                    line += "\n  Kiosk gửi chung nhóm team_report"
            parts.append(line)
        members = cfg.get("team.members") or []
        parts.append("")
        parts.append(
            "Nhân sự (fallback team.members): "
            + (", ".join(map(str, members)) if members else "(trống — đang dùng dropdown)")
        )
        parts.append("")
        parts.append("Đổi cấu hình: /cauhinh set <khóa> <giá trị>")
        await update.message.reply_text("\n".join(parts))
        return

    if args[0] == "set" and len(args) >= 3:
        key, raw = args[1], " ".join(args[2:])
        if key.startswith(("telegram.bot_token", "google_sheets.credentials")):
            await update.message.reply_text("Không cho phép đổi khóa này qua chat.")
            return
        value = _parse_value(raw, key)
        cfg.set(key, value)
        note = ""
        if key.startswith("schedules."):
            register_jobs(context.application)
            note = "\nLịch gửi đã được nạp lại."
        elif key == "team.members":
            sheets.fetch_team_members(force=True)  # nạp lại danh sách nhân sự
            note = f"\nĐã nạp {len(value)} nhân sự cho /tai."
        await update.message.reply_text(f"Đã cập nhật {key} = {value}{note}")
        return

    await update.message.reply_text("Cú pháp: /cauhinh hoặc /cauhinh set <khóa> <giá trị>")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trả lời tự nhiên khi người dùng nhắn không dùng lệnh (chỉ trong chat riêng)."""
    if update.effective_chat.type != "private":
        return
    text = (update.message.text or "").lower()
    if any(k in text for k in ("tiến độ", "tien do", "trạng thái", "status")):
        keyword = text
        for stop in ("tiến độ", "tien do", "trạng thái", "của", "task", "?"):
            keyword = keyword.replace(stop, " ")
        reply = rg.search_progress(keyword.strip())
        await send_long(context.bot, update.effective_chat.id, reply)
    elif any(k in text for k in ("báo cáo", "bao cao")):
        reports = rg.build_daily_team_reports(today())
        await send_long(context.bot, update.effective_chat.id, reports["kiosk"],
                        parse_mode=ParseMode.HTML)
        await send_long(context.bot, update.effective_chat.id, reports["others"],
                        parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("Gõ /help để xem các lệnh hỗ trợ.")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Lỗi xử lý update: %s", context.error)
    if isinstance(update, Update) and update.effective_chat:
        await context.bot.send_message(
            update.effective_chat.id,
            f"Có lỗi xảy ra: {context.error}",
        )


def main():
    app = Application.builder().token(cfg.bot_token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("baocao", cmd_baocao))
    app.add_handler(CommandHandler("canhan", cmd_canhan))
    app.add_handler(CommandHandler("tiendo", cmd_tiendo))
    app.add_handler(CommandHandler("trehan", cmd_trehan))
    app.add_handler(CommandHandler("tai", cmd_tai))
    app.add_handler(CommandHandler("moi", cmd_moi))
    app.add_handler(CommandHandler("tuan", cmd_tuan))
    app.add_handler(CommandHandler("thanhvien", cmd_thanhvien))
    app.add_handler(CommandHandler("lamMoi", cmd_lammoi))
    app.add_handler(CommandHandler("lammoi", cmd_lammoi))
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.add_handler(CommandHandler("cauhinh", cmd_cauhinh))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    register_jobs(app)
    log.info("Bot đang chạy...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
