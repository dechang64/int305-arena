"""数据库模型"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    STUDENT = "student"
    ADMIN = "admin"


class UserStatus(str, enum.Enum):
    PENDING = "pending"      # 等待审核
    APPROVED = "approved"    # 已通过
    REJECTED = "rejected"    # 已拒绝


class CompStatus(str, enum.Enum):
    UPCOMING = "upcoming"
    LIVE = "live"
    ENDED = "ended"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    student_id = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default=UserRole.STUDENT)
    status = Column(String(20), default=UserStatus.PENDING)
    team = Column(String(100), nullable=True)
    avatar_color = Column(String(7), default="#3b82f6")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    submissions = relationship("Submission", back_populates="user")
    posted_tasks = relationship("Task", foreign_keys="Task.owner_id", back_populates="owner")
    task_applications = relationship("TaskApplication", foreign_keys="TaskApplication.applicant_id", back_populates="applicant")
    task_deliveries = relationship("TaskDelivery", foreign_keys="TaskDelivery.applicant_id", back_populates="applicant")
    credit = relationship("CreditScore", back_populates="user", uselist=False)


class Competition(Base):
    __tablename__ = "competitions"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(100), unique=True, index=True, nullable=False)  # URL 友好标识
    title = Column(String(200), nullable=False)
    subtitle = Column(String(200), nullable=True)
    description = Column(Text, nullable=False)
    lectures = Column(String(100), nullable=True)        # e.g. "Lecture 1-2"
    week = Column(String(50), nullable=True)             # e.g. "Week 1-2"

    # 评估
    metric = Column(String(50), nullable=False)          # e.g. "RMSE", "Accuracy"
    metric_direction = Column(String(10), default="lower")  # "lower" = 越低越好, "higher" = 越高越好
    baseline_score = Column(Float, nullable=True)

    # 状态与时间
    status = Column(String(20), default=CompStatus.UPCOMING)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)

    # 提交限制
    max_submissions_per_day = Column(Integer, default=3)
    max_submissions_total = Column(Integer, default=50)

    # 标签 (JSON string)
    tags = Column(Text, nullable=True)  # e.g. '["线性回归","梯度下降"]'

    # 数据集文件 (JSON string)
    dataset_files = Column(Text, nullable=True)  # e.g. '["train.csv","test.csv"]'

    created_at = Column(DateTime, default=datetime.utcnow)

    submissions = relationship("Submission", back_populates="competition")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)

    # 提交文件
    prediction_file = Column(String(500), nullable=False)  # 预测文件路径
    code_file = Column(String(500), nullable=True)          # 代码文件路径
    report_file = Column(String(500), nullable=True)        # 报告文件路径
    description = Column(Text, nullable=True)               # 简要说明

    # 评分结果
    public_score = Column(Float, nullable=True)    # 公开测试集分数
    private_score = Column(Float, nullable=True)   # 隐藏测试集分数（最终评分用）
    score_detail = Column(Text, nullable=True)     # JSON 详细评分信息

    # 状态
    is_valid = Column(Boolean, default=True)       # 提交是否有效
    error_message = Column(Text, nullable=True)    # 评分错误信息

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="submissions")
    competition = relationship("Competition", back_populates="submissions")


class TaskCategory(str, enum.Enum):
    DATA_PIPELINE = "data_pipeline"       # 数据预处理 Pipeline
    MODEL_TRAINING = "model_training"     # 模型训练脚本
    VISUALIZATION = "visualization"       # 可视化 Dashboard
    API_SERVICE = "api_service"           # API 封装 / Docker 化
    BASELINE_REPO = "baseline_repo"       # 基线模型复现
    TESTING_BENCH = "testing_bench"       # 单元测试 + Benchmark
    OTHER = "other"                       # 其他


class TaskStatus(str, enum.Enum):
    PENDING = "pending"                   # 待审核
    OPEN = "open"                         # 开放接单
    IN_PROGRESS = "in_progress"           # 进行中（已有人接单）
    UNDER_REVIEW = "under_review"         # 验收中
    COMPLETED = "completed"               # 已完成
    REJECTED_ADMIN = "rejected_admin"     # 管理员审核未通过
    CANCELLED = "cancelled"               # 已取消


class ApplicationStatus(str, enum.Enum):
    PENDING = "pending"                   # 待审核
    ACCEPTED = "accepted"                 # 已接受
    REJECTED = "rejected"                 # 已拒绝
    WITHDRAWN = "withdrawn"               # 已撤回


class DeliveryStatus(str, enum.Enum):
    SUBMITTED = "submitted"               # 已提交
    ACCEPTED = "accepted"                 # 验收通过
    REVISION = "revision"                 # 需修改
    REJECTED = "rejected"                 # 验收未通过


class Task(Base):
    """任务市场 — 学生从毕设拆出的ML任务"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(30), nullable=False)

    # 出题者
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 毕设信息
    thesis_title = Column(String(300), nullable=True)
    thesis_advisor = Column(String(100), nullable=True)

    # 任务要求
    deliverables = Column(Text, nullable=False)           # JSON: 交付物列表
    acceptance_criteria = Column(Text, nullable=False)    # 验收标准
    difficulty = Column(String(10), default="medium")     # easy/medium/hard
    estimated_hours = Column(Integer, nullable=True)      # 预估工时(小时)

    # 数据与资源
    data_description = Column(Text, nullable=True)        # 数据说明
    data_availability = Column(String(20), default="public")  # public/shared/private
    resource_links = Column(Text, nullable=True)          # JSON: 资源链接列表

    # 状态与时间
    status = Column(String(20), default=TaskStatus.PENDING)
    deadline = Column(DateTime, nullable=True)            # 交付截止时间

    # 标签
    tags = Column(Text, nullable=True)                    # JSON: 标签列表

    # 统计
    view_count = Column(Integer, default=0)
    application_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    owner = relationship("User", foreign_keys=[owner_id], back_populates="posted_tasks")
    applications = relationship("TaskApplication", back_populates="task", cascade="all, delete-orphan")
    deliveries = relationship("TaskDelivery", back_populates="task", cascade="all, delete-orphan")


class TaskApplication(Base):
    """任务申请 — 学生申请接单"""
    __tablename__ = "task_applications"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    applicant_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 申请信息
    message = Column(Text, nullable=True)                 # 申请留言
    proposed_approach = Column(Text, nullable=True)       # 提案方案

    # 状态
    status = Column(String(20), default=ApplicationStatus.PENDING)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    task = relationship("Task", back_populates="applications")
    applicant = relationship("User", foreign_keys=[applicant_id], back_populates="task_applications")


class TaskDelivery(Base):
    """任务交付 — 做题者提交交付物"""
    __tablename__ = "task_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    applicant_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 交付物
    code_url = Column(String(500), nullable=True)         # GitHub/代码链接
    demo_url = Column(String(500), nullable=True)         # Demo 链接
    documentation = Column(Text, nullable=True)           # 文档说明
    attachment = Column(String(500), nullable=True)       # 附件路径

    # 验收
    review_status = Column(String(20), default=DeliveryStatus.SUBMITTED)
    review_comment = Column(Text, nullable=True)          # 验收评语
    quality_score = Column(Integer, nullable=True)        # 1-5 质量评分

    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    # 关系
    task = relationship("Task", back_populates="deliveries")
    applicant = relationship("User", foreign_keys=[applicant_id], back_populates="task_deliveries")


class CreditScore(Base):
    """信用分 — 每个用户的任务市场信用"""
    __tablename__ = "credit_scores"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    score = Column(Integer, default=100)                  # 信用分，初始100
    tasks_posted = Column(Integer, default=0)             # 发布任务数
    tasks_completed = Column(Integer, default=0)          # 完成任务数
    tasks_reviewed = Column(Integer, default=0)           # 验收任务数
    on_time_rate = Column(Float, default=1.0)             # 按时交付率
    acceptance_rate = Column(Float, default=1.0)          # 一次通过率
    avg_quality_score = Column(Float, nullable=True)      # 平均质量评分

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="credit")


class DailySubmissionCount(Base):
    """每日提交计数，用于限制提交频率"""
    __tablename__ = "daily_submission_counts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    count = Column(Integer, default=0)
