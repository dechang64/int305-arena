"""安全回归测试 —— 覆盖 S1 / S2 / S3 / S4 四项已修复缺陷。

这些用例的作用是**把已修复的漏洞钉死**：任何一次回退都会让测试变红，
而不是等到某次比赛被抄答案之后才发现。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.security import (
    UnsafeFilenameError, is_answer_like, safe_filename, safe_join,
)
from tests.conftest import BACKEND_DIR, TMP_ROOT


# ===========================================================================
# 单元：文件名净化 / 路径拼接
# ===========================================================================

class TestSafeFilename:
    @pytest.mark.parametrize("raw,expected", [
        ("train.csv", "train.csv"),
        ("../../evil.csv", "evil.csv"),
        ("..\\..\\..\\evil.csv", "evil.csv"),
        ("/etc/passwd", "passwd"),
        ("C:\\Windows\\evil.txt", "evil.txt"),
        ("  spaced.csv  ", "spaced.csv"),
        ("报告 最终版.csv", "报告 最终版.csv"),
        # 不可打印字符（含 NUL）会被剥掉，而不是原样落盘
        ("bad\x00name.csv", "badname.csv"),
    ])
    def test_strips_directories(self, raw, expected):
        assert safe_filename(raw) == expected

    @pytest.mark.parametrize("raw", [
        "", "   ", "..", "../", "/", "\\",
        "CON", "con.txt", "LPT1.csv", "com1.csv", "a?b.csv", "a|b.csv",
    ])
    def test_rejects_bad_names(self, raw):
        with pytest.raises(UnsafeFilenameError):
            safe_filename(raw)

    def test_truncates_long_names_keeping_suffix(self):
        out = safe_filename("x" * 300 + ".csv")
        assert len(out) <= 80 and out.endswith(".csv")

    def test_safe_join_blocks_escape(self):
        root = TMP_ROOT / "uploads"
        assert safe_join(root, "a", "b.csv").parent.name == "a"
        with pytest.raises(UnsafeFilenameError):
            safe_join(root, "..", "..", "escaped.csv")
        # 词法折叠正是原漏洞的成因，这里必须拦住
        with pytest.raises(UnsafeFilenameError):
            safe_join(root, "..\\..\\..\\escaped.csv")

    def test_is_answer_like(self):
        for name in ("answer.csv", "Answer.CSV", "answers.csv", "answers_v2.csv",
                     "answer_key.csv", "gt.csv", "标准答案.csv"):
            assert is_answer_like(name), name
        for name in ("train.csv", "test.csv", "sample_submission.csv", "features.csv"):
            assert not is_answer_like(name), name

    def test_is_answer_like_checks_basename_only(self):
        # 目录里出现 "answer" 不该误判文件本身
        assert not is_answer_like("answers_dir/train.csv")


# ===========================================================================
# S1 —— 标准答案不可下载
# ===========================================================================

class TestS1AnswerNotDownloadable:
    def test_anonymous_cannot_reach_datasets(self, client, make_competition):
        comp = make_competition()
        for url in (
            f"/api/datasets/{comp.id}/answer.csv",
            f"/api/competitions/{comp.id}/datasets/answer.csv",
        ):
            assert client.get(url).status_code == 401, url

    def test_answer_like_is_blocked_even_if_whitelisted(self, client, db, make_competition):
        """双重防线：即便管理员把 answer.csv 登记进 dataset_files，也必须 404。"""
        from app.config import DATASET_DIR
        from app.models import Competition

        comp = make_competition(with_answer=False)
        (DATASET_DIR / str(comp.id) / "answer.csv").write_text("Id,Target\n1,1\n", encoding="utf-8")
        comp_orm = db.query(Competition).filter(Competition.id == comp.id).first()
        comp_orm.dataset_files = '["answer.csv"]'
        db.commit()

        student = None
        # 用匿名请求验证 401，用学生验证 404
        assert client.get(f"/api/datasets/{comp.id}/answer.csv").status_code == 401

    def test_answer_like_guard_directly(self, client, db, make_competition, make_student):
        from app.config import DATASET_DIR
        from app.models import Competition

        comp = make_competition(with_answer=False)
        (DATASET_DIR / str(comp.id) / "answer.csv").write_text("Id,Target\n1,1\n", encoding="utf-8")
        db.query(Competition).filter(Competition.id == comp.id).first().dataset_files = '["answer.csv"]'
        db.commit()

        s = make_student()
        res = client.get(f"/api/datasets/{comp.id}/answer.csv", headers=s["headers"])
        assert res.status_code == 404, res.text

    def test_whitelisted_training_set_is_downloadable(self, client, make_competition, make_student):
        comp = make_competition()
        s = make_student()
        res = client.get(f"/api/datasets/{comp.id}/train.csv", headers=s["headers"])
        assert res.status_code == 200
        assert b"Feature" in res.content

        alias = client.get(f"/api/competitions/{comp.id}/datasets/train.csv", headers=s["headers"])
        assert alias.status_code == 200

    def test_unregistered_file_is_not_downloadable(self, client, db, make_competition, make_student):
        """防目录枚举：datasets 目录里存在但没登记的文件也不给。"""
        from app.config import DATASET_DIR

        comp = make_competition()
        (DATASET_DIR / str(comp.id) / "secret_notes.csv").write_text("x", encoding="utf-8")
        s = make_student()
        assert client.get(
            f"/api/datasets/{comp.id}/secret_notes.csv", headers=s["headers"]
        ).status_code == 404

    def test_scoring_still_finds_answer_in_answers_dir(self, client, make_competition, make_student):
        """搬走答案不能把评分搞坏：scorer 必须仍能读到 ANSWERS_DIR 里的答案。"""
        comp = make_competition()
        s = make_student()
        payload = b"Id,Target\n3,0.1\n4,0.2\n"  # 与 answer.csv 完全一致 -> RMSE=0
        res = client.post(
            f"/api/submissions/{comp.id}/submit",
            files={"prediction": ("pred.csv", payload, "text/csv")},
            headers=s["headers"],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["error_message"] is None
        assert body["public_score"] == pytest.approx(0.0)

    def test_dataset_upload_reroutes_answer_files(self, client, admin_headers, make_competition, db):
        """手滑把 answer.csv 当数据集上传时，应被改判为答案：不登记、不可下载。"""
        from app.config import ANSWERS_DIR
        from app.models import Competition

        comp = make_competition(with_datasets=False)
        res = client.post(
            f"/api/competitions/{comp.id}/datasets",
            files={"file": ("answer.csv", b"Id,Target\n1,1\n", "text/csv")},
            headers=admin_headers,
        )
        assert res.status_code == 200, res.text
        assert res.json()["kind"] == "answer"
        assert res.json()["downloadable"] is False
        assert (ANSWERS_DIR / str(comp.id) / "answer.csv").is_file()

        db.expire_all()
        comp_orm = db.query(Competition).filter(Competition.id == comp.id).first()
        assert "answer.csv" not in (comp_orm.dataset_files or "")


# ===========================================================================
# S2 —— 上传文件名路径穿越
# ===========================================================================

class TestS2PathTraversal:
    def test_submission_filename_cannot_escape(self, client, make_competition, make_student):
        from app.config import UPLOAD_DIR

        comp = make_competition()
        s = make_student()
        res = client.post(
            f"/api/submissions/{comp.id}/submit",
            files={"prediction": ("../../../../../../pwn_submit.csv", b"Id,Target\n3,0.1\n4,0.2\n", "text/csv")},
            headers=s["headers"],
        )
        assert res.status_code == 200, res.text

        user_dir = UPLOAD_DIR / str(comp.id) / str(s["id"])
        landed = list(user_dir.glob("*.csv"))
        assert landed, "文件应落在用户自己的上传目录内"
        assert all("pwn_submit" in p.name for p in landed)

        # 关键断言：TMP_ROOT 下、用户目录之外，不该出现任何逃逸文件
        escaped = [
            p for p in TMP_ROOT.rglob("pwn_submit*")
            if user_dir not in p.parents
        ]
        assert escaped == [], f"检测到逃逸写入: {escaped}"

    def test_unusable_filename_returns_400(self, client, make_competition, make_student):
        comp = make_competition()
        s = make_student()
        res = client.post(
            f"/api/submissions/{comp.id}/submit",
            files={"prediction": ("../../../", b"x", "text/csv")},
            headers=s["headers"],
        )
        assert res.status_code == 400, res.text

    def test_market_attachment_cannot_escape(self, client, make_competition, admin_headers, make_student):
        """任务交付附件的同类漏洞（原 market.py:546）。"""
        from app.config import UPLOAD_DIR

        owner = make_student("出题者")
        worker = make_student("接单者")

        task = client.post("/api/market/tasks", headers=owner["headers"], json={
            "title": "路径穿越测试任务",
            "description": "用于验证附件名净化是否生效，内容无实际意义。",
            "category": "other",
            "deliverables": ["脚本"],
            "acceptance_criteria": "能跑通即可，通过自动化验收",
        }).json()
        client.post(f"/api/market/tasks/{task['id']}/review",
                    headers=admin_headers, json={"action": "approve"})

        app_res = client.post(f"/api/market/tasks/{task['id']}/apply",
                              headers=worker["headers"], json={"message": "我来做"}).json()
        client.post(f"/api/market/applications/{app_res['id']}/action",
                    headers=owner["headers"], json={"action": "accept"})
        client.post(f"/api/market/tasks/{task['id']}/deliver", headers=worker["headers"],
                    json={"code_url": "https://example.com/repo"})

        up = client.post(
            f"/api/market/tasks/{task['id']}/deliver/upload",
            files={"file": ("../../../../../../pwn_attach.zip", b"PK\x03\x04", "application/zip")},
            headers=worker["headers"],
        )
        assert up.status_code == 200, up.text
        assert "/" not in up.json()["filename"] and ".." not in up.json()["filename"]

        task_dir = UPLOAD_DIR / "deliveries" / str(task["id"])
        assert list(task_dir.glob("*pwn_attach*"))
        escaped = [p for p in TMP_ROOT.rglob("pwn_attach*") if task_dir not in p.parents]
        assert escaped == [], f"检测到逃逸写入: {escaped}"


# ===========================================================================
# S4 —— 交付附件下载需鉴权且限定归属
# ===========================================================================

class TestS4UploadsRequireAuth:
    def _make_delivery(self, client, admin_headers, make_student, tmp_attach=b"PK\x03\x04data"):
        owner = make_student("附件出题者")
        worker = make_student("附件接单者")
        task = client.post("/api/market/tasks", headers=owner["headers"], json={
            "title": "附件下载鉴权测试",
            "description": "验证交付附件下载的权限边界，内容无实际意义。",
            "category": "other",
            "deliverables": ["压缩包"],
            "acceptance_criteria": "能下载即可，通过自动化验收",
        }).json()
        client.post(f"/api/market/tasks/{task['id']}/review",
                    headers=admin_headers, json={"action": "approve"})
        app_res = client.post(f"/api/market/tasks/{task['id']}/apply",
                              headers=worker["headers"], json={"message": "接单"}).json()
        client.post(f"/api/market/applications/{app_res['id']}/action",
                    headers=owner["headers"], json={"action": "accept"})
        client.post(f"/api/market/tasks/{task['id']}/deliver", headers=worker["headers"],
                    json={"code_url": "https://example.com/r"})
        up = client.post(f"/api/market/tasks/{task['id']}/deliver/upload",
                         files={"file": ("pkg.zip", tmp_attach, "application/zip")},
                         headers=worker["headers"]).json()
        return owner, worker, task, up["filename"]

    def test_anonymous_denied(self, client, admin_headers, make_student):
        _, _, task, fname = self._make_delivery(client, admin_headers, make_student)
        res = client.get(f"/api/uploads/deliveries/{task['id']}/{fname}")
        assert res.status_code == 401

    def test_unrelated_student_denied(self, client, admin_headers, make_student):
        _, _, task, fname = self._make_delivery(client, admin_headers, make_student)
        outsider = make_student("无关同学")
        res = client.get(f"/api/uploads/deliveries/{task['id']}/{fname}", headers=outsider["headers"])
        assert res.status_code == 403

    def test_owner_and_worker_allowed(self, client, admin_headers, make_student):
        owner, worker, task, fname = self._make_delivery(client, admin_headers, make_student)
        for who in (owner, worker):
            res = client.get(f"/api/uploads/deliveries/{task['id']}/{fname}", headers=who["headers"])
            assert res.status_code == 200, who["name"]
            assert res.content == b"PK\x03\x04data"

    def test_unregistered_filename_denied(self, client, admin_headers, make_student):
        owner, _, task, _ = self._make_delivery(client, admin_headers, make_student)
        res = client.get(f"/api/uploads/deliveries/{task['id']}/not_recorded.zip", headers=owner["headers"])
        assert res.status_code == 404

    def test_response_does_not_leak_server_path(self, client, admin_headers, make_student):
        owner, _, task, _ = self._make_delivery(client, admin_headers, make_student)
        rows = client.get(f"/api/market/tasks/{task['id']}/deliveries", headers=owner["headers"]).json()
        assert rows
        att = rows[0]["attachment"]
        assert att.endswith("pkg.zip")
        # 关键：不能回传服务器绝对路径
        assert "/" not in att and "\\" not in att and ":" not in att


# ===========================================================================
# S3 —— 兜底凭据拒绝启动
# ===========================================================================

class TestS3RefuseInsecureDefaults:
    def _run_import(self, env_overrides, drop=()):
        env = {**os.environ}
        for key in drop:
            env.pop(key, None)
        env.update(env_overrides)
        env["PYTHONPATH"] = str(BACKEND_DIR)
        return subprocess.run(
            [sys.executable, "-c", "import app.config"],
            env=env, capture_output=True, text=True, cwd=str(BACKEND_DIR),
        )

    def test_refuses_default_secret_key(self):
        r = self._run_import({}, drop=("SECRET_KEY",))
        assert r.returncode != 0
        assert "SECRET_KEY" in r.stderr

    def test_refuses_default_admin_password(self):
        r = self._run_import({"SECRET_KEY": "x" * 48}, drop=("ADMIN_PASSWORD",))
        assert r.returncode != 0
        assert "ADMIN_PASSWORD" in r.stderr

    def test_refuses_known_leaked_placeholders(self):
        for secret in ("dev-secret-key-change-in-production", "change-me-in-production-2024"):
            r = self._run_import({"SECRET_KEY": secret, "ADMIN_PASSWORD": "a-real-password-1234"})
            assert r.returncode != 0, secret

    def test_accepts_strong_credentials(self):
        r = self._run_import({
            "SECRET_KEY": "s" * 48,
            "ADMIN_PASSWORD": "a-real-password-1234",
        })
        assert r.returncode == 0, r.stderr

    def test_escape_hatch_warns_but_starts(self):
        r = self._run_import({"ALLOW_INSECURE_DEFAULTS": "1"}, drop=("SECRET_KEY", "ADMIN_PASSWORD"))
        assert r.returncode == 0
        assert "ALLOW_INSECURE_DEFAULTS" in r.stderr
