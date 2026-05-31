"""认证路由 — 注册、登录、用户信息"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserRole, UserStatus
from ..auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_admin
)
from ..config import REQUIRE_APPROVAL
from ..schemas import (
    RegisterRequest, LoginRequest, TokenResponse, UserBrief
)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=TokenResponse, summary="学生注册")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """学生注册账号"""
    # 检查邮箱是否已注册
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    # 检查学号是否已注册
    if db.query(User).filter(User.student_id == req.student_id).first():
        raise HTTPException(status_code=400, detail="该学号已注册")

    # 创建用户
    user_status = UserStatus.PENDING if REQUIRE_APPROVAL else UserStatus.APPROVED
    import random
    colors = ["#3b82f6", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ec4899", "#ef4444", "#6366f1"]

    user = User(
        email=req.email,
        name=req.name,
        student_id=req.student_id,
        hashed_password=hash_password(req.password),
        role=UserRole.STUDENT,
        status=user_status,
        team=req.team,
        avatar_color=random.choice(colors),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.id})
    return TokenResponse(
        access_token=token,
        user=UserBrief(
            id=user.id, email=user.email, name=user.name,
            student_id=user.student_id, role=user.role,
            status=user.status, team=user.team
        )
    )


@router.post("/login", response_model=TokenResponse, summary="登录")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误"
        )

    # 更新最后登录时间
    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token({"sub": user.id})
    return TokenResponse(
        access_token=token,
        user=UserBrief(
            id=user.id, email=user.email, name=user.name,
            student_id=user.student_id, role=user.role,
            status=user.status, team=user.team
        )
    )


@router.get("/me", response_model=UserBrief, summary="获取当前用户信息")
def get_me(current_user: User = Depends(get_current_user)):
    return UserBrief(
        id=current_user.id, email=current_user.email, name=current_user.name,
        student_id=current_user.student_id, role=current_user.role,
        status=current_user.status, team=current_user.team
    )


@router.put("/me", response_model=UserBrief, summary="更新个人信息")
def update_me(
    name: str = None,
    team: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if name:
        current_user.name = name
    if team:
        current_user.team = team
    db.commit()
    db.refresh(current_user)
    return UserBrief(
        id=current_user.id, email=current_user.email, name=current_user.name,
        student_id=current_user.student_id, role=current_user.role,
        status=current_user.status, team=current_user.team
    )
