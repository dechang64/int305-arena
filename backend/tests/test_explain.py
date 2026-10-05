"""讲轨回归测试 —— 采集链路、卡壳聚合视图、权限矩阵、并发认领。"""
import sys
from pathlib import Path

import pytest

from tests.conftest import BACKEND_DIR

SCRIPTS_DIR = BACKEND_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# 帮助函数
# ---------------------------------------------------------------------------

def make_concept(client, admin_headers, code="C-12", **overrides):
    body = {
        "code": code,
        "title": "批量规范化在训练与推理时的差异",
        "d2l_ref_zh": "7.5 批量规范化",
        "d2l_url": "https://zh-v2.d2l.ai/chapter_convolutional-modern/batch-norm.html",
        "boundary": "说清训练用批统计量、推理用全局统计量的原因",
        "common_gaps": ["说「推理时没有批」这种表面理由"],
        "jargon_watchlist": ["批量规范化", "running statistics"],
        "track": "arch",
    }
    body.update(overrides)
    res = client.post("/api/explain/concepts", headers=admin_headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def submit_claim(client, headers, concept_id, plain_text=None, **overrides):
    body = {
        "concept_id": concept_id,
        "plain_text": plain_text or "训练时我们用当前批次算出的均值和方差把这一层归一化，所以每次前向的统计量都在变；"
                                    "推理时没有「一批」可言，如果继续用单条样本自己的统计量，结果会随样本漂移，"
                                    "所以要把训练过程中累积的全局均值方差固定下来用，这样同一个样本单独送进网络也能得到稳定输出。",
        "analogy": "像考试时用的及格线，是平时月考反复累积出来的，不能因为你一个人今天发挥失常就当场改线。",
        "counterexample": "反例：推理时仍用单样本统计量，则同一张图片单独预测与放进批量预测结果不一致。",
    }
    body.update(overrides)
    res = client.post("/api/explain/claims", headers=headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def setup_claim(client, admin_headers, make_student, code="C-12", **concept_kwargs):
    """建卡 → 认领 → 回讲，返回 (concept, claim, student)。"""
    concept = make_concept(client, admin_headers, code=code, **concept_kwargs)
    student = make_student()
    client.post(f"/api/explain/concepts/{concept['id']}/claim",
                headers=student["headers"], json={"group_name": "第1组"})
    claim = submit_claim(client, student["headers"], concept["id"])
    return concept, claim, student


# ===========================================================================
# 概念卡
# ===========================================================================

class TestConcepts:
    def test_requires_login(self, client):
        assert client.get("/api/explain/concepts").status_code == 401

    def test_student_cannot_create(self, client, make_student):
        s = make_student()
        res = client.post("/api/explain/concepts", headers=s["headers"], json={
            "code": "C-99", "title": "越权测试", "track": "base",
        })
        assert res.status_code == 403

    def test_admin_creates_and_lists(self, client, admin_headers, make_student):
        make_concept(client, admin_headers, code="C-01")
        make_concept(client, admin_headers, code="C-02", track="optimize")
        s = make_student()
        rows = client.get("/api/explain/concepts", headers=s["headers"]).json()
        assert [r["code"] for r in rows] == ["C-01", "C-02"]
        assert rows[0]["status"] == "open" and rows[0]["claimed_by_group"] is None

    def test_duplicate_code_rejected(self, client, admin_headers):
        make_concept(client, admin_headers, code="C-05")
        res = client.post("/api/explain/concepts", headers=admin_headers, json={
            "code": "C-05", "title": "重复编号", "track": "base",
        })
        assert res.status_code == 409

    def test_invalid_track_rejected(self, client, admin_headers):
        res = client.post("/api/explain/concepts", headers=admin_headers, json={
            "code": "C-77", "title": "非法轨道", "track": "nonsense",
        })
        assert res.status_code == 422

    def test_filter_by_track_and_claimed(self, client, admin_headers, make_student):
        make_concept(client, admin_headers, code="C-01", track="base")
        c2 = make_concept(client, admin_headers, code="C-12", track="arch")
        s = make_student()
        client.post(f"/api/explain/concepts/{c2['id']}/claim",
                    headers=s["headers"], json={"group_name": "第1组"})

        assert len(client.get("/api/explain/concepts?track=arch", headers=s["headers"]).json()) == 1
        claimed = client.get("/api/explain/concepts?claimed=true", headers=s["headers"]).json()
        assert [r["code"] for r in claimed] == ["C-12"]
        assert claimed[0]["claimed_by_group"] == "第1组"

    def test_detail_includes_claims(self, client, admin_headers, make_student):
        concept, claim, _ = setup_claim(client, admin_headers, make_student)
        detail = client.get(f"/api/explain/concepts/{concept['id']}",
                            headers=admin_headers).json()
        assert len(detail["claims"]) == 1
        assert detail["claims"][0]["id"] == claim["id"]
        assert detail["jargon_watchlist"] == ["批量规范化", "running statistics"]

    def test_bulk_import_is_idempotent(self, client, admin_headers, make_student):
        payload = [
            {"code": "C-01", "title": "梯度从哪里来", "track": "base"},
            {"code": "C-02", "title": "交叉熵为何配 softmax", "track": "base"},
        ]
        first = client.post("/api/explain/concepts/import", headers=admin_headers, json=payload).json()
        assert first == {"created": 2, "updated": 0, "total": 2}
        second = client.post("/api/explain/concepts/import", headers=admin_headers, json=payload).json()
        assert second == {"created": 0, "updated": 2, "total": 2}
        assert len(client.get("/api/explain/concepts", headers=admin_headers).json()) == 2


# ===========================================================================
# 认领（含并发）
# ===========================================================================

class TestClaim:
    def test_one_concept_one_group(self, client, admin_headers, make_student):
        concept = make_concept(client, admin_headers)
        a, b = make_student("甲"), make_student("乙")

        assert client.post(f"/api/explain/concepts/{concept['id']}/claim",
                           headers=a["headers"], json={"group_name": "第1组"}).status_code == 200
        conflict = client.post(f"/api/explain/concepts/{concept['id']}/claim",
                               headers=b["headers"], json={"group_name": "第2组"})
        assert conflict.status_code == 409
        assert "第1组" in conflict.json()["detail"]

    def test_claim_missing_concept_404(self, client, make_student):
        s = make_student()
        res = client.post("/api/explain/concepts/99999/claim",
                          headers=s["headers"], json={"group_name": "第1组"})
        assert res.status_code == 404

    def test_concurrent_claims_only_one_wins(self, client, admin_headers, make_student):
        """并发双认领：单语句 UPDATE ... WHERE claimed_by_group IS NULL 的原子性。"""
        from concurrent.futures import ThreadPoolExecutor

        concept = make_concept(client, admin_headers)
        students = [make_student(f"并发{i}") for i in range(6)]

        def try_claim(s):
            return client.post(
                f"/api/explain/concepts/{concept['id']}/claim",
                headers=s["headers"], json={"group_name": s["name"]},
            ).status_code

        with ThreadPoolExecutor(max_workers=6) as ex:
            codes = list(ex.map(try_claim, students))

        assert codes.count(200) == 1, f"应只有一个组认领成功，实际 {codes}"
        winner = students[codes.index(200)]
        rows = client.get("/api/explain/concepts?claimed=true", headers=admin_headers).json()
        assert rows[0]["claimed_by_group"] == winner["name"]

    def test_release_returns_to_open(self, client, admin_headers, make_student):
        concept = make_concept(client, admin_headers)
        a = make_student("甲")
        client.post(f"/api/explain/concepts/{concept['id']}/claim",
                    headers=a["headers"], json={"group_name": "第1组"})

        b = make_student("乙")
        assert client.post(f"/api/explain/concepts/{concept['id']}/release",
                           headers=b["headers"]).status_code == 403
        assert client.post(f"/api/explain/concepts/{concept['id']}/release",
                           headers=a["headers"]).status_code == 200
        assert client.post(f"/api/explain/concepts/{concept['id']}/claim",
                           headers=b["headers"], json={"group_name": "第2组"}).status_code == 200


# ===========================================================================
# 回讲与第二版
# ===========================================================================

class TestClaims:
    def test_must_claim_before_submitting(self, client, admin_headers, make_student):
        concept = make_concept(client, admin_headers)
        s = make_student()
        res = client.post("/api/explain/claims", headers=s["headers"], json={
            "concept_id": concept["id"], "plain_text": "x" * 40,
        })
        assert res.status_code == 403

    def test_second_v1_rejected(self, client, admin_headers, make_student):
        concept, claim, student = setup_claim(client, admin_headers, make_student)
        res = client.post("/api/explain/claims", headers=student["headers"], json={
            "concept_id": concept["id"], "plain_text": "y" * 40,
        })
        assert res.status_code == 409

    def test_short_plain_text_rejected(self, client, admin_headers, make_student):
        concept = make_concept(client, admin_headers)
        s = make_student()
        client.post(f"/api/explain/concepts/{concept['id']}/claim",
                    headers=s["headers"], json={"group_name": "第1组"})
        res = client.post("/api/explain/claims", headers=s["headers"], json={
            "concept_id": concept["id"], "plain_text": "太短",
        })
        assert res.status_code == 422

    def test_revise_requires_diff_and_closes_gaps(self, client, admin_headers, make_student):
        concept, claim, student = setup_claim(client, admin_headers, make_student)
        ch = client.post(f"/api/explain/claims/{claim['id']}/challenge", headers=make_student("质询者")["headers"],
                         json={"question": "推理时的全局统计量是怎么累积出来的？"}).json()
        client.post(f"/api/explain/challenges/{ch['id']}/arbitrate", headers=admin_headers,
                    json={"is_gap": True, "gap_severity": 2})

        before = client.get("/api/explain/gaps/summary", headers=admin_headers).json()
        assert before["open_gaps"] == 1

        # revision_diff 缺失 -> 422
        bad = client.post(f"/api/explain/claims/{claim['id']}/revise", headers=student["headers"], json={
            "plain_text": "z" * 40, "revision_diff": "",
        })
        assert bad.status_code == 422

        ok = client.post(f"/api/explain/claims/{claim['id']}/revise", headers=student["headers"], json={
            "plain_text": "训练阶段每做一次前向，就把这一批的均值和方差按动量方式并入全局统计量；"
                          "推理时直接取这份累积值，因此与批量大小无关。",
            "revision_diff": "第一版漏掉了「全局统计量是逐步累积来的」这一步，只说了要用全局值。",
            "gap_closed": True,
        })
        assert ok.status_code == 200, ok.text
        assert ok.json()["version"] == 2

        after = client.get("/api/explain/gaps/summary", headers=admin_headers).json()
        assert after["total_gaps"] == 1 and after["open_gaps"] == 0

    def test_only_owner_can_revise(self, client, admin_headers, make_student):
        _, claim, _ = setup_claim(client, admin_headers, make_student)
        outsider = make_student("旁观者")
        res = client.post(f"/api/explain/claims/{claim['id']}/revise", headers=outsider["headers"], json={
            "plain_text": "q" * 40, "revision_diff": "与我无关的第二版",
        })
        assert res.status_code == 403


# ===========================================================================
# 质询与裁定
# ===========================================================================

class TestChallenges:
    def test_statement_rejected(self, client, admin_headers, make_student):
        _, claim, _ = setup_claim(client, admin_headers, make_student)
        q = make_student("提问者")
        res = client.post(f"/api/explain/claims/{claim['id']}/challenge", headers=q["headers"],
                          json={"question": "这一段我觉得写得不够详细，需要补充内容"})
        assert res.status_code == 422
        assert "疑问句" in res.json()["detail"]

    def test_cannot_challenge_own_claim(self, client, admin_headers, make_student):
        _, claim, student = setup_claim(client, admin_headers, make_student)
        res = client.post(f"/api/explain/claims/{claim['id']}/challenge", headers=student["headers"],
                          json={"question": "我自己问自己可以吗？"})
        assert res.status_code == 400

    def test_uses_concept_term_flagged(self, client, admin_headers, make_student):
        """含被讲概念核心术语的质询不算好问题，需要标记出来给裁定者看。"""
        _, claim, _ = setup_claim(client, admin_headers, make_student)
        q = make_student("提问者")

        bad = client.post(f"/api/explain/claims/{claim['id']}/challenge", headers=q["headers"],
                          json={"question": "你能解释一下什么是批量规范化吗？"}).json()
        assert bad["uses_concept_term"] is True

        good = client.post(f"/api/explain/claims/{claim['id']}/challenge", headers=q["headers"],
                           json={"question": "如果推理阶段也沿用当前批次自己的统计量，同一张图单独预测会怎样？"}).json()
        assert good["uses_concept_term"] is False

    def test_respond_only_by_owner(self, client, admin_headers, make_student):
        _, claim, student = setup_claim(client, admin_headers, make_student)
        ch = client.post(f"/api/explain/claims/{claim['id']}/challenge",
                         headers=make_student("提问者")["headers"],
                         json={"question": "为什么不能直接用单样本的统计量？"}).json()

        outsider = make_student("旁观者")
        assert client.post(f"/api/explain/challenges/{ch['id']}/respond", headers=outsider["headers"],
                           json={"response": "我来替你答"}).status_code == 403

        ok = client.post(f"/api/explain/challenges/{ch['id']}/respond", headers=student["headers"],
                         json={"response": "因为单样本方差噪声极大，输出会随样本抖动。"})
        assert ok.status_code == 200
        assert ok.json()["responded_at"] is not None

    def test_arbitrate_permissions_and_severity(self, client, admin_headers, make_student):
        _, claim, _ = setup_claim(client, admin_headers, make_student)
        ch = client.post(f"/api/explain/claims/{claim['id']}/challenge",
                         headers=make_student("提问者")["headers"],
                         json={"question": "全局统计量具体是怎么更新的？"}).json()

        s = make_student("普通学生")
        assert client.post(f"/api/explain/challenges/{ch['id']}/arbitrate", headers=s["headers"],
                           json={"is_gap": True, "gap_severity": 1}).status_code == 403

        # 判为卡壳点却不给严重度 -> 422
        assert client.post(f"/api/explain/challenges/{ch['id']}/arbitrate", headers=admin_headers,
                           json={"is_gap": True}).status_code == 422

        # 判为非卡壳点可以不带严重度
        not_gap = client.post(f"/api/explain/challenges/{ch['id']}/arbitrate", headers=admin_headers,
                              json={"is_gap": False})
        assert not_gap.status_code == 200 and not_gap.json()["is_gap"] is False

        gap = client.post(f"/api/explain/challenges/{ch['id']}/arbitrate", headers=admin_headers,
                          json={"is_gap": True, "gap_severity": 3})
        assert gap.status_code == 200
        assert gap.json()["gap_severity"] == 3
        assert gap.json()["arbiter_id"] == 1

    def test_pending_filter(self, client, admin_headers, make_student):
        _, claim, _ = setup_claim(client, admin_headers, make_student)
        client.post(f"/api/explain/claims/{claim['id']}/challenge",
                    headers=make_student("提问者")["headers"],
                    json={"question": "为什么这里要这样处理？"})
        pending = client.get("/api/explain/challenges?pending=true", headers=admin_headers).json()
        assert len(pending) == 1 and pending[0]["is_gap"] is None


# ===========================================================================
# 卡壳点聚合视图（教师端核心产物）
# ===========================================================================

class TestGapSummary:
    def test_requires_admin(self, client, make_student):
        s = make_student()
        assert client.get("/api/explain/gaps/summary", headers=s["headers"]).status_code == 403
        assert client.get("/api/explain/gaps/summary").status_code == 401

    def test_empty_state_is_well_formed(self, client, admin_headers):
        body = client.get("/api/explain/gaps/summary", headers=admin_headers).json()
        assert body["total_gaps"] == 0
        assert body["by_concept"] == []
        assert [b["severity"] for b in body["by_severity"]] == [1, 2, 3]
        assert all(b["count"] == 0 for b in body["by_severity"])

    def test_aggregation_ordering_and_buckets(self, client, admin_headers, make_student):
        # 卡 C-12：3 个卡壳点（severity 3,2,1）
        concept_a, claim_a, _ = setup_claim(client, admin_headers, make_student, code="C-12")
        # 卡 C-07（optimize 轨道）：1 个卡壳点（severity 2）
        concept_b, claim_b, _ = setup_claim(client, admin_headers, make_student,
                                            code="C-07", track="optimize")

        qs = [make_student(f"质询{i}") for i in range(4)]
        for i, sev in enumerate((3, 2, 1)):
            ch = client.post(f"/api/explain/claims/{claim_a['id']}/challenge", headers=qs[i]["headers"],
                             json={"question": f"关于批统计量的第{i}个追问，具体如何传递？"}).json()
            client.post(f"/api/explain/challenges/{ch['id']}/arbitrate", headers=admin_headers,
                        json={"is_gap": True, "gap_severity": sev})
        ch_b = client.post(f"/api/explain/claims/{claim_b['id']}/challenge", headers=qs[3]["headers"],
                           json={"question": "初始化尺度和批大小有交互吗？"}).json()
        client.post(f"/api/explain/challenges/{ch_b['id']}/arbitrate", headers=admin_headers,
                    json={"is_gap": True, "gap_severity": 2})
        # 一条被判为非卡壳点，不应计入
        ch_x = client.post(f"/api/explain/claims/{claim_a['id']}/challenge", headers=qs[0]["headers"],
                           json={"question": "这个公式的下标是不是写错了？"}).json()
        client.post(f"/api/explain/challenges/{ch_x['id']}/arbitrate", headers=admin_headers,
                    json={"is_gap": False})

        body = client.get("/api/explain/gaps/summary", headers=admin_headers).json()

        assert body["total_gaps"] == 4
        assert body["adjudicated_challenges"] == 5
        assert body["pending_challenges"] == 0
        assert body["open_gaps"] == 4
        assert body["concept_count_with_gaps"] == 2

        # 排序：卡壳点多的 C-12 排第一
        assert [c["code"] for c in body["by_concept"]] == ["C-12", "C-07"]
        top = body["by_concept"][0]
        assert top["gap_count"] == 3
        assert top["avg_severity"] == 2.0
        assert top["max_severity"] == 3
        assert top["challenge_count"] == 4      # 含 1 条非卡壳点
        assert len(top["sample_questions"]) == 3
        assert top["open_gap_count"] == 3
        assert top["d2l_ref_zh"] == "7.5 批量规范化"

        assert {b["severity"]: b["count"] for b in body["by_severity"]} == {1: 1, 2: 2, 3: 1}

        # 轨道分布：arch 3 个卡壳点排第一，optimize 1 个
        assert [(t["track"], t["gap_count"], t["concept_count"]) for t in body["by_track"]] == [
            ("arch", 3, 1), ("optimize", 1, 1),
        ]
        assert sum(w["gap_count"] for w in body["by_week"]) == 4

    def test_track_and_severity_filters(self, client, admin_headers, make_student):
        c1, claim1, _ = setup_claim(client, admin_headers, make_student, code="C-12")   # arch
        c2, claim2, _ = setup_claim(client, admin_headers, make_student, code="C-07")   # arch(默认) -> 改成 optimize

        ch1 = client.post(f"/api/explain/claims/{claim1['id']}/challenge",
                          headers=make_student("问1")["headers"],
                          json={"question": "训练时的统计量会随批次变化吗？"}).json()
        client.post(f"/api/explain/challenges/{ch1['id']}/arbitrate", headers=admin_headers,
                    json={"is_gap": True, "gap_severity": 3})
        ch2 = client.post(f"/api/explain/claims/{claim2['id']}/challenge",
                          headers=make_student("问2")["headers"],
                          json={"question": "尺度与方差的关系是什么？"}).json()
        client.post(f"/api/explain/challenges/{ch2['id']}/arbitrate", headers=admin_headers,
                    json={"is_gap": True, "gap_severity": 1})

        assert client.get("/api/explain/gaps/summary", headers=admin_headers).json()["total_gaps"] == 2
        arch_only = client.get("/api/explain/gaps/summary?track=arch", headers=admin_headers).json()
        assert arch_only["total_gaps"] == 2
        sev2 = client.get("/api/explain/gaps/summary?min_severity=2", headers=admin_headers).json()
        assert sev2["total_gaps"] == 1
        assert sev2["by_concept"][0]["max_severity"] == 3

    def test_detail_list(self, client, admin_headers, make_student):
        _, claim, _ = setup_claim(client, admin_headers, make_student)
        ch = client.post(f"/api/explain/claims/{claim['id']}/challenge",
                         headers=make_student("提问者")["headers"],
                         json={"question": "全局均值和方差到底是怎么被保存下来的？"}).json()
        client.post(f"/api/explain/challenges/{ch['id']}/arbitrate", headers=admin_headers,
                    json={"is_gap": True, "gap_severity": 2})

        rows = client.get("/api/explain/gaps", headers=admin_headers).json()
        assert len(rows) == 1
        assert rows[0]["question"] == "全局均值和方差到底是怎么被保存下来的？"
        assert rows[0]["gap_severity"] == 2 and rows[0]["gap_closed"] is False
        assert rows[0]["concept_code"] == "C-12"
        assert rows[0]["challenger_name"] == "提问者"


# ===========================================================================
# 我的讲轨
# ===========================================================================

class TestMyExplain:
    def test_me_counts(self, client, admin_headers, make_student):
        concept, claim, student = setup_claim(client, admin_headers, make_student)
        ch = client.post(f"/api/explain/claims/{claim['id']}/challenge",
                         headers=make_student("提问者")["headers"],
                         json={"question": "为什么全局统计量要按动量更新？"}).json()
        client.post(f"/api/explain/challenges/{ch['id']}/arbitrate", headers=admin_headers,
                    json={"is_gap": True, "gap_severity": 3})

        mine = client.get("/api/explain/me", headers=student["headers"]).json()
        assert mine["name"] == student["name"]
        assert [c["code"] for c in mine["concepts_claimed"]] == ["C-12"]
        assert mine["concepts_claimed"][0]["gap_count"] == 1
        assert len(mine["claims_submitted"]) == 1
        assert mine["gaps_flagged_on_me"] == 1
        assert mine["challenges_raised"] == 0

        asker = make_student("提问者2")
        ch2 = client.post(f"/api/explain/claims/{claim['id']}/challenge", headers=asker["headers"],
                          json={"question": "这种归一化对卷积层是逐通道做的吗？"}).json()
        client.post(f"/api/explain/challenges/{ch2['id']}/arbitrate", headers=admin_headers,
                    json={"is_gap": True, "gap_severity": 2})
        asker_me = client.get("/api/explain/me", headers=asker["headers"]).json()
        assert asker_me["challenges_raised"] == 1
        assert asker_me["effective_challenges"] == 1


# ===========================================================================
# 种子数据
# ===========================================================================

class TestSeed:
    def test_seed_concepts_is_idempotent_and_loads_20(self):
        from seed_concepts import seed

        seed()
        seed()  # 幂等

        from app.database import SessionLocal
        from app.models import Concept

        session = SessionLocal()
        try:
            rows = session.query(Concept).order_by(Concept.code).all()
            assert len(rows) == 20
            assert rows[0].code == "C-01" and rows[-1].code == "C-20"
            assert all(r.boundary for r in rows), "每张卡都必须有判定边界"
            assert all(r.d2l_ref_zh for r in rows), "每张卡都必须有 d2l 中文定位"
            assert all(r.d2l_url and r.d2l_url.startswith("https://zh-v2.d2l.ai/") for r in rows)
            tracks = {r.track for r in rows}
            assert tracks == {"base", "arch", "optimize", "application"}
        finally:
            session.close()
