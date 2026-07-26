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
