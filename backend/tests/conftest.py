"""pytest 公共夹具。

关键点：**环境变量必须在 import app.* 之前设置** —— app/config.py 在模块加载时
就会做安全校验（SECRET_KEY / ADMIN_PASSWORD 为兜底值即拒绝启动），这正是被测行为。
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="int305-tests-"))

# --- 必须在 import app 之前 ---
os.environ["SECRET_KEY"] = "test-secret-key-" + "a" * 40
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["REQUIRE_APPROVAL"] = "false"
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["DATASET_DIR"] = str(_TMP / "datasets")
os.environ["ANSWERS_DIR"] = str(_TMP / "answers")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.database import SessionLocal, engine, create_tables  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, CreditScore, User, UserRole, UserStatus  # noqa: E402

TMP_ROOT = _TMP


@pytest.fixture(scope="session", autouse=True)
def _prepare_dirs():
    for sub in ("uploads", "datasets", "answers"):
        (_TMP / sub).mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture(autouse=True)
def _fresh_db():
    """每个用例一套干净的库 **和干净的文件目录**。

    文件目录必须一起清：多个用例会复用 comp_id=1 / user_id=1 这类小整数，
    不清会互相看到对方落的文件（曾因此让一条路径穿越断言出现假阳性）。
    """
    import shutil

    for sub in ("uploads", "datasets", "answers"):
        path = _TMP / sub
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    Base.metadata.drop_all(bind=engine)
    create_tables()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 用户工厂
# ---------------------------------------------------------------------------

def _create_user(db, *, email, name, student_id, password, role, status) -> User:
    user = User(
        email=email, name=name, student_id=student_id,
        hashed_password=hash_password(password),
        role=role, status=status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(CreditScore(user_id=user.id))
    db.commit()
    return user


@pytest.fixture
def admin(db) -> User:
    return _create_user(
        db, email=os.environ["ADMIN_EMAIL"], name="管理员",
        student_id="ADMIN", password=os.environ["ADMIN_PASSWORD"],
        role=UserRole.ADMIN, status=UserStatus.APPROVED,
    )


@pytest.fixture
def admin_headers(client, admin) -> dict:
    res = client.post("/api/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"],
    })
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def make_student(client, db):
    """返回一个工厂：调用即创建一个已通过审核的学生，并返回其 token/headers/id。"""
    counter = {"n": 0}

    def _make(name=None, *, role=UserRole.STUDENT, status=UserStatus.APPROVED, password="student-pw-123"):
        counter["n"] += 1
        n = counter["n"]
        name = name or f"学生{n}"
        email = f"student{n}@test.local"
        user = _create_user(
            db, email=email, name=name, student_id=f"S{n:04d}",
            password=password, role=role, status=status,
        )
        res = client.post("/api/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.text
        token = res.json()["access_token"]
        return {
            "id": user.id, "name": name, "email": email,
            "token": token, "headers": {"Authorization": f"Bearer {token}"},
        }

    return _make


@pytest.fixture
def make_competition(db):
    """创建一个可提交的竞赛，并按需铺设数据集 / 答案文件。"""
    import csv
    from datetime import datetime, timedelta

    from app.config import ANSWERS_DIR, DATASET_DIR
    from app.models import Competition, CompStatus

    counter = {"n": 0}

    def _make(*, with_answer=True, with_datasets=True, metric="RMSE", direction="lower"):
        counter["n"] += 1
        n = counter["n"]
        comp = Competition(
            slug=f"comp-test-{n}", title=f"测试竞赛{n}", description="用于自动化测试",
            metric=metric, metric_direction=direction, baseline_score=0.5,
            status=CompStatus.LIVE,
            start_time=datetime.utcnow() - timedelta(days=1),
            end_time=datetime.utcnow() + timedelta(days=7),
            max_submissions_per_day=5, max_submissions_total=50,
            tags="[]", dataset_files="[]",
        )
        db.add(comp)
        db.commit()
        db.refresh(comp)

        comp_dir = DATASET_DIR / str(comp.id)
        comp_dir.mkdir(parents=True, exist_ok=True)
        ans_dir = ANSWERS_DIR / str(comp.id)
        ans_dir.mkdir(parents=True, exist_ok=True)

        if with_datasets:
            (comp_dir / "train.csv").write_text("Id,Feature,Target\n1,0.5,1.0\n2,1.5,2.0\n", encoding="utf-8")
            (comp_dir / "test.csv").write_text("Id,Feature\n3,0.1\n4,0.2\n", encoding="utf-8")
            comp.dataset_files = '["train.csv", "test.csv"]'

        if with_answer:
            # 答案只落在 ANSWERS_DIR —— 它不在任何可下载目录下
            with (ans_dir / "answer.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Id", "Target"])
                w.writerow([3, 0.1])
                w.writerow([4, 0.2])

        db.commit()
        db.refresh(comp)
        return comp

    return _make
