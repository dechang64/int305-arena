"""FastAPI 主应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import FRONTEND_URL, UPLOAD_DIR, DATASET_DIR
from .database import create_tables
from .routers import auth, competitions, submissions, leaderboard, admin, market

app = FastAPI(
    title="INT305 ML Arena",
    description="机器学习竞赛教学平台 API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:8080", "http://localhost:3000", "*"],
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

# 静态文件（数据集下载等）
app.mount("/api/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/api/datasets", StaticFiles(directory=str(DATASET_DIR)), name="datasets")


@app.on_event("startup")
def startup():
    """启动时创建数据表"""
    create_tables()


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "INT305 ML Arena"}
