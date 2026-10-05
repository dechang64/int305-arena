"""FastAPI 主应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from .config import FRONTEND_URL, UPLOAD_DIR, DATASET_DIR, ANSWERS_DIR
from .database import create_tables
from .routers import auth, competitions, submissions, leaderboard, admin, market, files, explain

app = FastAPI(
    title="INT305 ML Arena",
    description="机器学习竞赛教学平台 API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS
# [审计补丁] 原配置 allow_origins=[..., "*"] 且 allow_credentials=True —— 通配源
# 与凭据模式互斥，等价于对任意站点开放。本平台认证走 Authorization 头而非 Cookie，
# 风险有限，但配置本身不该是通配。改为显式白名单（可用 CORS_ORIGINS 环境变量覆盖）。
import os as _os

_cors_extra = [o.strip() for o in _os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:8080", "http://localhost:3000", *_cors_extra],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api")
app.include_router(competitions.router, prefix="/api")
app.include_router(submissions.router, prefix="/api")
app.include_router(leaderboard.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(explain.router, prefix="/api")

# ---------------------------------------------------------------------------
# [审计补丁 S1 / S4] 已移除两处无鉴权静态挂载
#
# 原代码：
#   app.mount("/api/uploads",  StaticFiles(directory=UPLOAD_DIR))   # S4
#   app.mount("/api/datasets", StaticFiles(directory=DATASET_DIR))  # S1（最严重）
#
# 后果（已实测）：
#   [无 token] GET /api/datasets/7/answer.csv        -> 200  ← 抄答案即满分
#   [无 token] GET /api/uploads/deliveries/1/3_normal.zip -> 200  ← 交付物公开
#
# 现在改为：
#   * 答案文件迁移到 ANSWERS_DIR（不在任何静态目录下，无任何下载端点）；
#   * 数据集 / 交付附件统一走 app/routers/files.py 的校验接口。
# ---------------------------------------------------------------------------


@app.on_event("startup")
def startup():
    """启动时创建数据表"""
    create_tables()
    print(f"📂 数据集目录: {DATASET_DIR}")
    print(f"🔒 答案目录（无下载端点）: {ANSWERS_DIR}")
    print(f"📦 上传目录: {UPLOAD_DIR}")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "INT305 ML Arena"}
