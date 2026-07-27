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


if __name__ == "__main__":
    unittest.main()
