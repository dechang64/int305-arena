"""文件下载路由 —— 取代原先两处无鉴权的 StaticFiles 挂载。

原实现（审计 S1 / S4）：

    app.mount("/api/uploads",  StaticFiles(directory=UPLOAD_DIR))
    app.mount("/api/datasets", StaticFiles(directory=DATASET_DIR))

本模块提供**同路径的带鉴权版本**，前端无需改 URL：

* ``GET /api/datasets/{comp_id}/{filename}``  —— 需登录；文件名必须在竞赛
  ``dataset_files`` 白名单内；答案类文件名一律 404（双重防线，见 :func:`is_answer_like`）。
* ``GET /api/uploads/deliveries/{task_id}/{filename}`` —— 需登录；仅出题者、
  交付者本人与管理员可下载。

标准答案文件不存在于以上任一目录（见 ``config.ANSWERS_DIR``），也没有任何下载端点。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_approved
from ..config import DATASET_DIR, UPLOAD_DIR
from ..database import get_db
from ..models import Competition, Task, TaskDelivery, User, UserRole
from ..security import UnsafeFilenameError, is_answer_like, safe_filename, safe_join
from ..utils import jload

router = APIRouter(tags=["文件"])

_NOT_FOUND = HTTPException(status_code=404, detail="文件不存在")


def _resolve_dataset_file(db: Session, comp_id: int, filename: str) -> Path:
    """定位一个可下载的数据集文件，任何一步不通过都返回 404。"""
    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        raise _NOT_FOUND

    try:
        name = safe_filename(filename)
    except UnsafeFilenameError:
        raise _NOT_FOUND

    # 双重防线：即便管理员误把答案传进了 datasets 目录，这里也不放行
    if is_answer_like(name):
        raise _NOT_FOUND

    # 只允许下载竞赛登记过的文件（防止枚举目录）
    if name not in (jload(comp.dataset_files, []) or []):
        raise _NOT_FOUND

    try:
        path = safe_join(DATASET_DIR, str(comp_id), name)
    except UnsafeFilenameError:
        raise _NOT_FOUND

    if not path.is_file():
        raise _NOT_FOUND
    return path


@router.get("/datasets/{comp_id}/{filename}", summary="下载数据集文件（需登录）")
def download_dataset(
    comp_id: int,
    filename: str,
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db),
):
    path = _resolve_dataset_file(db, comp_id, filename)
    return FileResponse(path=path, filename=path.name, media_type="application/octet-stream")


@router.get("/uploads/deliveries/{task_id}/{filename}", summary="下载交付物附件（限出题者/交付者/管理员）")
def download_delivery_attachment(
    task_id: int,
    filename: str,
    current_user: User = Depends(require_approved),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise _NOT_FOUND

    try:
        name = safe_filename(filename)
        path = safe_join(UPLOAD_DIR, "deliveries", str(task_id), name)
    except UnsafeFilenameError:
        raise _NOT_FOUND

    # 必须真的存在这条交付记录，且文件名与登记的一致
    delivery = db.query(TaskDelivery).filter(
        TaskDelivery.task_id == task_id,
        TaskDelivery.attachment.isnot(None),
    ).all()

    recorded = {Path(d.attachment).name for d in delivery if d.attachment}
    if name not in recorded:
        raise _NOT_FOUND

    is_owner = task.owner_id == current_user.id
    is_applicant = any(d.applicant_id == current_user.id and Path(d.attachment).name == name
                       for d in delivery if d.attachment)
    is_admin = current_user.role == UserRole.ADMIN
    if not (is_owner or is_applicant or is_admin):
        raise HTTPException(status_code=403, detail="无权下载该附件")

    if not path.is_file():
        raise _NOT_FOUND
    return FileResponse(path=path, filename=path.name, media_type="application/octet-stream")
