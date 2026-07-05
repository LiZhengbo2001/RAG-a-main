"""结构化日志 — JSON格式，键值对打点，方便 grep / ELK / Grafana 检索"""

import logging
import json
import sys
import time
from datetime import datetime, timezone, timedelta

CN_TZ = timezone(timedelta(hours=8))


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":       datetime.now(CN_TZ).isoformat(),
            "level":    record.levelname.lower(),
            "logger":   record.name,
            "msg":      record.getMessage(),
        }
        # 附加字段（通过 extra 传入）
        for key in ("event", "user_id", "conversation_id", "elapsed_ms", "query",
                     "chunks", "tokens", "status", "method", "path", "error"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        # 异常堆栈
        if record.exc_info and record.exc_info[1]:
            payload["error"] = str(record.exc_info[1])
        return json.dumps(payload, ensure_ascii=False)


def setup_logger(name: str = "rag_agent") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:  # 防止重复添加
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


logger = setup_logger()
