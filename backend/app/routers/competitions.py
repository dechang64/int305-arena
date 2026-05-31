"""竞赛路由 — 竞赛列表、详情、数据集下载"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models import Competition, CompStatus, Submission, User
from ..auth import get_current_user, require_admin, require_approved
from ..schemas import CompetitionCreate, CompetitionUpdate, CompetitionResponse

router = APIRouter(prefix="/competitions", tags=["竞赛"])


@router.get("", response_model=List[CompetitionResponse], summary="获取竞赛列表")
def list_competitions(
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取所有竞赛，可按状态筛选"""
    query = db.query(Competition)
    if status:
        query = query.filter(Competition.status == status)
    competitions = query.order_by(Competition.week, Competition.id).all()

    result = []
    for c in competitions:
        # 统计参与人数
        participant_count = db.query(Submission.user_id).filter(
            Submission.competition_id == c.id
        ).distinct().count()

        # 获取最高分
        top_sub = _get_top_submission(db, c.id)
        top_score = top_sub.public_score if top_sub else c.baseline_score

        result.append(CompetitionResponse(
            id=c.id, slug=c.slug, title=c.title, subtitle=c.subtitle,
            description=c.description, lectures=c.lectures, week=c.week,
            metric=c.metric, metric_direction=c.metric_direction,
            baseline_score=c.baseline_score, status=c.status,
            start_time=c.start_time, end_time=c.end_time,
            max_submissions_per_day=c.max_submissions_per_day,
            max_submissions_total=c.max_submissions_total,
            tags=c.tags, dataset_files=c.dataset_files,
            participant_count=participant_count,
            top_score=top_score,
            created_at=c.created_at
        ))
    return result


@router.get("/{comp_id}", response_model=CompetitionResponse, summary="获取竞赛详情")
def get_competition(comp_id: int, db: Session = Depends(get_db)):
    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="竞赛不存在")

    participant_count = db.query(Submission.user_id).filter(
        Submission.competition_id == comp.id
    ).distinct().count()

    top_sub = _get_top_submission(db, comp.id)
    top_score = top_sub.public_score if top_sub else comp.baseline_score

    return CompetitionResponse(
        id=comp.id, slug=comp.slug, title=comp.title, subtitle=comp.subtitle,
        description=comp.description, lectures=comp.lectures, week=comp.week,
        metric=comp.metric, metric_direction=comp.metric_direction,
        baseline_score=comp.baseline_score, status=comp.status,
        start_time=comp.start_time, end_time=comp.end_time,
        max_submissions_per_day=comp.max_submissions_per_day,
        max_submissions_total=comp.max_submissions_total,
        tags=comp.tags, dataset_files=comp.dataset_files,
        participant_count=participant_count,
        top_score=top_score,
        created_at=comp.created_at
    )


@router.post("", response_model=CompetitionResponse, summary="创建竞赛（管理员）")
def create_competition(
    req: CompetitionCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    comp = Competition(
        slug=req.slug, title=req.title, subtitle=req.subtitle,
        description=req.description, lectures=req.lectures, week=req.week,
        metric=req.metric, metric_direction=req.metric_direction,
        baseline_score=req.baseline_score, status=CompStatus.UPCOMING,
        start_time=req.start_time, end_time=req.end_time,
        max_submissions_per_day=req.max_submissions_per_day,
        max_submissions_total=req.max_submissions_total,
        tags=req.tags, dataset_files=[]
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return _comp_to_response(db, comp)


@router.put("/{comp_id}", response_model=CompetitionResponse, summary="更新竞赛（管理员）")
def update_competition(
    comp_id: int,
    req: CompetitionUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="竞赛不存在")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(comp, field, value)

    db.commit()
    db.refresh(comp)
    return _comp_to_response(db, comp)


@router.post("/{comp_id}/datasets", summary="上传竞赛数据集（管理员）")
async def upload_dataset(
    comp_id: int,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """上传数据集文件（训练集、测试集、样例提交等）"""
    import aiofiles
    from ..config import DATASET_DIR

    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="竞赛不存在")

    # 保存文件
    comp_dir = DATASET_DIR / str(comp_id)
    comp_dir.mkdir(parents=True, exist_ok=True)
    file_path = comp_dir / file.filename

    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # 更新竞赛的数据集列表
    files = comp.dataset_files or []
    if file.filename not in files:
        files.append(file.filename)
    comp.dataset_files = files
    db.commit()

    return {"filename": file.filename, "size": len(content)}


@router.get("/{comp_id}/datasets/{filename}", summary="下载数据集")
def download_dataset(
    comp_id: int,
    filename: str,
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db)
):
    from fastapi.responses import FileResponse
    from ..config import DATASET_DIR

    file_path = DATASET_DIR / str(comp_id) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


# ===== 辅助函数 =====

def _get_top_submission(db: Session, comp_id: int):
    """获取竞赛最高分提交"""
    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        return None

    direction = comp.metric_direction
    order = Submission.public_score.desc() if direction == "higher" else Submission.public_score.asc()

    return db.query(Submission).filter(
        Submission.competition_id == comp_id,
        Submission.is_valid == True,
        Submission.public_score.isnot(None)
    ).order_by(order).first()


def _comp_to_response(db: Session, comp: Competition) -> CompetitionResponse:
    participant_count = db.query(Submission.user_id).filter(
        Submission.competition_id == comp.id
    ).distinct().count()

    top_sub = _get_top_submission(db, comp.id)
    top_score = top_sub.public_score if top_sub else comp.baseline_score

    return CompetitionResponse(
        id=comp.id, slug=comp.slug, title=comp.title, subtitle=comp.subtitle,
        description=comp.description, lectures=comp.lectures, week=comp.week,
        metric=comp.metric, metric_direction=comp.metric_direction,
        baseline_score=comp.baseline_score, status=comp.status,
        start_time=comp.start_time, end_time=comp.end_time,
        max_submissions_per_day=comp.max_submissions_per_day,
        max_submissions_total=comp.max_submissions_total,
        tags=comp.tags, dataset_files=comp.dataset_files,
        participant_count=participant_count,
        top_score=top_score,
        created_at=comp.created_at
    )
