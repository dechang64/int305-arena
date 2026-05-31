"""任务市场路由 — 发布、浏览、申请、交付、验收、信用"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models import (
    User, Task, TaskApplication, TaskDelivery, CreditScore,
    TaskStatus, ApplicationStatus, DeliveryStatus, UserRole
)
from ..auth import get_current_user, require_admin, require_approved
from ..schemas import (
    TaskCreate, TaskUpdate, TaskResponse, TaskBrief,
    ApplicationCreate, ApplicationResponse, ApplicationAction,
    DeliveryCreate, DeliveryResponse, DeliveryReview,
    CreditResponse, TaskReviewAction
)

router = APIRouter(prefix="/market", tags=["任务市场"])

# ===== 类别映射 =====
CATEGORY_LABELS = {
    "data_pipeline": "数据预处理",
    "model_training": "模型训练",
    "visualization": "可视化",
    "api_service": "API/Docker",
    "baseline_repo": "基线复现",
    "testing_bench": "测试/Benchmark",
    "other": "其他",
}

DIFFICULTY_LABELS = {"easy": "简单", "medium": "中等", "hard": "困难"}


# ===== 辅助函数 =====

def _get_or_create_credit(db: Session, user_id: int) -> CreditScore:
    """获取或创建用户信用记录"""
    credit = db.query(CreditScore).filter(CreditScore.user_id == user_id).first()
    if not credit:
        credit = CreditScore(user_id=user_id)
        db.add(credit)
        db.commit()
        db.refresh(credit)
    return credit


def _task_to_response(db: Session, task: Task) -> TaskResponse:
    """Task ORM 对象转 TaskResponse"""
    owner = db.query(User).filter(User.id == task.owner_id).first()
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        category=task.category,
        owner_id=task.owner_id,
        owner_name=owner.name if owner else None,
        owner_team=owner.team if owner else None,
        thesis_title=task.thesis_title,
        thesis_advisor=task.thesis_advisor,
        deliverables=json.loads(task.deliverables) if task.deliverables else [],
        acceptance_criteria=task.acceptance_criteria,
        difficulty=task.difficulty,
        estimated_hours=task.estimated_hours,
        data_description=task.data_description,
        data_availability=task.data_availability,
        resource_links=json.loads(task.resource_links) if task.resource_links else [],
        status=task.status,
        deadline=task.deadline,
        tags=json.loads(task.tags) if task.tags else [],
        view_count=task.view_count,
        application_count=task.application_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _task_to_brief(db: Session, task: Task) -> TaskBrief:
    """Task ORM 对象转 TaskBrief"""
    owner = db.query(User).filter(User.id == task.owner_id).first()
    return TaskBrief(
        id=task.id,
        title=task.title,
        category=task.category,
        difficulty=task.difficulty,
        status=task.status,
        owner_name=owner.name if owner else None,
        estimated_hours=task.estimated_hours,
        application_count=task.application_count,
        tags=json.loads(task.tags) if task.tags else [],
        deadline=task.deadline,
        created_at=task.created_at,
    )


def _update_credit_on_delivery_accept(db: Session, applicant_id: int, owner_id: int, quality_score: Optional[int]):
    """验收通过时更新双方信用"""
    # 更新做题者信用
    credit = _get_or_create_credit(db, applicant_id)
    credit.tasks_completed += 1
    if quality_score:
        old_total = credit.avg_quality_score * (credit.tasks_completed - 1) if credit.avg_quality_score else 0
        credit.avg_quality_score = (old_total + quality_score) / credit.tasks_completed
    credit.score = min(200, credit.score + 5)  # 完成任务 +5 分

    # 更新出题者信用
    owner_credit = _get_or_create_credit(db, owner_id)
    owner_credit.tasks_reviewed += 1
    owner_credit.score = min(200, owner_credit.score + 3)  # 认真验收 +3 分

    db.commit()


def _update_credit_on_delivery_reject(db: Session, applicant_id: int):
    """验收拒绝时扣减做题者信用"""
    credit = _get_or_create_credit(db, applicant_id)
    credit.score = max(0, credit.score - 5)  # 验收未通过 -5 分
    db.commit()


# ===== 任务 CRUD =====

@router.get("/tasks", response_model=List[TaskBrief], summary="浏览任务市场")
def list_tasks(
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """浏览任务市场，支持按类别/难度/状态/关键词筛选"""
    query = db.query(Task)

    if category:
        query = query.filter(Task.category == category)
    if difficulty:
        query = query.filter(Task.difficulty == difficulty)
    if status:
        query = query.filter(Task.status == status)
    else:
        # 默认只显示开放和进行中的
        query = query.filter(Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]))
    if keyword:
        query = query.filter(Task.title.contains(keyword))

    tasks = query.order_by(Task.created_at.desc()).limit(100).all()
    return [_task_to_brief(db, t) for t in tasks]


@router.get("/tasks/all", response_model=List[TaskBrief], summary="浏览所有任务（含待审核）")
def list_all_tasks(
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """浏览所有状态的任务"""
    query = db.query(Task)
    if category:
        query = query.filter(Task.category == category)
    if status:
        query = query.filter(Task.status == status)
    tasks = query.order_by(Task.created_at.desc()).limit(200).all()
    return [_task_to_brief(db, t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="查看任务详情")
def get_task(task_id: int, db: Session = Depends(get_db)):
    """查看任务详情，自动增加浏览量"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 增加浏览量
    task.view_count += 1
    db.commit()

    return _task_to_response(db, task)


@router.post("/tasks", response_model=TaskResponse, summary="发布任务")
def create_task(
    req: TaskCreate,
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db),
):
    """学生从毕设中拆出ML任务发布到市场"""
    # 验证 category
    valid_categories = [e.value for e in Task.__table__.columns if False]  # hack
    valid_categories = ["data_pipeline", "model_training", "visualization",
                        "api_service", "baseline_repo", "testing_bench", "other"]
    if req.category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"无效的任务类别，可选: {valid_categories}")

    # 验证 difficulty
    if req.difficulty not in ["easy", "medium", "hard"]:
        raise HTTPException(status_code=400, detail="难度必须为 easy/medium/hard")

    task = Task(
        title=req.title,
        description=req.description,
        category=req.category,
        owner_id=current_user.id,
        thesis_title=req.thesis_title,
        thesis_advisor=req.thesis_advisor,
        deliverables=json.dumps(req.deliverables, ensure_ascii=False),
        acceptance_criteria=req.acceptance_criteria,
        difficulty=req.difficulty,
        estimated_hours=req.estimated_hours,
        data_description=req.data_description,
        data_availability=req.data_availability,
        resource_links=json.dumps(req.resource_links, ensure_ascii=False) if req.resource_links else None,
        status=TaskStatus.PENDING,  # 需要管理员审核
        deadline=req.deadline,
        tags=json.dumps(req.tags, ensure_ascii=False) if req.tags else None,
    )
    db.add(task)

    # 更新出题者信用
    credit = _get_or_create_credit(db, current_user.id)
    credit.tasks_posted += 1
    db.commit()
    db.refresh(task)

    return _task_to_response(db, task)


@router.put("/tasks/{task_id}", response_model=TaskResponse, summary="修改任务")
def update_task(
    task_id: int,
    req: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """出题者修改自己的任务（仅限待审核状态）"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能修改自己发布的任务")
    if task.status not in [TaskStatus.PENDING, TaskStatus.REJECTED_ADMIN]:
        raise HTTPException(status_code=400, detail="只能修改待审核或被拒的任务")

    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in ("deliverables", "resource_links", "tags") and value is not None:
            setattr(task, field, json.dumps(value, ensure_ascii=False))
        else:
            setattr(task, field, value)

    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return _task_to_response(db, task)


@router.delete("/tasks/{task_id}", summary="取消任务")
def cancel_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """出题者取消自己的任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能取消自己发布的任务")
    if task.status == TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="已完成的任务不能取消")

    task.status = TaskStatus.CANCELLED
    db.commit()
    return {"message": "任务已取消"}


# ===== 管理员审核 =====

@router.get("/tasks/pending/list", response_model=List[TaskBrief], summary="待审核任务列表（管理员）")
def list_pending_tasks(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员查看待审核的任务"""
    tasks = db.query(Task).filter(Task.status == TaskStatus.PENDING).order_by(Task.created_at).all()
    return [_task_to_brief(db, t) for t in tasks]


@router.post("/tasks/{task_id}/review", summary="审核任务（管理员）")
def review_task(
    task_id: int,
    req: TaskReviewAction,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员审核任务：通过则上架，拒绝则退回"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=400, detail="只能审核待审核状态的任务")

    if req.action == "approve":
        task.status = TaskStatus.OPEN
    else:
        task.status = TaskStatus.REJECTED_ADMIN

    task.updated_at = datetime.utcnow()
    db.commit()
    return {"message": f"任务已{'通过审核并上架' if req.action == 'approve' else '拒绝'}"}


# ===== 申请接单 =====

@router.post("/tasks/{task_id}/apply", response_model=ApplicationResponse, summary="申请接单")
def apply_for_task(
    task_id: int,
    req: ApplicationCreate,
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db),
):
    """学生申请接单"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.OPEN:
        raise HTTPException(status_code=400, detail="该任务当前不接受申请")
    if task.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能申请自己发布的任务")

    # 检查是否已申请
    existing = db.query(TaskApplication).filter(
        TaskApplication.task_id == task_id,
        TaskApplication.applicant_id == current_user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="你已经申请过该任务")

    # 检查信用分
    credit = _get_or_create_credit(db, current_user.id)
    if credit.score < 30:
        raise HTTPException(status_code=400, detail="信用分过低，无法接单（低于30分）")

    application = TaskApplication(
        task_id=task_id,
        applicant_id=current_user.id,
        message=req.message,
        proposed_approach=req.proposed_approach,
    )
    db.add(application)

    task.application_count += 1
    db.commit()
    db.refresh(application)

    # 构造响应
    return ApplicationResponse(
        id=application.id,
        task_id=application.task_id,
        applicant_id=application.applicant_id,
        applicant_name=current_user.name,
        applicant_team=current_user.team,
        applicant_credit=credit.score,
        message=application.message,
        proposed_approach=application.proposed_approach,
        status=application.status,
        created_at=application.created_at,
    )


@router.get("/tasks/{task_id}/applications", response_model=List[ApplicationResponse], summary="查看任务申请列表")
def list_applications(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """出题者查看自己任务的申请列表"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能查看自己任务的申请")

    applications = db.query(TaskApplication).filter(
        TaskApplication.task_id == task_id
    ).order_by(TaskApplication.created_at).all()

    result = []
    for app in applications:
        applicant = db.query(User).filter(User.id == app.applicant_id).first()
        credit = db.query(CreditScore).filter(CreditScore.user_id == app.applicant_id).first()
        result.append(ApplicationResponse(
            id=app.id,
            task_id=app.task_id,
            applicant_id=app.applicant_id,
            applicant_name=applicant.name if applicant else None,
            applicant_team=applicant.team if applicant else None,
            applicant_credit=credit.score if credit else 100,
            message=app.message,
            proposed_approach=app.proposed_approach,
            status=app.status,
            created_at=app.created_at,
        ))
    return result


@router.post("/applications/{app_id}/action", summary="接受/拒绝申请")
def handle_application(
    app_id: int,
    req: ApplicationAction,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """出题者接受或拒绝申请"""
    application = db.query(TaskApplication).filter(TaskApplication.id == app_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")

    task = db.query(Task).filter(Task.id == application.task_id).first()
    if task.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能操作自己任务的申请")

    if application.status != ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="该申请已处理")

    if req.action == "accept":
        application.status = ApplicationStatus.ACCEPTED
        task.status = TaskStatus.IN_PROGRESS
        # 拒绝其他申请
        other_apps = db.query(TaskApplication).filter(
            TaskApplication.task_id == task.id,
            TaskApplication.id != app_id,
            TaskApplication.status == ApplicationStatus.PENDING,
        ).all()
        for other in other_apps:
            other.status = ApplicationStatus.REJECTED
    else:
        application.status = ApplicationStatus.REJECTED

    db.commit()
    return {"message": f"申请已{'接受' if req.action == 'accept' else '拒绝'}"}


@router.post("/applications/{app_id}/withdraw", summary="撤回申请")
def withdraw_application(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """申请者撤回自己的申请"""
    application = db.query(TaskApplication).filter(TaskApplication.id == app_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")
    if application.applicant_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能撤回自己的申请")
    if application.status != ApplicationStatus.PENDING:
        raise HTTPException(status_code=400, detail="只能撤回待处理的申请")

    application.status = ApplicationStatus.WITHDRAWN
    db.commit()
    return {"message": "申请已撤回"}


# ===== 交付 =====

@router.post("/tasks/{task_id}/deliver", response_model=DeliveryResponse, summary="提交交付物")
def submit_delivery(
    task_id: int,
    req: DeliveryCreate,
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db),
):
    """做题者提交交付物"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="任务不在进行中状态")

    # 验证当前用户是被接受的申请者
    accepted_app = db.query(TaskApplication).filter(
        TaskApplication.task_id == task_id,
        TaskApplication.applicant_id == current_user.id,
        TaskApplication.status == ApplicationStatus.ACCEPTED,
    ).first()
    if not accepted_app:
        raise HTTPException(status_code=403, detail="你不是该任务的被接受申请者")

    delivery = TaskDelivery(
        task_id=task_id,
        applicant_id=current_user.id,
        code_url=req.code_url,
        demo_url=req.demo_url,
        documentation=req.documentation,
    )
    db.add(delivery)

    task.status = TaskStatus.UNDER_REVIEW
    db.commit()
    db.refresh(delivery)

    return DeliveryResponse(
        id=delivery.id,
        task_id=delivery.task_id,
        applicant_id=delivery.applicant_id,
        applicant_name=current_user.name,
        code_url=delivery.code_url,
        demo_url=delivery.demo_url,
        documentation=delivery.documentation,
        attachment=delivery.attachment,
        review_status=delivery.review_status,
        review_comment=delivery.review_comment,
        quality_score=delivery.quality_score,
        created_at=delivery.created_at,
        reviewed_at=delivery.reviewed_at,
    )


@router.post("/tasks/{task_id}/deliver/upload", summary="上传交付物附件")
async def upload_delivery_attachment(
    task_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db),
):
    """上传交付物附件（代码压缩包等）"""
    import aiofiles
    from ..config import UPLOAD_DIR

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 查找最近的交付记录
    delivery = db.query(TaskDelivery).filter(
        TaskDelivery.task_id == task_id,
        TaskDelivery.applicant_id == current_user.id,
    ).order_by(TaskDelivery.created_at.desc()).first()
    if not delivery:
        raise HTTPException(status_code=400, detail="请先提交交付物信息")

    # 保存文件
    task_dir = UPLOAD_DIR / "deliveries" / str(task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    file_path = task_dir / f"{current_user.id}_{file.filename}"

    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    delivery.attachment = str(file_path)
    db.commit()

    return {"filename": file.filename, "size": len(content)}


@router.get("/tasks/{task_id}/deliveries", response_model=List[DeliveryResponse], summary="查看交付物列表")
def list_deliveries(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """出题者查看交付物"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能查看自己任务的交付物")

    deliveries = db.query(TaskDelivery).filter(
        TaskDelivery.task_id == task_id
    ).order_by(TaskDelivery.created_at.desc()).all()

    result = []
    for d in deliveries:
        applicant = db.query(User).filter(User.id == d.applicant_id).first()
        result.append(DeliveryResponse(
            id=d.id,
            task_id=d.task_id,
            applicant_id=d.applicant_id,
            applicant_name=applicant.name if applicant else None,
            code_url=d.code_url,
            demo_url=d.demo_url,
            documentation=d.documentation,
            attachment=d.attachment,
            review_status=d.review_status,
            review_comment=d.review_comment,
            quality_score=d.quality_score,
            created_at=d.created_at,
            reviewed_at=d.reviewed_at,
        ))
    return result


@router.post("/deliveries/{delivery_id}/review", summary="验收交付物")
def review_delivery(
    delivery_id: int,
    req: DeliveryReview,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """出题者验收交付物：通过/需修改/拒绝"""
    delivery = db.query(TaskDelivery).filter(TaskDelivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="交付物不存在")

    task = db.query(Task).filter(Task.id == delivery.task_id).first()
    if task.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能验收自己任务的交付物")

    if delivery.review_status not in [DeliveryStatus.SUBMITTED, DeliveryStatus.REVISION]:
        raise HTTPException(status_code=400, detail="该交付物已验收")

    delivery.review_comment = req.comment
    delivery.reviewed_at = datetime.utcnow()

    if req.action == "accept":
        delivery.review_status = DeliveryStatus.ACCEPTED
        delivery.quality_score = req.quality_score
        task.status = TaskStatus.COMPLETED
        _update_credit_on_delivery_accept(db, delivery.applicant_id, task.owner_id, req.quality_score)
    elif req.action == "revision":
        delivery.review_status = DeliveryStatus.REVISION
        task.status = TaskStatus.IN_PROGRESS  # 回到进行中，等待修改后重新提交
    else:  # reject
        delivery.review_status = DeliveryStatus.REJECTED
        task.status = TaskStatus.IN_PROGRESS  # 回到进行中，允许重新提交
        _update_credit_on_delivery_reject(db, delivery.applicant_id)

    db.commit()
    return {"message": f"交付物已{'通过验收' if req.action == 'accept' else '要求修改' if req.action == 'revision' else '拒绝'}"}


# ===== 信用分 =====

@router.get("/credit/me", response_model=CreditResponse, summary="查看我的信用分")
def get_my_credit(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看当前用户的信用分"""
    credit = _get_or_create_credit(db, current_user.id)
    return CreditResponse(
        user_id=credit.user_id,
        user_name=current_user.name,
        score=credit.score,
        tasks_posted=credit.tasks_posted,
        tasks_completed=credit.tasks_completed,
        tasks_reviewed=credit.tasks_reviewed,
        on_time_rate=credit.on_time_rate,
        acceptance_rate=credit.acceptance_rate,
        avg_quality_score=credit.avg_quality_score,
    )


@router.get("/credit/leaderboard", response_model=List[CreditResponse], summary="信用排行榜")
def credit_leaderboard(db: Session = Depends(get_db)):
    """信用分排行榜"""
    credits = db.query(CreditScore).order_by(CreditScore.score.desc()).limit(50).all()
    result = []
    for c in credits:
        user = db.query(User).filter(User.id == c.user_id).first()
        result.append(CreditResponse(
            user_id=c.user_id,
            user_name=user.name if user else None,
            score=c.score,
            tasks_posted=c.tasks_posted,
            tasks_completed=c.tasks_completed,
            tasks_reviewed=c.tasks_reviewed,
            on_time_rate=c.on_time_rate,
            acceptance_rate=c.acceptance_rate,
            avg_quality_score=c.avg_quality_score,
        ))
    return result


# ===== 我的任务 =====

@router.get("/my/posted", response_model=List[TaskBrief], summary="我发布的任务")
def my_posted_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看我发布的所有任务"""
    tasks = db.query(Task).filter(Task.owner_id == current_user.id).order_by(Task.created_at.desc()).all()
    return [_task_to_brief(db, t) for t in tasks]


@router.get("/my/applied", response_model=List[dict], summary="我申请的任务")
def my_applied_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看我申请的所有任务及状态"""
    applications = db.query(TaskApplication).filter(
        TaskApplication.applicant_id == current_user.id
    ).order_by(TaskApplication.created_at.desc()).all()

    result = []
    for app in applications:
        task = db.query(Task).filter(Task.id == app.task_id).first()
        if task:
            result.append({
                "application_id": app.id,
                "task_id": task.id,
                "task_title": task.title,
                "task_category": task.category,
                "task_status": task.status,
                "application_status": app.status,
                "applied_at": app.created_at.isoformat() if app.created_at else None,
            })
    return result


# ===== 统计 =====

@router.get("/stats", summary="任务市场统计")
def market_stats(db: Session = Depends(get_db)):
    """任务市场整体统计"""
    total_tasks = db.query(Task).count()
    open_tasks = db.query(Task).filter(Task.status == TaskStatus.OPEN).count()
    in_progress = db.query(Task).filter(Task.status == TaskStatus.IN_PROGRESS).count()
    completed = db.query(Task).filter(Task.status == TaskStatus.COMPLETED).count()
    pending_review = db.query(Task).filter(Task.status == TaskStatus.PENDING).count()

    # 按类别统计
    category_stats = {}
    for cat_key, cat_label in CATEGORY_LABELS.items():
        count = db.query(Task).filter(Task.category == cat_key).count()
        if count > 0:
            category_stats[cat_key] = {"label": cat_label, "count": count}

    return {
        "total_tasks": total_tasks,
        "open_tasks": open_tasks,
        "in_progress": in_progress,
        "completed": completed,
        "pending_review": pending_review,
        "category_stats": category_stats,
    }
