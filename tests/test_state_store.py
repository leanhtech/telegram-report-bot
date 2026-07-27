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

    def test_sources_sai_kieu_thi_ve_dict_rong(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": state_store.STATE_VERSION, "sources": "oops",
                      "pending": [{"i": 1}]}, f)
        state = state_store.load(self.path)
        self.assertEqual(state["sources"], {})
        self.assertEqual(state["pending"], [{"i": 1}])

    def test_pending_sai_kieu_thi_ve_danh_sach_rong(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": state_store.STATE_VERSION,
                      "sources": {"vnedu": {"snapshot": {}}}, "pending": "oops"}, f)
        state = state_store.load(self.path)
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["sources"], {"vnedu": {"snapshot": {}}})

    def test_ca_hai_truong_sai_kieu_khong_lam_sap_bot(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": state_store.STATE_VERSION,
                      "sources": "oops", "pending": "oops"}, f)
        state = state_store.load(self.path)
        self.assertEqual(state["sources"], {})
        self.assertEqual(state["pending"], [])

    def test_tu_tao_thu_muc_neu_chua_co(self):
        nested = os.path.join(self.dir, "state", "watch_state.json")
        state_store.save(nested, state_store.default_state())
        self.assertTrue(os.path.exists(nested))


if __name__ == "__main__":
    unittest.main()
