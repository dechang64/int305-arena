"""数据库连接与会话管理"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL
from .models import Base

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # SQLite 需要
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# create_all 只建缺失的**表**，不会给已存在的表补**列**。
# 讲轨迭代给 credit_scores 增加了两列，已部署的库需要显式补。
_ADDITIVE_COLUMNS = {
    "credit_scores": {
        "explain_score": "FLOAT",
        "challenge_credits": "INTEGER DEFAULT 0",
    },
}


def get_db():
    """FastAPI 依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _apply_additive_migrations():
    """为已存在的表补上新增列（幂等，只做 ADD COLUMN，不动既有数据）。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl_type in columns.items():
                if name in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
                print(f"🔧 迁移：{table} 增加列 {name}")


def create_tables():
    """创建所有数据表（并补齐增量列）"""
    Base.metadata.create_all(bind=engine)
    _apply_additive_migrations()
