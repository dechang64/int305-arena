"""排行榜路由 — 实时排名、趋势"""
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc
from typing import List, Optional

from ..database import get_db
from ..models import Competition, Submission, User
from ..schemas import LeaderboardEntry

router = APIRouter(prefix="/leaderboard", tags=["排行榜"])


@router.get("/{comp_id}", response_model=List[LeaderboardEntry], summary="获取竞赛排行榜")
def get_leaderboard(
    comp_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    获取竞赛排行榜

    排名规则:
    - 每个学生取最高分的一次提交
    - 按分数排序（metric_direction 决定升序/降序）
    - 同分按提交时间排序（早提交排前）
    """
    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="竞赛不存在")

    # 获取每个用户的最佳提交
    direction = comp.metric_direction
    if direction == "higher":
        best_per_user = db.query(
            Submission.user_id,
            func.max(Submission.public_score).label("best_score")
        ).filter(
            Submission.competition_id == comp_id,
            Submission.is_valid == True,
            Submission.public_score.isnot(None)
        ).group_by(Submission.user_id).subquery()

        # 获取最佳提交的详细信息
        order_clause = desc("best_score")
    else:
        best_per_user = db.query(
            Submission.user_id,
            func.min(Submission.public_score).label("best_score")
        ).filter(
            Submission.competition_id == comp_id,
            Submission.is_valid == True,
            Submission.public_score.isnot(None)
        ).group_by(Submission.user_id).subquery()

        order_clause = asc("best_score")

    # 获取用户信息和提交数
    results = db.query(
        best_per_user.c.user_id,
        best_per_user.c.best_score,
        User.name,
        User.team,
        User.avatar_color,
    ).join(User, User.id == best_per_user.c.user_id)\
     .order_by(order_clause, asc("best_score") if direction == "lower" else desc("best_score"))\
     .offset((page - 1) * page_size)\
     .limit(page_size)\
     .all()

    # 获取每个用户的提交数和最后提交时间
    entries = []
    for rank, (user_id, best_score, name, team, avatar_color) in enumerate(results, start=(page - 1) * page_size + 1):
        sub_count = db.query(Submission).filter(
            Submission.user_id == user_id,
            Submission.competition_id == comp_id,
            Submission.is_valid == True
        ).count()

        last_sub = db.query(Submission).filter(
            Submission.user_id == user_id,
            Submission.competition_id == comp_id,
            Submission.is_valid == True
        ).order_by(Submission.created_at.desc()).first()

        entries.append(LeaderboardEntry(
            rank=rank,
            user_id=user_id,
            name=name,
            team=team,
            avatar_color=avatar_color,
            best_score=round(best_score, 6),
            submission_count=sub_count,
            last_submission_time=last_sub.created_at if last_sub else None,
            trend="same"  # 趋势需要历史数据对比，暂时默认
        ))

    return entries


@router.get("/{comp_id}/my-rank", summary="获取我的排名")
def get_my_rank(
    comp_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    comp = db.query(Competition).filter(Competition.id == comp_id).first()
    if not comp:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="竞赛不存在")

    # 获取我的最佳分数
    direction = comp.metric_direction
    if direction == "higher":
        my_best = db.query(func.max(Submission.public_score)).filter(
            Submission.user_id == current_user.id,
            Submission.competition_id == comp_id,
            Submission.is_valid == True
        ).scalar()
    else:
        my_best = db.query(func.min(Submission.public_score)).filter(
            Submission.user_id == current_user.id,
            Submission.competition_id == comp_id,
            Submission.is_valid == True
        ).scalar()

    if my_best is None:
        return {"rank": None, "best_score": None, "total_participants": 0}

    # 计算排名
    if direction == "higher":
        better_count = db.query(func.count(func.distinct(Submission.user_id))).filter(
            Submission.competition_id == comp_id,
            Submission.is_valid == True,
            Submission.public_score > my_best
        ).scalar()
    else:
        better_count = db.query(func.count(func.distinct(Submission.user_id))).filter(
            Submission.competition_id == comp_id,
            Submission.is_valid == True,
            Submission.public_score < my_best
        ).scalar()

    total = db.query(func.count(func.distinct(Submission.user_id))).filter(
        Submission.competition_id == comp_id,
        Submission.is_valid == True
    ).scalar()

    return {
        "rank": better_count + 1,
        "best_score": round(my_best, 6),
        "total_participants": total,
        "percentile": round((1 - better_count / max(total, 1)) * 100, 1)
    }
