"""提交路由 — 上传预测、自动评分、提交历史"""
import json
from datetime import datetime, date
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models import Competition, CompStatus, Submission, User, DailySubmissionCount
from ..auth import get_current_user, require_approved
from ..config import UPLOAD_DIR, DATASET_DIR, MAX_UPLOAD_SIZE_MB
from ..evaluators.scorer import evaluate_submission, validate_prediction_format, EvaluationError
from ..schemas import SubmissionResponse, SubmissionResult

router = APIRouter(prefix="/submissions", tags=["提交"])


@router.post("/{comp_id}/submit", response_model=SubmissionResult, summary="提交预测结果")
async def submit_prediction(
    comp_id: int,
    prediction: UploadFile = File(..., description="预测文件 (CSV)"),
    code: Optional[UploadFile] = File(None, description="代码文件 (可选)"),
    description: Optional[str] = Form(None, description="提交说明"),
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db)
):
    """
    学生提交预测文件，系统自动评分

    流程:
    1. 验证竞赛状态和提交限制
    2. 保存预测文件
    3. 验证格式
    4. 自动评分
    5. 更新排行榜
    """
    # 1. 验证竞赛
    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="竞赛不存在")
    if comp.status != CompStatus.LIVE:
        raise HTTPException(status_code=400, detail="竞赛未开放提交")

    # 2. 检查提交限制
    today = date.today().isoformat()
    daily_count = db.query(DailySubmissionCount).filter(
        DailySubmissionCount.user_id == current_user.id,
        DailySubmissionCount.competition_id == comp_id,
        DailySubmissionCount.date == today
    ).first()

    today_count = daily_count.count if daily_count else 0
    if today_count >= comp.max_submissions_per_day:
        raise HTTPException(
            status_code=429,
            detail=f"今日提交次数已达上限 ({comp.max_submissions_per_day} 次/天)"
        )

    # 总提交次数
    total_count = db.query(Submission).filter(
        Submission.user_id == current_user.id,
        Submission.competition_id == comp_id
    ).count()
    if total_count >= comp.max_submissions_total:
        raise HTTPException(
            status_code=429,
            detail=f"总提交次数已达上限 ({comp.max_submissions_total} 次)"
        )

    # 3. 保存预测文件
    import aiofiles
    user_dir = UPLOAD_DIR / str(comp_id) / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    pred_filename = f"sub_{timestamp}_{prediction.filename}"
    pred_path = user_dir / pred_filename

    content = await prediction.read()
    if len(content) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE_MB}MB)")

    async with aiofiles.open(pred_path, "wb") as f:
        await f.write(content)

    # 4. 保存代码文件（可选）
    code_path = None
    if code:
        code_filename = f"code_{timestamp}_{code.filename}"
        code_filepath = user_dir / code_filename
        code_content = await code.read()
        async with aiofiles.open(code_filepath, "wb") as f:
            await f.write(code_content)
        code_path = str(code_filepath)

    # 5. 验证格式
    answer_path = DATASET_DIR / str(comp_id) / "answer.csv"
    if not answer_path.exists():
        raise HTTPException(status_code=500, detail="答案文件未配置，请联系管理员")

    is_valid, error_msg = validate_prediction_format(str(pred_path), str(answer_path))
    if not is_valid:
        # 仍然记录提交，但标记为无效
        sub = Submission(
            user_id=current_user.id,
            competition_id=comp_id,
            prediction_file=str(pred_path),
            code_file=code_path,
            description=description,
            is_valid=False,
            error_message=error_msg
        )
        db.add(sub)
        _increment_daily_count(db, current_user.id, comp_id, today, daily_count)
        db.commit()
        db.refresh(sub)

        return SubmissionResult(
            submission_id=sub.id,
            public_score=None,
            error_message=error_msg,
            remaining_submissions_today=comp.max_submissions_per_day - today_count - 1
        )

    # 6. 自动评分
    try:
        result = evaluate_submission(
            str(pred_path), str(answer_path),
            comp.metric, comp.metric_direction
        )
        public_score = result["score"]
        score_detail = result["detail"]

    except EvaluationError as e:
        sub = Submission(
            user_id=current_user.id,
            competition_id=comp_id,
            prediction_file=str(pred_path),
            code_file=code_path,
            description=description,
            is_valid=False,
            error_message=str(e)
        )
        db.add(sub)
        _increment_daily_count(db, current_user.id, comp_id, today, daily_count)
        db.commit()
        db.refresh(sub)

        return SubmissionResult(
            submission_id=sub.id,
            public_score=None,
            error_message=str(e),
            remaining_submissions_today=comp.max_submissions_per_day - today_count - 1
        )

    # 7. 保存有效提交
    sub = Submission(
        user_id=current_user.id,
        competition_id=comp_id,
        prediction_file=str(pred_path),
        code_file=code_path,
        description=description,
        public_score=public_score,
        score_detail=score_detail,
        is_valid=True
    )
    db.add(sub)
    _increment_daily_count(db, current_user.id, comp_id, today, daily_count)
    db.commit()
    db.refresh(sub)

    return SubmissionResult(
        submission_id=sub.id,
        public_score=public_score,
        error_message=None,
        remaining_submissions_today=comp.max_submissions_per_day - today_count - 1
    )


@router.get("/{comp_id}/my", response_model=list[SubmissionResponse], summary="我的提交历史")
def my_submissions(
    comp_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户在某竞赛的提交历史"""
    subs = db.query(Submission).filter(
        Submission.user_id == current_user.id,
        Submission.competition_id == comp_id
    ).order_by(Submission.created_at.desc()).all()

    return [SubmissionResponse(
        id=s.id, user_id=s.user_id, competition_id=s.competition_id,
        prediction_file=Path(s.prediction_file).name,
        code_file=Path(s.code_file).name if s.code_file else None,
        report_file=Path(s.report_file).name if s.report_file else None,
        description=s.description,
        public_score=s.public_score, private_score=s.private_score,
        score_detail=s.score_detail,
        is_valid=s.is_valid, error_message=s.error_message,
        created_at=s.created_at
    ) for s in subs]


@router.get("/{comp_id}/remaining", summary="查询剩余提交次数")
def remaining_submissions(
    comp_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="竞赛不存在")

    today = date.today().isoformat()
    daily_count = db.query(DailySubmissionCount).filter(
        DailySubmissionCount.user_id == current_user.id,
        DailySubmissionCount.competition_id == comp_id,
        DailySubmissionCount.date == today
    ).first()
    today_count = daily_count.count if daily_count else 0

    total_count = db.query(Submission).filter(
        Submission.user_id == current_user.id,
        Submission.competition_id == comp_id
    ).count()

    return {
        "remaining_today": comp.max_submissions_per_day - today_count,
        "remaining_total": comp.max_submissions_total - total_count,
        "max_per_day": comp.max_submissions_per_day,
        "max_total": comp.max_submissions_total
    }


def _increment_daily_count(db, user_id, comp_id, today_str, existing):
    if existing:
        existing.count += 1
    else:
        db.add(DailySubmissionCount(
            user_id=user_id, competition_id=comp_id,
            date=today_str, count=1
        ))
