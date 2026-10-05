"""应用配置 — 从环境变量读取

[审计补丁 S3] 原实现为 SECRET_KEY / ADMIN_PASSWORD 提供**写死在源码里的兜底值**，
而仓库是公开的，等于公开了默认管理员口令与 JWT 签名密钥：

    POST /api/auth/login  {"email":"admin@xjtlu.edu.cn","password":"admin123"}  -> 200 role=admin

且 `README` 教你 `cp .env.example .env`，但漏做这一步不会报错，只会静默用默认值。

现在改为**启动即校验**：缺失或等于已知兜底值时直接拒绝启动（fail-fast），
并把正确的生成方式打印出来，避免"静默不安全"。

仅自动化测试/一次性本地演示可通过 `ALLOW_INSECURE_DEFAULTS=1` 放行，
此时会打印醒目告警。
"""
import os
import secrets
import sys
from pathlib import Path


def _env_flag(name: str, default: bool = False) -> bool:
    """宽松解析布尔环境变量：1/true/yes/on 均视为真（大小写无关）。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 天

# 管理员
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@xjtlu.edu.cn")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# 数据库
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'int305_arena.db'}")

# 文件存储
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")))
DATASET_DIR = Path(os.getenv("DATASET_DIR", str(BASE_DIR / "data" / "datasets")))

# [审计补丁 S1] 标准答案单独存放，**不在任何可下载目录之下**。
# 原实现把 answer.csv 放在 DATASET_DIR 里，而整个 DATASET_DIR 被 StaticFiles
# 无鉴权挂载，导致 `GET /api/datasets/7/answer.csv` 免登录 200 —— 抄答案即满分。
ANSWERS_DIR = Path(os.getenv("ANSWERS_DIR", str(BASE_DIR / "data" / "answers")))

MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))

# 注册审核
REQUIRE_APPROVAL = _env_flag("REQUIRE_APPROVAL")

# CORS
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")

# 是否放行不安全的兜底凭据（仅测试/演示；生产必须为 false）
ALLOW_INSECURE_DEFAULTS = _env_flag("ALLOW_INSECURE_DEFAULTS")

# 确保目录存在
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATASET_DIR.mkdir(parents=True, exist_ok=True)
ANSWERS_DIR.mkdir(parents=True, exist_ok=True)


def answer_path_for(comp_id: int) -> Path:
    """标准答案文件路径。

    [审计补丁 S1] 优先使用 ``ANSWERS_DIR``（不在任何可下载目录下）。
    为兼容迁移前已存在的部署，若新位置没有文件而旧位置
    （``DATASET_DIR/{comp_id}/answer.csv``）有，则回落到旧位置 —— 旧位置虽然
    仍在 datasets 目录里，但静态挂载已移除、且下载侧有 ``is_answer_like`` 拦截，
    因此不构成新的暴露面。迁移脚本见 ``scripts/migrate_answers.py``。
    """
    new_path = ANSWERS_DIR / str(comp_id) / "answer.csv"
    if new_path.exists():
        return new_path
    legacy = DATASET_DIR / str(comp_id) / "answer.csv"
    if legacy.exists():
        return legacy
    return new_path


# ---------------------------------------------------------------------------
# [审计补丁 S3] 启动期安全校验
# ---------------------------------------------------------------------------
# 已知的、曾经出现在源码/文档/compose 文件里的兜底密钥。任何一个被用作实际
# SECRET_KEY 都意味着任何人都能伪造管理员 JWT（含 role=admin 的令牌）。
_INSECURE_SECRETS = {
    "dev-secret-key-change-in-production",
    "change-me-in-production-2024",
    "change-me-to-a-random-string-in-production",
    "secret",
    "",
}

# 同理，这些口令一旦生效，公开仓库 = 公开管理员账号。
_INSECURE_ADMIN_PASSWORDS = {"admin123", "admin", "password", "123456", ""}

_GENERATE_HINT = (
    '  python -c "import secrets; print(secrets.token_urlsafe(48))"'
)


def validate_security_config() -> list:
    """校验凭据强度。返回告警列表；不通过时抛 RuntimeError。"""
    problems = []

    if SECRET_KEY in _INSECURE_SECRETS or len(SECRET_KEY) < 32:
        if SECRET_KEY in _INSECURE_SECRETS:
            problems.append(
                f"SECRET_KEY 正在使用公开的兜底值（{SECRET_KEY!r}）。"
                "任何人都能用它伪造任意用户（含管理员）的 JWT。"
            )
        else:
            problems.append(f"SECRET_KEY 过短（{len(SECRET_KEY)} 字符，至少 32）。")

    if ADMIN_PASSWORD in _INSECURE_ADMIN_PASSWORDS or len(ADMIN_PASSWORD) < 8:
        if ADMIN_PASSWORD in _INSECURE_ADMIN_PASSWORDS:
            problems.append(
                f"ADMIN_PASSWORD 正在使用公开的兜底口令（{ADMIN_PASSWORD!r}）。"
            )
        else:
            problems.append(f"ADMIN_PASSWORD 过短（{len(ADMIN_PASSWORD)} 字符，至少 8）。")

    if not problems:
        return []

    detail = "\n".join(f"  - {p}" for p in problems)
    message = (
        "启动被拒绝：检测到不安全的默认凭据。\n"
        f"{detail}\n\n"
        "修复方式（二选一）：\n"
        "  1) 在 .env 或环境变量中显式提供，随机值可用：\n"
        f"{_GENERATE_HINT}\n"
        "  2) 若只是自动化测试或一次性本地演示，可设 ALLOW_INSECURE_DEFAULTS=1 放行（不建议）。"
    )

    if ALLOW_INSECURE_DEFAULTS:
        warning = "=" * 72 + "\n"
        warning += "⚠️  ALLOW_INSECURE_DEFAULTS=1：正在使用不安全的默认凭据启动。\n"
        warning += message + "\n"
        warning += "=" * 72
        print(warning, file=sys.stderr)
        return problems

    raise RuntimeError(message)


validate_security_config()
