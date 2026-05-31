"""应用配置 — 从环境变量读取"""
import os
from pathlib import Path

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
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))

# 注册审核
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "false").lower() == "true"

# CORS
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")

# 确保目录存在
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATASET_DIR.mkdir(parents=True, exist_ok=True)
