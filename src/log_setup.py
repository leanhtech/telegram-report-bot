# -*- coding: utf-8 -*-
"""Cấu hình logging cho bot — tách riêng để test được không cần telegram."""
import logging

# httpx log mỗi request ở INFO kèm URL đầy đủ
# (https://api.telegram.org/bot<TOKEN>/getUpdates) → lộ token bot ra log.
# Nâng lên WARNING như doc2report; httpcore cũng nâng cho chắc.
NOISY_LOGGERS = ("httpx", "httpcore")


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=level
    )
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
