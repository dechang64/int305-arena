"""竞赛路由 — 竞赛列表、详情、数据集上传/下载"""
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models import Competition, CompStatus, Submission, User
from ..auth import get_current_user, require_admin, require_approved
from ..schemas import CompetitionCreate, CompetitionUpdate, CompetitionResponse

# [审计补丁 5/5] Competition.tags / .dataset_files 是 Text 列，但代码里当 list 用：
#   写入——init_db.py 传 ["回归",...]、create_competition 传 req.tags / dataset_files=[]，
#         sqlite3 无法绑定 list，报 InterfaceError: Error binding parameter 14，
#         整个事务回滚（后果：init_db.py 连管理员账号都建不出来）；
#   读取——列里存的是 JSON 字符串，直接喂给 response_model 的 List[str] 字段会校验失败。
# 读写两侧统一走 app.utils 的 jload/jdump。
from ..utils import jdump as _jdump, jload as _jload
from ..security import UnsafeFilenameError, is_answer_like, safe_filename, safe_join

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
            tags=_jload(c.tags, []), dataset_files=_jload(c.dataset_files, []),
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
        tags=_jload(comp.tags, []), dataset_files=_jload(comp.dataset_files, []),
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
        tags=_jdump(req.tags), dataset_files=_jdump([])
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
        if field == "tags" and value is not None:
            value = _jdump(value)
        setattr(comp, field, value)

    db.commit()
    db.refresh(comp)
    return _comp_to_response(db, comp)


@router.post("/{comp_id}/datasets", summary="上传竞赛数据集（管理员）")
async def upload_dataset(
    comp_id: int,
    file: UploadFile = File(...),
    kind: str = Form("public", description="public=训练/测试集(学生可下载)；answer=标准答案(不可下载)"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """上传数据集文件。

    * ``kind=public``（默认）：训练集 / 测试集 / 样例提交 → 存入 DATASET_DIR，
      登记进 ``competition.dataset_files``，学生登录后可下载；
    * ``kind=answer``：标准答案 → 存入 **ANSWERS_DIR**，**不登记**、**无下载端点**。

    传 answer 类文件名（``answer*.csv`` 等）而 ``kind=public`` 时会被自动改判为 answer，
    避免"手滑把答案放进可下载目录"这一类事故。
    """
    import aiofiles
    from ..config import DATASET_DIR, ANSWERS_DIR, MAX_UPLOAD_SIZE_MB

    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="竞赛不存在")

    # [审计补丁 S2] 客户端文件名不可信：先净化再用
    try:
        name = safe_filename(file.filename)
    except UnsafeFilenameError as e:
        raise HTTPException(status_code=400, detail=f"文件名不合法：{e}")

    is_answer = kind == "answer" or is_answer_like(name)
    root = ANSWERS_DIR if is_answer else DATASET_DIR

    # [审计补丁 S2] 先查大小再落盘，且落盘路径用 safe_join 断言未越界
    try:
        target = safe_join(root, str(comp_id), name)
    except UnsafeFilenameError as e:
        raise HTTPException(status_code=400, detail=f"非法存储路径：{e}")
    target.parent.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE_MB}MB)")

    async with aiofiles.open(target, "wb") as f:
        await f.write(content)

    if not is_answer:
        files = _jload(comp.dataset_files, [])
        if name not in files:
            files.append(name)
        comp.dataset_files = _jdump(files)
        db.commit()

    return {
        "filename": name,
        "size": len(content),
        "kind": "answer" if is_answer else "public",
        "downloadable": not is_answer,
    }


@router.get("/{comp_id}/datasets/{filename}", summary="下载数据集（需登录）")
def download_dataset(
    comp_id: int,
    filename: str,
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db)
):
    """兼容旧路径的数据集下载。

    实现已统一收敛到 ``app/routers/files.py``（白名单 + 答案类文件名拦截 + safe_join），
    本路由仅作为 /api/datasets/{comp_id}/{filename} 的别名保留，避免前端链接失效。
    """
    from fastapi.responses import FileResponse
    from .files import _resolve_dataset_file

    path = _resolve_dataset_file(db, comp_id, filename)
    return FileResponse(path=path, filename=path.name, media_type="application/octet-stream")


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
        tags=_jload(comp.tags, []), dataset_files=_jload(comp.dataset_files, []),
        participant_count=participant_count,
        top_score=top_score,
        created_at=comp.created_at
    )
