"""概念卡种子导入 —— 把备课清单灌进 concepts 表。

用法：
    python scripts/seed_concepts.py                # 导入默认种子
    python scripts/seed_concepts.py 自定义.json     # 导入自定义文件

按 code 幂等 upsert：重复执行不会产生重复卡，只会刷新字段。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, create_tables  # noqa: E402
from app.models import Concept, ConceptStatus         # noqa: E402

DEFAULT_SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds", "concepts_v1.json")


def load_seed(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    # 兼容两种格式：{"_meta":..., "concepts":[...]} 或 直接是 list
    if isinstance(payload, dict):
        return payload.get("concepts", [])
    return payload


def seed(path: str = DEFAULT_SEED):
    concepts = load_seed(path)
    print(f"📚 读取种子: {path}（{len(concepts)} 张概念卡）")

    create_tables()
    db = SessionLocal()
    created = updated = 0
    try:
        for item in concepts:
            concept = db.query(Concept).filter(Concept.code == item["code"]).first()
            if concept is None:
                concept = Concept(code=item["code"], status=ConceptStatus.OPEN)
                db.add(concept)
                created += 1
            else:
                updated += 1
            concept.title = item["title"]
            concept.d2l_ref_zh = item.get("d2l_ref_zh")
            concept.d2l_ref_en = item.get("d2l_ref_en")
            concept.d2l_url = item.get("d2l_url")
            concept.boundary = item.get("boundary")
            concept.common_gaps = json.dumps(item.get("common_gaps", []), ensure_ascii=False)
            concept.jargon_watchlist = json.dumps(item.get("jargon_watchlist", []), ensure_ascii=False)
            concept.track = item.get("track", "base")
        db.commit()
        print(f"✅ 新增 {created} 张，更新 {updated} 张，共 {created + updated} 张概念卡")
    except Exception as e:
        db.rollback()
        print(f"❌ 导入失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SEED)
