"""把标准答案从 datasets 目录迁移到 answers 目录（审计 S1 的存量修复）。

背景：升级前 `answer.csv` 存放在 `DATASET_DIR/{comp_id}/` 下，而整个 DATASET_DIR
曾被 StaticFiles 无鉴权挂载，`GET /api/datasets/{id}/answer.csv` 免登录即可下载。
新版本已移除该挂载并把答案改存 `ANSWERS_DIR`，但**已部署实例的旧文件仍需搬走**。

用法：
    python scripts/migrate_answers.py --dry-run   # 只看会动哪些文件
    python scripts/migrate_answers.py             # 实际迁移

迁移是「复制 + 删除源文件」；若源文件删除失败会保留并提示，不会丢数据。
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import ANSWERS_DIR, DATASET_DIR  # noqa: E402
from app.security import is_answer_like          # noqa: E402


def find_stray_answers() -> list:
    """列出仍留在 DATASET_DIR 里的答案类文件。"""
    if not DATASET_DIR.exists():
        return []
    return [
        p for p in DATASET_DIR.rglob("*")
        if p.is_file() and is_answer_like(p.name)
    ]


def migrate(dry_run: bool = False) -> int:
    stray = find_stray_answers()
    if not stray:
        print("✅ 未发现遗留在 datasets 目录下的答案文件。")
        return 0

    print(f"发现 {len(stray)} 个遗留答案文件：")
    moved = 0
    for src in stray:
        # 目录结构为 DATASET_DIR/<comp_id>/<file>，迁到 ANSWERS_DIR/<comp_id>/<file>
        rel = src.relative_to(DATASET_DIR)
        dst = ANSWERS_DIR / rel
        print(f"  {src}  ->  {dst}")
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        try:
            src.unlink()
            moved += 1
        except OSError as e:
            print(f"    ⚠️  源文件删除失败（已复制，请手工处理）: {e}")

    if dry_run:
        print("\n（dry-run，未做任何改动）")
    else:
        print(f"\n✅ 已迁移 {moved}/{len(stray)} 个文件到 {ANSWERS_DIR}")
    return len(stray)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="迁移遗留的标准答案文件")
    ap.add_argument("--dry-run", action="store_true", help="只列出，不实际迁移")
    args = ap.parse_args()
    migrate(dry_run=args.dry_run)
