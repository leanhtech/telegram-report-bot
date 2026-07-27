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
