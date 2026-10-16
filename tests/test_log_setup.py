# -*- coding: utf-8 -*-
"""Test cho src/log_setup.py — token bot không được lọt ra log của httpx."""
import io
import logging
import unittest

from src.log_setup import NOISY_LOGGERS, setup_logging

FAKE_TOKEN = "123456:ABC-def"
URL = f"https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates"


class TestLogSetup(unittest.TestCase):
    def setUp(self):
        root = logging.getLogger()
        self.saved_root = (root.level, root.handlers[:])
        self.saved = {n: logging.getLogger(n).level for n in NOISY_LOGGERS}
        root.handlers = []  # basicConfig chỉ chạy khi root chưa có handler
        setup_logging()
        # Thay handler stderr của basicConfig bằng handler ghi vào bộ nhớ
        self.stream = io.StringIO()
        root.handlers = [logging.StreamHandler(self.stream)]

    def tearDown(self):
        root = logging.getLogger()
        root.setLevel(self.saved_root[0])
        root.handlers = self.saved_root[1]
        for name, level in self.saved.items():
            logging.getLogger(name).setLevel(level)

    def test_request_log_cua_httpx_khong_lo_token(self):
        # Đúng dạng dòng httpx ghi cho mỗi request
        logging.getLogger("httpx").info(
            'HTTP Request: %s %s "%s %d %s"',
            "POST", URL, "HTTP/1.1", 200, "OK",
        )
        logging.getLogger("httpcore").info("connect %s", URL)
        self.assertNotIn(FAKE_TOKEN, self.stream.getvalue())

    def test_canh_bao_httpx_van_hien(self):
        logging.getLogger("httpx").warning("mất kết nối")
        self.assertIn("mất kết nối", self.stream.getvalue())

    def test_log_cua_bot_van_hien_o_info(self):
        logging.getLogger("report-bot").info("bot đã chạy")
        self.assertIn("bot đã chạy", self.stream.getvalue())


if __name__ == "__main__":
    unittest.main()
