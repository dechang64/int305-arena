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

    # [讲轨扩展] 讲轨综合分（0–100）与有效质询计数
    # challenge_credits 是「咬合点二」的判定依据：出题者需完成有效质询才能验收他人交付
    explain_score = Column(Float, nullable=True)          # 讲轨综合分 0–100
    challenge_credits = Column(Integer, default=0)        # 有效质询计数

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="credit")


# ===========================================================================
# 讲轨（Explain Track）—— 把「讲」做成一等交付物
#
# 设计依据：《INT305 ML Arena 教学重构方案》第五章。
# 现状诊断：平台只能验证「你做出来了」，不能验证「你懂了」；而排行榜的最优策略
# （换权重 + 调参）恰恰最不需要理解——激励在主动奖励「不懂」。
# 讲轨五步：认领概念卡 → 回讲三件套 → 全员质询 → 助教裁定卡壳 → 重构第二版。
#
# 迭代一（本次实现）只做「采集链路 + 只读视图」：认领 / 回讲 / 质询 / 裁定 / 聚合，
# 不打分、不设闸门，因此**不改变任何现有教学流程**。
# ===========================================================================


class ConceptStatus(str, enum.Enum):
    OPEN = "open"                # 待认领
    CLAIMED = "claimed"          # 已认领
    EXPLAINING = "explaining"    # 已回讲，质询中
    CHALLENGED = "challenged"    # 质询已发起
    CLOSED = "closed"            # 闭环（含第二版）


class ConceptTrack(str, enum.Enum):
    BASE = "base"                # 基础：线性模型 / 优化
    ARCH = "arch"                # 架构：CNN / 归一化 / 残差
    OPTIMIZE = "optimize"        # 优化：学习率 / 动量 / Adam
    APPLICATION = "application"  # 应用：注意力 / Transformer / 预训练


class Concept(Base):
    """表一 · concepts —— 概念卡（讲轨的原子单位）"""
    __tablename__ = "concepts"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, index=True, nullable=False)   # C-12
    title = Column(String(200), nullable=False)
    d2l_ref_zh = Column(String(100), nullable=True)                      # 7.5 批量规范化
    d2l_ref_en = Column(String(100), nullable=True)                      # 8.5 Batch Normalization
    d2l_url = Column(String(500), nullable=True)
    boundary = Column(Text, nullable=True)         # 判定边界：要讲清的最小命题
    common_gaps = Column(Text, nullable=True)      # JSON: 教师预标注的常见卡壳点
    jargon_watchlist = Column(Text, nullable=True)  # JSON: 高危术语清单
    track = Column(String(20), default=ConceptTrack.BASE)
    claimed_by_group = Column(String(100), nullable=True)   # 认领组（乐观锁）
    claimed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default=ConceptStatus.OPEN)
    created_at = Column(DateTime, default=datetime.utcnow)

    claims = relationship("ExplainClaim", back_populates="concept", cascade="all, delete-orphan")


class ClaimStatus(str, enum.Enum):
    SUBMITTED = "submitted"      # 已提交
    CHALLENGED = "challenged"    # 已被质询
    REVISED = "revised"          # 已提交第二版
    ACCEPTED = "accepted"        # 已验收（迭代二）


class ExplainClaim(Base):
    """表二 · explain_claims —— 回讲提交（白话稿三件套）"""
    __tablename__ = "explain_claims"

    id = Column(Integer, primary_key=True, index=True)
    concept_id = Column(Integer, ForeignKey("concepts.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    group_name = Column(String(100), nullable=True)

    plain_text = Column(Text, nullable=False)      # 白话稿（150–250 字）
    analogy = Column(Text, nullable=True)          # 类比句
    counterexample = Column(Text, nullable=True)   # 反例卡

    version = Column(Integer, default=1)           # 1 或 2
    parent_id = Column(Integer, ForeignKey("explain_claims.id"), nullable=True)
    revision_diff = Column(Text, nullable=True)    # 第二版必填：我第一版漏了什么
    gap_closed = Column(Boolean, default=False)

    status = Column(String(20), default=ClaimStatus.SUBMITTED)
    created_at = Column(DateTime, default=datetime.utcnow)

    concept = relationship("Concept", back_populates="claims")
    challenges = relationship("ExplainChallenge", back_populates="claim", cascade="all, delete-orphan")


class ExplainChallenge(Base):
    """表三 · explain_challenges —— 质询（全班可见的提问池）"""
    __tablename__ = "explain_challenges"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("explain_claims.id"), nullable=False, index=True)
    challenger_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    question = Column(Text, nullable=False)        # 必须是疑问句
    uses_concept_term = Column(Boolean, default=False)  # 是否含被讲概念的核心术语（反滥用信号）
    response = Column(Text, nullable=True)         # 讲解组回应

    is_gap = Column(Boolean, nullable=True)        # 是否被裁定为卡壳点（None=待裁定）
    gap_severity = Column(Integer, nullable=True)  # 1–3
    arbiter_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    responded_at = Column(DateTime, nullable=True)

    claim = relationship("ExplainClaim", back_populates="challenges")
    challenger = relationship("User", foreign_keys=[challenger_id])
    arbiter = relationship("User", foreign_keys=[arbiter_id])


class ConceptQualityScore(Base):
    """表四 · concept_quality_scores —— 讲解分（四维，各 0–3，合计 0–12）

    ⚠️ 「卡壳诚实」方向必须与直觉相反：承认不懂给高分、掩饰不懂给 0 分。
    这是整套机制能否产生真实诊断数据的关键——否则学生会理性地伪装理解。
    （迭代二启用打分端点，本表先建好以固定数据契约。）
    """
    __tablename__ = "concept_quality_scores"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("explain_claims.id"), nullable=False)
    dim_jargon = Column(Integer, default=0)        # 术语依赖度
    dim_analogy = Column(Integer, default=0)       # 类比贴切度
    dim_honesty = Column(Integer, default=0)       # 卡壳诚实度
    dim_compression = Column(Integer, default=0)   # 重构压缩率
    total = Column(Integer, default=0)             # 0–12
    scored_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    comment = Column(Text, nullable=True)          # 空评语不给分
    created_at = Column(DateTime, default=datetime.utcnow)


class DailySubmissionCount(Base):
    """每日提交计数，用于限制提交频率"""
    __tablename__ = "daily_submission_counts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    count = Column(Integer, default=0)
