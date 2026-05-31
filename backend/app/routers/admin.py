"""管理后台路由 — 用户审核、成绩导出、竞赛管理"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
import io
import csv

from ..database import get_db
from ..models import User, UserRole, UserStatus, Competition, Submission, CompStatus
from ..auth import require_admin
from ..schemas import UserAdminView, UserApproveRequest, GradeExport

router = APIRouter(prefix="/admin", tags=["管理后台"])


@router.get("/users", response_model=List[UserAdminView], summary="获取用户列表")
def list_users(
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员查看所有用户，可按状态筛选、搜索"""
    query = db.query(User)

    if status:
        query = query.filter(User.status == status)
    if search:
        query = query.filter(
            (User.name.contains(search)) |
            (User.email.contains(search)) |
            (User.student_id.contains(search))
        )

    users = query.order_by(User.created_at.desc())\
                 .offset((page - 1) * page_size)\
                 .limit(page_size).all()

    result = []
    for u in users:
        sub_count = db.query(Submission).filter(Submission.user_id == u.id).count()
        result.append(UserAdminView(
            id=u.id, email=u.email, name=u.name,
            student_id=u.student_id, role=u.role, status=u.status,
            team=u.team, created_at=u.created_at,
            last_login=u.last_login, submission_count=sub_count
        ))
    return result


@router.post("/users/approve", summary="审核用户（通过/拒绝）")
def approve_user(
    req: UserApproveRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.status = UserStatus.APPROVED if req.action == "approve" else UserStatus.REJECTED
    db.commit()
    return {"user_id": user.id, "status": user.status}


@router.post("/users/batch-approve", summary="批量审核通过")
def batch_approve(
    user_ids: List[int],
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    db.query(User).filter(User.id.in_(user_ids)).update(
        {"status": UserStatus.APPROVED}, synchronize_session=False
    )
    db.commit()
    return {"approved_count": len(user_ids)}


@router.get("/stats", summary="平台统计数据")
def platform_stats(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    total_users = db.query(User).filter(User.role == UserRole.STUDENT).count()
    approved_users = db.query(User).filter(
        User.role == UserRole.STUDENT, User.status == UserStatus.APPROVED
    ).count()
    pending_users = db.query(User).filter(
        User.role == UserRole.STUDENT, User.status == UserStatus.PENDING
    ).count()
    total_submissions = db.query(Submission).count()
    active_competitions = db.query(Competition).filter(Competition.status == CompStatus.LIVE).count()

    return {
        "total_users": total_users,
        "approved_users": approved_users,
        "pending_users": pending_users,
        "total_submissions": total_submissions,
        "active_competitions": active_competitions
    }


@router.get("/grades/export", summary="导出成绩表 (CSV)")
def export_grades(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    导出最终成绩表

    评分公式:
    - 竞赛排名分 (60%): 每场竞赛归一化排名分 = 40 + 60 * (N - rank) / N
    - 进步奖励分 (20%): 首次提交 vs 最佳提交的改进幅度
    - 代码报告分 (15%): 由管理员手动评分
    - 社区贡献分 (5%): 由管理员手动评分
    """
    competitions = db.query(Competition).all()
    students = db.query(User).filter(
        User.role == UserRole.STUDENT,
        User.status == UserStatus.APPROVED
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # 表头
    header = ["学号", "姓名", "邮箱"]
    comp_scores = {}
    for c in competitions:
        header.append(f"{c.title}({c.metric})")
        header.append(f"{c.title}_排名")
        # 预计算每场竞赛的排名
        comp_scores[c.id] = _compute_rankings(db, c)

    header.extend(["竞赛排名分(60%)", "进步奖励分(20%)", "代码报告分(15%)", "社区贡献分(5%)", "最终成绩"])
    writer.writerow(header)

    for student in students:
        row = [student.student_id, student.name, student.email]
        rank_scores = []

        for c in competitions:
            ranking = comp_scores.get(c.id, {})
            if student.id in ranking:
                score, rank, total = ranking[student.id]
                row.append(f"{score:.4f}")
                row.append(f"{rank}/{total}")
                # 归一化排名分
                if total > 1:
                    normalized = 40 + 60 * (total - rank) / (total - 1)
                else:
                    normalized = 70
                rank_scores.append(normalized)
            else:
                row.append("未参与")
                row.append("-")
                rank_scores.append(0)

        # 竞赛排名分 (60%)
        avg_rank_score = sum(rank_scores) / len(rank_scores) if rank_scores else 0
        competition_grade = avg_rank_score * 0.6

        # 进步奖励分 (20%) - 简化：基于提交次数
        total_subs = db.query(Submission).filter(
            Submission.user_id == student.id,
            Submission.is_valid == True
        ).count()
        improvement_grade = min(total_subs * 2, 20)  # 每次有效提交2分，上限20

        row.append(f"{competition_grade:.1f}")
        row.append(f"{improvement_grade:.1f}")
        row.append("")  # 代码报告分（手动填写）
        row.append("")  # 社区贡献分（手动填写）
        row.append(f"{competition_grade + improvement_grade:.1f}")

        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=INT305_grades_{datetime.now().strftime('%Y%m%d')}.csv"
        }
    )


@router.get("/submissions/recent", summary="最近提交记录")
def recent_submissions(
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    subs = db.query(Submission, User.name, Competition.title)\
        .join(User, User.id == Submission.user_id)\
        .join(Competition, Competition.id == Submission.competition_id)\
        .order_by(Submission.created_at.desc())\
        .limit(limit).all()

    return [{
        "submission_id": s.id,
        "student_name": name,
        "competition_title": title,
        "public_score": s.public_score,
        "is_valid": s.is_valid,
        "error_message": s.error_message,
        "created_at": s.created_at.isoformat() if s.created_at else None
    } for s, name, title in subs]


def _compute_rankings(db: Session, comp: Competition) -> dict:
    """计算某场竞赛的排名"""
    direction = comp.metric_direction

    if direction == "higher":
        best_scores = db.query(
            Submission.user_id,
            func.max(Submission.public_score).label("best")
        ).filter(
            Submission.competition_id == comp.id,
            Submission.is_valid == True
        ).group_by(Submission.user_id).all()
        best_scores.sort(key=lambda x: x.best, reverse=True)
    else:
        best_scores = db.query(
            Submission.user_id,
            func.min(Submission.public_score).label("best")
        ).filter(
            Submission.competition_id == comp.id,
            Submission.is_valid == True
        ).group_by(Submission.user_id).all()
        best_scores.sort(key=lambda x: x.best)

    total = len(best_scores)
    result = {}
    for rank, (user_id, best_score) in enumerate(best_scores, start=1):
        result[user_id] = (best_score, rank, total)

    return result
