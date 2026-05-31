"""Pydantic 请求/响应模型"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field


# ===== Auth =====
class RegisterRequest(BaseModel):
    email: str = Field(..., description="学校邮箱")
    name: str = Field(..., min_length=2, max_length=100)
    student_id: str = Field(..., min_length=4, max_length=50)
    password: str = Field(..., min_length=6)
    team: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserBrief"


class UserBrief(BaseModel):
    id: int
    email: str
    name: str
    student_id: str
    role: str
    status: str
    team: Optional[str]

    class Config:
        from_attributes = True


# ===== Competition =====
class CompetitionCreate(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9-]+$", description="URL标识，如 comp1-house-price")
    title: str
    subtitle: Optional[str] = None
    description: str
    lectures: Optional[str] = None
    week: Optional[str] = None
    metric: str = Field(..., description="评估指标，如 RMSE, Accuracy, AUC-ROC")
    metric_direction: str = Field(default="lower", description="lower=越低越好, higher=越高越好")
    baseline_score: Optional[float] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    max_submissions_per_day: int = 3
    max_submissions_total: int = 50
    tags: Optional[List[str]] = None


class CompetitionUpdate(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    max_submissions_per_day: Optional[int] = None
    max_submissions_total: Optional[int] = None
    tags: Optional[List[str]] = None


class CompetitionResponse(BaseModel):
    id: int
    slug: str
    title: str
    subtitle: Optional[str]
    description: str
    lectures: Optional[str]
    week: Optional[str]
    metric: str
    metric_direction: str
    baseline_score: Optional[float]
    status: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    max_submissions_per_day: int
    max_submissions_total: int
    tags: Optional[List[str]]
    dataset_files: Optional[List[str]]
    participant_count: int = 0
    top_score: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ===== Submission =====
class SubmissionResponse(BaseModel):
    id: int
    user_id: int
    competition_id: int
    prediction_file: str
    code_file: Optional[str]
    report_file: Optional[str]
    description: Optional[str]
    public_score: Optional[float]
    private_score: Optional[float]
    score_detail: Optional[str]
    is_valid: bool
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SubmissionResult(BaseModel):
    """提交后的即时结果"""
    submission_id: int
    public_score: Optional[float]
    error_message: Optional[str]
    remaining_submissions_today: int


# ===== Leaderboard =====
class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    name: str
    team: Optional[str]
    avatar_color: str
    best_score: float
    submission_count: int
    last_submission_time: Optional[datetime]
    trend: str = "same"  # up, down, same


# ===== Admin =====
class UserAdminView(BaseModel):
    id: int
    email: str
    name: str
    student_id: str
    role: str
    status: str
    team: Optional[str]
    created_at: datetime
    last_login: Optional[datetime]
    submission_count: int = 0

    class Config:
        from_attributes = True


class UserApproveRequest(BaseModel):
    user_id: int
    action: str = Field(..., pattern=r"^(approve|reject)$")


class GradeExport(BaseModel):
    student_id: str
    name: str
    email: str
    competition_scores: dict  # {comp_slug: {rank_score, public_score, rank}}
    improvement_score: float
    report_score: Optional[float]
    community_score: Optional[float]
    final_grade: float


# ===== Task Market =====

# --- 任务 ---
class TaskCreate(BaseModel):
    """学生发布任务"""
    title: str = Field(..., min_length=5, max_length=200, description="任务标题")
    description: str = Field(..., min_length=20, description="任务详细描述")
    category: str = Field(..., description="任务类型: data_pipeline/model_training/visualization/api_service/baseline_repo/testing_bench/other")
    thesis_title: Optional[str] = Field(None, description="毕设题目")
    thesis_advisor: Optional[str] = Field(None, description="指导老师")
    deliverables: List[str] = Field(..., min_length=1, description="交付物列表，如 ['训练脚本', 'README文档']")
    acceptance_criteria: str = Field(..., min_length=10, description="验收标准")
    difficulty: str = Field(default="medium", description="难度: easy/medium/hard")
    estimated_hours: Optional[int] = Field(None, description="预估工时(小时)")
    data_description: Optional[str] = Field(None, description="数据说明")
    data_availability: str = Field(default="public", description="数据可用性: public/shared/private")
    resource_links: Optional[List[str]] = Field(None, description="资源链接列表")
    deadline: Optional[datetime] = Field(None, description="交付截止时间")
    tags: Optional[List[str]] = Field(None, description="标签列表")


class TaskUpdate(BaseModel):
    """出题者修改任务"""
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    deliverables: Optional[List[str]] = None
    acceptance_criteria: Optional[str] = None
    difficulty: Optional[str] = None
    estimated_hours: Optional[int] = None
    data_description: Optional[str] = None
    data_availability: Optional[str] = None
    resource_links: Optional[List[str]] = None
    deadline: Optional[datetime] = None
    tags: Optional[List[str]] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    category: str
    owner_id: int
    owner_name: Optional[str] = None
    owner_team: Optional[str] = None
    thesis_title: Optional[str]
    thesis_advisor: Optional[str]
    deliverables: List[str]
    acceptance_criteria: str
    difficulty: str
    estimated_hours: Optional[int]
    data_description: Optional[str]
    data_availability: str
    resource_links: Optional[List[str]]
    status: str
    deadline: Optional[datetime]
    tags: Optional[List[str]]
    view_count: int
    application_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskBrief(BaseModel):
    """任务列表简要信息"""
    id: int
    title: str
    category: str
    difficulty: str
    status: str
    owner_name: Optional[str]
    estimated_hours: Optional[int]
    application_count: int
    tags: Optional[List[str]]
    deadline: Optional[datetime]
    created_at: datetime


# --- 申请 ---
class ApplicationCreate(BaseModel):
    """申请接单"""
    message: Optional[str] = Field(None, max_length=500, description="申请留言")
    proposed_approach: Optional[str] = Field(None, max_length=1000, description="提案方案")


class ApplicationResponse(BaseModel):
    id: int
    task_id: int
    applicant_id: int
    applicant_name: Optional[str] = None
    applicant_team: Optional[str] = None
    applicant_credit: Optional[int] = None
    message: Optional[str]
    proposed_approach: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ApplicationAction(BaseModel):
    """出题者接受/拒绝申请"""
    action: str = Field(..., pattern=r"^(accept|reject)$")


# --- 交付 ---
class DeliveryCreate(BaseModel):
    """提交交付物"""
    code_url: Optional[str] = Field(None, description="GitHub/代码链接")
    demo_url: Optional[str] = Field(None, description="Demo链接")
    documentation: Optional[str] = Field(None, description="文档说明")
    # attachment 通过文件上传单独处理


class DeliveryResponse(BaseModel):
    id: int
    task_id: int
    applicant_id: int
    applicant_name: Optional[str] = None
    code_url: Optional[str]
    demo_url: Optional[str]
    documentation: Optional[str]
    attachment: Optional[str]
    review_status: str
    review_comment: Optional[str]
    quality_score: Optional[int]
    created_at: datetime
    reviewed_at: Optional[datetime]

    class Config:
        from_attributes = True


class DeliveryReview(BaseModel):
    """出题者验收交付物"""
    action: str = Field(..., pattern=r"^(accept|revision|reject)$")
    comment: Optional[str] = Field(None, max_length=1000, description="验收评语")
    quality_score: Optional[int] = Field(None, ge=1, le=5, description="质量评分1-5")


# --- 信用分 ---
class CreditResponse(BaseModel):
    user_id: int
    user_name: Optional[str] = None
    score: int
    tasks_posted: int
    tasks_completed: int
    tasks_reviewed: int
    on_time_rate: float
    acceptance_rate: float
    avg_quality_score: Optional[float]

    class Config:
        from_attributes = True


# --- 管理员审核 ---
class TaskReviewAction(BaseModel):
    """管理员审核任务"""
    action: str = Field(..., pattern=r"^(approve|reject)$")
    comment: Optional[str] = Field(None, description="审核意见")
