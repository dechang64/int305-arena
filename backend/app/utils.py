"""通用小工具（JSON 列读写等）。

[审计补丁 B5] 说明：`Competition.tags` / `Competition.dataset_files` / `Task.tags` 等
列在 models 里声明为 ``Text``，但业务代码把它当 ``list`` 用。sqlite3 无法绑定 list，
写入直接抛 ``InterfaceError: Error binding parameter``，整个事务回滚。
读写两侧统一走这里的转换函数即可根治。
"""
from __future__ import annotations

import json
from typing import Any, Optional

__all__ = ["jload", "jdump"]


def jload(value: Any, default: Optional[Any] = None) -> Any:
    """把数据库里的 JSON 字符串安全地解析回 Python 对象。"""
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def jdump(value: Any) -> Optional[str]:
    """把 Python 对象序列化为可写入 Text 列的 JSON 字符串。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)
