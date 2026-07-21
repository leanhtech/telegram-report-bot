# -*- coding: utf-8 -*-
"""Quản lý cấu hình bot: đọc/ghi config.yaml, hỗ trợ cập nhật runtime."""
import os
import threading
import yaml

CONFIG_PATH = os.environ.get(
    "BOT_CONFIG", os.path.join(os.path.dirname(__file__), "..", "config.yaml")
)

_lock = threading.Lock()


class Config:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = os.path.abspath(path)
        self.data = {}
        self.reload()

    def reload(self):
        with _lock:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = yaml.safe_load(f) or {}

    def save(self):
        with _lock:
            with open(self.path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.data, f, allow_unicode=True, sort_keys=False)

    # --- helper truy cập theo đường dẫn "a.b.c" ---
    def get(self, dotted_key: str, default=None):
        node = self.data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted_key: str, value):
        parts = dotted_key.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.save()

    # --- shortcut hay dùng ---
    @property
    def bot_token(self):
        return self.get("telegram.bot_token")

    @property
    def admin_ids(self):
        return set(self.get("telegram.admin_ids", []) or [])

    @property
    def timezone(self):
        return self.get("timezone", "Asia/Ho_Chi_Minh")


cfg = Config()
