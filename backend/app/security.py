"""文件安全工具 —— 所有「客户端可控的文件名/路径」必须经过本模块。

背景（审计 S2）：原代码直接使用 ``file.filename`` 拼接落盘路径

    task_dir / f"{current_user.id}_{file.filename}"

看似有 ``{user_id}_`` 前缀兜底，但 Windows 对 ``..`` 做**词法折叠**：
``..\\..\\..\\`` 会把前缀连同中间目录一起吃掉，实测 7 层即可写到仓库根目录，
任何通过审核的学生账号都能利用（等价任意文件写 → 可覆盖后端代码）。

本模块提供两道闸门：

1. :func:`safe_filename` —— 剥目录 + 字符白名单 + 长度限制 + Windows 保留名拒绝；
2. :func:`safe_join` —— 拼接后 ``resolve()``，断言仍在预期根目录之下。

两者必须**同时**使用：前者防脏名，后者防绕过（符号链接、编码变形、平台差异）。
"""
from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "UnsafeFilenameError",
    "safe_filename",
    "safe_join",
    "is_answer_like",
]


class UnsafeFilenameError(ValueError):
    """文件名未通过安全校验。"""


# 允许的字符：中日韩汉字、字母、数字、下划线、点、连字符、空格
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-\u4e00-\u9fff ]{1,80}$")

# Windows 保留设备名（不区分大小写，且对带扩展名的形式同样保留）
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# 答案类文件名特征 —— 这类文件永远不允许出现在任何可下载路径上。
# 刻意取得偏保守（宁可误伤，不可漏放）：管理员若确有名为 answers_template.csv 的
# 公开模板，改名即可；反过来漏放一次答案的代价是整个竞赛失效。
# 覆盖：answer.csv / answers.csv / answer_v2.csv / answer_key.csv / gt.csv / 标准答案.csv
_ANSWER_LIKE_RE = re.compile(r"(^|[_\-. ])answers?([_\-.\d ]|$)|^gt([_\-.]|$)|答案", re.I)


def is_answer_like(filename: str) -> bool:
    """判断文件名是否「像标准答案」，用于下载侧的兜底拦截。

    这是第二道防线：第一道是答案文件本身就不存放在可下载目录（``ANSWERS_DIR``）。
    即便管理员误把答案传进 datasets，这里也会拦住。
    """
    return bool(_ANSWER_LIKE_RE.search(Path(str(filename)).name))


def safe_filename(name: str, *, max_len: int = 80) -> str:
    """把客户端提供的文件名净化为可安全落盘的 basename。

    规则：剥掉一切目录成分 → 去控制字符 → 裁剪长度（保留扩展名）→ 白名单校验。

    Raises:
        UnsafeFilenameError: 净化后为空、超出白名单、或命中 Windows 保留名。
    """
    if name is None:
        raise UnsafeFilenameError("文件名为空")

    # 1) 统一分隔符后取最后一段 —— 同时覆盖 POSIX 的 "/" 与 Windows 的 "\\"
    raw = str(name).replace("\\", "/")
    base = raw.rsplit("/", 1)[-1]

    # 2) 去掉残余盘符 / 流标记（形如 "C:evil.txt"、"a.txt:stream"）
    base = re.sub(r"^[A-Za-z]:", "", base)
    base = base.replace(":", "_")

    # 3) 去控制字符与不可打印字符
    base = "".join(ch for ch in base if ch.isprintable())

    # 4) 去掉 Windows 会静默截断的首尾空格与点（"evil.txt." -> "evil.txt"）
    base = base.strip(" .")

    # 5) 长度裁剪，尽量保留扩展名
    if len(base) > max_len:
        stem, dot, suffix = base.rpartition(".")
        if dot and len(suffix) <= 10:
            keep = max_len - len(suffix) - 1
            base = f"{stem[:keep]}.{suffix}" if keep > 0 else base[:max_len]
        else:
            base = base[:max_len]
        base = base.strip(" .")

    # 6) 白名单校验
    if not base or not _SAFE_NAME_RE.match(base):
        raise UnsafeFilenameError(
            f"文件名不合法（仅允许字母/数字/下划线/点/连字符/空格/汉字，且不超过 {max_len} 字符）"
        )

    # 7) Windows 保留设备名
    if Path(base).stem.upper() in _WINDOWS_RESERVED:
        raise UnsafeFilenameError(f"文件名 '{base}' 是系统保留名")

    return base


def safe_join(root, *parts) -> Path:
    """在 ``root`` 之下安全拼接路径，并断言结果没有逃出 ``root``。

    这是 S2 的最终防线：即使 :func:`safe_filename` 被绕过（未知平台语义、
    符号链接、编码变形），``resolve()`` 之后的父目录断言仍会拦住越界写入。
    """
    root_path = Path(root).resolve()
    target = root_path.joinpath(*[str(p) for p in parts]).resolve()
    if target != root_path and root_path not in target.parents:
        raise UnsafeFilenameError("目标路径超出允许的存储目录")
    return target
