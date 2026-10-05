"""讲轨路由 —— 把「讲」做成一等交付物

设计依据：《INT305 ML Arena 教学重构方案》第四、五章。

平台现状诊断：排行榜的最优策略是「换权重 + 调参」，而这恰恰是最不需要理解的一条路
—— 激励在主动奖励「不懂」。本模块补上缺失的那一半：**验证「你懂了」**。

五步闭环：认领概念卡 → 回讲三件套 → 全员质询 → 助教裁定卡壳 → 重构第二版。

迭代一边界（本文件当前实现范围）：
  ✅ 认领 / 回讲 / 质询 / 裁定 / 第二版 / 卡壳聚合视图
  ⏳ 四维打分、与竞赛提交和任务验收的两道闸门 → 迭代二

因此本模块**不改变任何现有教学流程**：即使中途搁置，也不影响当前教学。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import (
    ClaimStatus, Concept, ConceptStatus, ConceptTrack,
    CreditScore, ExplainChallenge, ExplainClaim, User, UserRole,
)
from ..schemas import (
    ArbitrateRequest, ChallengeCreate, ChallengeRespond, ChallengeResponse,
    ClaimCreate, ClaimResponse, ClaimRevise, ConceptBrief, ConceptClaimRequest,
    ConceptCreate, ConceptResponse, GapConceptItem, GapDetailItem,
    GapSeverityBucket, GapSummary, GapTrackBucket, GapWeekBucket, MyExplainResponse,
)
from ..utils import jdump, jload

router = APIRouter(prefix="/explain", tags=["讲轨"])

_VALID_TRACKS = {t.value for t in ConceptTrack}

# 疑问句的宽松判定：结尾问号，或含中文疑问标记词。
# 刻意不做严格语法检查 —— 目标是拦住「陈述句冒充提问」，不是考语文。
_INTERROGATIVE_MARKERS = ("为什么", "怎么", "如何", "什么", "哪些", "是否", "能否", "吗", "请问", "多少")


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _concept_to_response(c: Concept) -> ConceptResponse:
    return ConceptResponse(
        id=c.id, code=c.code, title=c.title,
        d2l_ref_zh=c.d2l_ref_zh, d2l_ref_en=c.d2l_ref_en, d2l_url=c.d2l_url,
        boundary=c.boundary,
        common_gaps=jload(c.common_gaps, []),
        jargon_watchlist=jload(c.jargon_watchlist, []),
        track=c.track, claimed_by_group=c.claimed_by_group,
        claimed_by_user_id=c.claimed_by_user_id,
        status=c.status, created_at=c.created_at,
    )


def _claim_to_response(db: Session, claim: ExplainClaim) -> ClaimResponse:
    concept = db.query(Concept).filter(Concept.id == claim.concept_id).first()
    user = db.query(User).filter(User.id == claim.user_id).first()
    challenges = db.query(ExplainChallenge).filter(ExplainChallenge.claim_id == claim.id).all()
    return ClaimResponse(
        id=claim.id, concept_id=claim.concept_id,
        concept_code=concept.code if concept else None,
        concept_title=concept.title if concept else None,
        user_id=claim.user_id, user_name=user.name if user else None,
        group_name=claim.group_name,
        plain_text=claim.plain_text, analogy=claim.analogy, counterexample=claim.counterexample,
        version=claim.version, parent_id=claim.parent_id,
        revision_diff=claim.revision_diff, gap_closed=bool(claim.gap_closed),
        status=claim.status,
        challenge_count=len(challenges),
        gap_count=sum(1 for c in challenges if c.is_gap),
        created_at=claim.created_at,
    )


def _challenge_to_response(db: Session, ch: ExplainChallenge) -> ChallengeResponse:
    claim = db.query(ExplainClaim).filter(ExplainClaim.id == ch.claim_id).first()
    concept = db.query(Concept).filter(Concept.id == claim.concept_id).first() if claim else None
    challenger = db.query(User).filter(User.id == ch.challenger_id).first()
    return ChallengeResponse(
        id=ch.id, claim_id=ch.claim_id,
        concept_code=concept.code if concept else None,
        concept_title=concept.title if concept else None,
        challenger_id=ch.challenger_id,
        challenger_name=challenger.name if challenger else None,
        question=ch.question, uses_concept_term=bool(ch.uses_concept_term),
        response=ch.response, is_gap=ch.is_gap, gap_severity=ch.gap_severity,
        arbiter_id=ch.arbiter_id,
        created_at=ch.created_at, responded_at=ch.responded_at,
    )


def _looks_like_question(text: str) -> bool:
    t = text.strip()
    if t.endswith(("?", "？")):
        return True
    return any(marker in t for marker in _INTERROGATIVE_MARKERS)


def _uses_concept_term(question: str, concept: Concept) -> bool:
    """质询里是否直接使用了被讲概念的核心术语。

    不是硬拦截 —— 这是一个**给裁定助教看的信号**：
    「你能解释一下什么是批量规范化吗」这类问题对被讲者不构成任何检验，
    记下来让裁定者知道该条质询含金量低。硬拦截会误伤真正的好问题
    （如「偏导在反向传播里是怎么被消掉的」）。
    """
    text = question or ""
    terms = set()
    if concept.title:
        terms.add(concept.title)
    for term in jload(concept.jargon_watchlist, []) or []:
        if isinstance(term, str) and term.strip():
            terms.add(term.strip())
    return any(term and term in text for term in terms)


def _closed_parent_ids(db: Session) -> set:
    """一次性取出「有已关闭第二版」的第一版 id 集合（避免在聚合里逐行查询）。"""
    return {
        parent_id for (parent_id,) in db.query(ExplainClaim.parent_id).filter(
            ExplainClaim.gap_closed == True,  # noqa: E712
            ExplainClaim.parent_id.isnot(None),
        ).all()
    }


# ---------------------------------------------------------------------------
# 概念卡
# ---------------------------------------------------------------------------

@router.get("/concepts", response_model=List[ConceptBrief], summary="概念卡列表")
def list_concepts(
    track: Optional[str] = None,
    status: Optional[str] = None,
    claimed: Optional[bool] = Query(None, description="true=只看已被认领的"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """概念卡地图。全班可见，是「认领」的入口。"""
    query = db.query(Concept)
    if track:
        query = query.filter(Concept.track == track)
    if status:
        query = query.filter(Concept.status == status)
    if claimed is True:
        query = query.filter(Concept.claimed_by_group.isnot(None))
    elif claimed is False:
        query = query.filter(Concept.claimed_by_group.is_(None))

    concepts = query.order_by(Concept.code).all()

    # 一次查全量再在内存里统计，避免 N+1（一个班的规模下远快于逐卡查询）
    claim_rows = db.query(ExplainClaim.id, ExplainClaim.concept_id).all()
    claims_per_concept = defaultdict(int)
    claim_ids = []
    for claim_id, concept_id in claim_rows:
        claims_per_concept[concept_id] += 1
        claim_ids.append(claim_id)

    gaps_per_concept = defaultdict(int)
    if claim_ids:
        gap_rows = db.query(ExplainChallenge.claim_id).filter(
            ExplainChallenge.claim_id.in_(claim_ids),
            ExplainChallenge.is_gap == True,  # noqa: E712
        ).all()
        claim_to_concept = {cid: cid2 for cid, cid2 in claim_rows}
        for (claim_id,) in gap_rows:
            gaps_per_concept[claim_to_concept.get(claim_id)] += 1

    return [
        ConceptBrief(
            id=c.id, code=c.code, title=c.title, d2l_ref_zh=c.d2l_ref_zh,
            track=c.track, status=c.status, claimed_by_group=c.claimed_by_group,
            claim_count=claims_per_concept.get(c.id, 0),
            gap_count=gaps_per_concept.get(c.id, 0),
        )
        for c in concepts
    ]


@router.post("/concepts", response_model=ConceptResponse, summary="创建概念卡（管理员）")
def create_concept(
    req: ConceptCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if req.track not in _VALID_TRACKS:
        raise HTTPException(status_code=422, detail=f"track 必须是 {sorted(_VALID_TRACKS)} 之一")
    if db.query(Concept).filter(Concept.code == req.code).first():
        raise HTTPException(status_code=409, detail=f"概念卡编号 {req.code} 已存在")

    concept = Concept(
        code=req.code, title=req.title,
        d2l_ref_zh=req.d2l_ref_zh, d2l_ref_en=req.d2l_ref_en, d2l_url=req.d2l_url,
        boundary=req.boundary,
        common_gaps=jdump(req.common_gaps or []),
        jargon_watchlist=jdump(req.jargon_watchlist or []),
        track=req.track, status=ConceptStatus.OPEN,
    )
    db.add(concept)
    db.commit()
    db.refresh(concept)
    return _concept_to_response(concept)


@router.post("/concepts/import", summary="批量导入概念卡（管理员）")
def import_concepts(
    concepts: List[ConceptCreate],
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """按 code 幂等 upsert。用于把备课清单（附录 B 的 20 条）一次灌进库里。"""
    created, updated = 0, 0
    for item in concepts:
        if item.track not in _VALID_TRACKS:
            raise HTTPException(status_code=422, detail=f"{item.code}: track 非法")
        concept = db.query(Concept).filter(Concept.code == item.code).first()
        if concept is None:
            concept = Concept(code=item.code, status=ConceptStatus.OPEN)
            db.add(concept)
            created += 1
        else:
            updated += 1
        concept.title = item.title
        concept.d2l_ref_zh = item.d2l_ref_zh
        concept.d2l_ref_en = item.d2l_ref_en
        concept.d2l_url = item.d2l_url
        concept.boundary = item.boundary
        concept.common_gaps = jdump(item.common_gaps or [])
        concept.jargon_watchlist = jdump(item.jargon_watchlist or [])
        concept.track = item.track
    db.commit()
    return {"created": created, "updated": updated, "total": created + updated}


@router.get("/concepts/{concept_id}", summary="概念卡详情（含回讲与质询）")
def get_concept(
    concept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    concept = db.query(Concept).filter(Concept.id == concept_id).first()
    if not concept:
        raise HTTPException(status_code=404, detail="概念卡不存在")

    claims = db.query(ExplainClaim).filter(
        ExplainClaim.concept_id == concept_id
    ).order_by(ExplainClaim.version, ExplainClaim.created_at).all()

    payload = _concept_to_response(concept).model_dump()
    payload["claims"] = [_claim_to_response(db, c).model_dump() for c in claims]
    return payload


@router.post("/concepts/{concept_id}/claim", summary="认领概念卡")
def claim_concept(
    concept_id: int,
    req: ConceptClaimRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """一组认领一张卡。

    并发安全：用 `UPDATE ... WHERE claimed_by_group IS NULL` 单语句抢占，
    以影响行数判定成败。这比「先查再写」可靠 —— 后者在两个人同时点击时
    会双双通过检查（典型的 TOCTOU 竞态：检查与写入之间存在时间窗）。
    """
    concept = db.query(Concept).filter(Concept.id == concept_id).first()
    if not concept:
        raise HTTPException(status_code=404, detail="概念卡不存在")

    rows = db.query(Concept).filter(
        Concept.id == concept_id,
        Concept.claimed_by_group.is_(None),
    ).update(
        {
            "claimed_by_group": req.group_name,
            "claimed_by_user_id": current_user.id,
            "status": ConceptStatus.CLAIMED,
        },
        synchronize_session=False,
    )
    db.commit()

    if rows == 0:
        db.refresh(concept)
        raise HTTPException(
            status_code=409,
            detail=f"该概念卡已被「{concept.claimed_by_group}」认领",
        )

    db.refresh(concept)
    return _concept_to_response(concept)


@router.post("/concepts/{concept_id}/release", summary="释放概念卡（认领者本人或管理员）")
def release_concept(
    concept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    concept = db.query(Concept).filter(Concept.id == concept_id).first()
    if not concept:
        raise HTTPException(status_code=404, detail="概念卡不存在")
    if concept.claimed_by_user_id is None:
        raise HTTPException(status_code=400, detail="该概念卡尚未被认领")
    if concept.claimed_by_user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能释放自己认领的概念卡")

    concept.claimed_by_group = None
    concept.claimed_by_user_id = None
    concept.status = ConceptStatus.OPEN
    db.commit()
    db.refresh(concept)
    return _concept_to_response(concept)


# ---------------------------------------------------------------------------
# 回讲三件套
# ---------------------------------------------------------------------------

@router.post("/claims", response_model=ClaimResponse, summary="提交回讲三件套")
def create_claim(
    req: ClaimCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    concept = db.query(Concept).filter(Concept.id == req.concept_id).first()
    if not concept:
        raise HTTPException(status_code=404, detail="概念卡不存在")

    if concept.claimed_by_user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="请先认领该概念卡再提交回讲")

    # 已有关联的第二版时不允许再提交第一版（避免一卡多份第一版）
    existing_v1 = db.query(ExplainClaim).filter(
        ExplainClaim.concept_id == concept.id,
        ExplainClaim.version == 1,
    ).first()
    if existing_v1:
        raise HTTPException(
            status_code=409,
            detail=f"该概念卡已有一份第一版回讲（id={existing_v1.id}），请改用第二版接口修订",
        )

    claim = ExplainClaim(
        concept_id=concept.id,
        user_id=current_user.id,
        group_name=req.group_name or concept.claimed_by_group,
        plain_text=req.plain_text,
        analogy=req.analogy,
        counterexample=req.counterexample,
        version=1,
        status=ClaimStatus.SUBMITTED,
    )
    db.add(claim)
    concept.status = ConceptStatus.EXPLAINING
    db.commit()
    db.refresh(claim)
    return _claim_to_response(db, claim)


@router.get("/claims", response_model=List[ClaimResponse], summary="质询池（全班可见）")
def list_claims(
    concept_id: Optional[int] = None,
    status: Optional[str] = None,
    mine: bool = Query(False, description="只看我提交的"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ExplainClaim)
    if concept_id:
        query = query.filter(ExplainClaim.concept_id == concept_id)
    if status:
        query = query.filter(ExplainClaim.status == status)
    if mine:
        query = query.filter(ExplainClaim.user_id == current_user.id)

    claims = query.order_by(ExplainClaim.created_at.desc()).limit(200).all()
    return [_claim_to_response(db, c) for c in claims]


@router.post("/claims/{claim_id}/revise", response_model=ClaimResponse, summary="提交第二版回讲")
def revise_claim(
    claim_id: int,
    req: ClaimRevise,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重构第二版。

    `revision_diff`（「我第一版漏了什么」）必填 —— 这是全机制里**最难被 AI 代写**的一环：
    没有模型知道这个学生第一版的漏洞在哪。凡要求「自我诊断」的环节，代写的边际收益
    远低于抄袭成本，比查重或禁 AI 都更有效。
    """
    parent = db.query(ExplainClaim).filter(ExplainClaim.id == claim_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="回讲不存在")
    if parent.user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有讲解组可以提交第二版")
    if parent.version != 1:
        raise HTTPException(status_code=400, detail="只能对第一版提交第二版")

    existing = db.query(ExplainClaim).filter(ExplainClaim.parent_id == parent.id).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"该回讲已有第二版（id={existing.id}）")

    if not (req.revision_diff or "").strip():
        raise HTTPException(status_code=422, detail="第二版必须填写 revision_diff：我第一版漏了什么")

    revision = ExplainClaim(
        concept_id=parent.concept_id,
        user_id=current_user.id,
        group_name=parent.group_name,
        plain_text=req.plain_text,
        analogy=req.analogy,
        counterexample=req.counterexample,
        version=2,
        parent_id=parent.id,
        revision_diff=req.revision_diff.strip(),
        gap_closed=req.gap_closed,
        status=ClaimStatus.REVISED,
    )
    db.add(revision)
    parent.status = ClaimStatus.REVISED
    if req.gap_closed:
        concept = db.query(Concept).filter(Concept.id == parent.concept_id).first()
        if concept:
            concept.status = ConceptStatus.CLOSED
    db.commit()
    db.refresh(revision)
    return _claim_to_response(db, revision)


# ---------------------------------------------------------------------------
# 质询
# ---------------------------------------------------------------------------

@router.post("/claims/{claim_id}/challenge", response_model=ChallengeResponse, summary="提交质询")
def create_challenge(
    claim_id: int,
    req: ChallengeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = db.query(ExplainClaim).filter(ExplainClaim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="回讲不存在")
    if claim.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能质询自己提交的回讲")

    concept = db.query(Concept).filter(Concept.id == claim.concept_id).first()

    if not _looks_like_question(req.question):
        raise HTTPException(
            status_code=422,
            detail="质询必须是一个疑问句（以 ? / ？ 结尾，或包含「如何/为什么/是否」等疑问词）",
        )

    challenge = ExplainChallenge(
        claim_id=claim.id,
        challenger_id=current_user.id,
        question=req.question.strip(),
        uses_concept_term=_uses_concept_term(req.question, concept) if concept else False,
    )
    db.add(challenge)
    if claim.status == ClaimStatus.SUBMITTED:
        claim.status = ClaimStatus.CHALLENGED
    db.commit()
    db.refresh(challenge)
    return _challenge_to_response(db, challenge)


@router.post("/challenges/{challenge_id}/respond", response_model=ChallengeResponse, summary="讲解组回应质询")
def respond_challenge(
    challenge_id: int,
    req: ChallengeRespond,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    challenge = db.query(ExplainChallenge).filter(ExplainChallenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="质询不存在")

    claim = db.query(ExplainClaim).filter(ExplainClaim.id == challenge.claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="回讲不存在")
    if claim.user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有讲解组可以回应质询")

    challenge.response = req.response
    challenge.responded_at = datetime.utcnow()
    db.commit()
    db.refresh(challenge)
    return _challenge_to_response(db, challenge)


@router.post("/challenges/{challenge_id}/arbitrate", response_model=ChallengeResponse, summary="裁定卡壳点（助教/管理员）")
def arbitrate_challenge(
    challenge_id: int,
    req: ArbitrateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """裁定这条质询是否命中卡壳点。

    迭代一由管理员（教师）兼任裁定者；专门的 TA 角色在迭代二引入
    —— 需同步扩展 UserRole 与管理端授权流程，不宜混在本次改动里。
    """
    challenge = db.query(ExplainChallenge).filter(ExplainChallenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="质询不存在")

    if req.is_gap and req.gap_severity is None:
        raise HTTPException(status_code=422, detail="判定为卡壳点时必须给出 gap_severity (1–3)")

    challenge.is_gap = req.is_gap
    challenge.gap_severity = req.gap_severity if req.is_gap else None
    challenge.arbiter_id = admin.id
    db.commit()

    if req.is_gap:
        claim = db.query(ExplainClaim).filter(ExplainClaim.id == challenge.claim_id).first()
        if claim:
            concept = db.query(Concept).filter(Concept.id == claim.concept_id).first()
            if concept and concept.status != ConceptStatus.CLOSED:
                concept.status = ConceptStatus.CHALLENGED
                db.commit()

    db.refresh(challenge)
    return _challenge_to_response(db, challenge)


@router.get("/challenges", response_model=List[ChallengeResponse], summary="质询列表")
def list_challenges(
    claim_id: Optional[int] = None,
    concept_id: Optional[int] = None,
    only_gaps: bool = Query(False),
    pending: bool = Query(False, description="只看尚未裁定的"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ExplainChallenge)
    if claim_id:
        query = query.filter(ExplainChallenge.claim_id == claim_id)
    if concept_id:
        claim_ids = [
            cid for (cid,) in db.query(ExplainClaim.id).filter(ExplainClaim.concept_id == concept_id).all()
        ]
        query = query.filter(ExplainChallenge.claim_id.in_(claim_ids or [-1]))
    if only_gaps:
        query = query.filter(ExplainChallenge.is_gap == True)  # noqa: E712
    if pending:
        query = query.filter(ExplainChallenge.is_gap.is_(None))

    rows = query.order_by(ExplainChallenge.created_at.desc()).limit(300).all()
    return [_challenge_to_response(db, c) for c in rows]


# ---------------------------------------------------------------------------
# 卡壳点聚合视图（教师端核心产物）
# ---------------------------------------------------------------------------

@router.get("/gaps/summary", response_model=GapSummary, summary="卡壳点聚合（教师端）")
def gaps_summary(
    track: Optional[str] = None,
    concept_id: Optional[int] = None,
    min_severity: Optional[int] = Query(None, ge=1, le=3),
    top: int = Query(20, ge=1, le=100, description="按概念聚合时返回前 N 张卡"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """回答一个具体问题：**这周学生到底在哪里讲不通？**

    这是讲轨机制里唯一不改变现有流程、却能立刻给出教学决策依据的产物 ——
    下周的课堂只需要讲这里排名靠前的几张概念卡。

    实现说明：聚合在 Python 侧完成而非 SQL。原因是 Week 分桶需要 ISO 周
    （``%W``/``strftime`` 在不同 SQLite 版本与年份边界上有差异），且一个班的
    数据量在千行级，全量取回后聚合更快也更好验证。
    """
    rows = (
        db.query(ExplainChallenge, ExplainClaim, Concept)
        .join(ExplainClaim, ExplainChallenge.claim_id == ExplainClaim.id)
        .join(Concept, ExplainClaim.concept_id == Concept.id)
        .all()
    )

    # --- 过滤 ---
    def keep(ch: ExplainChallenge, claim: ExplainClaim, concept: Concept) -> bool:
        if track and concept.track != track:
            return False
        if concept_id and concept.id != concept_id:
            return False
        if min_severity is not None:
            if not ch.is_gap or (ch.gap_severity or 0) < min_severity:
                return False
        return True

    rows = [(ch, cl, cp) for (ch, cl, cp) in rows if keep(ch, cl, cp)]

    total_gaps = 0
    adjudicated = 0
    pending = 0
    open_gaps = 0

    per_concept = defaultdict(lambda: {
        "gap_count": 0, "severities": [], "adjudicated": 0,
        "claims": set(), "challenges": 0, "samples": [], "last": None, "open": 0,
    })
    severity_hist = defaultdict(int)
    track_stats = defaultdict(lambda: {"gap": 0, "concepts": set()})
    week_stats = defaultdict(int)

    # 第二版是否关闭了卡壳点：一次性建索引，避免逐行查询
    revised_closed = _closed_parent_ids(db)

    for ch, claim, concept in rows:
        bucket = per_concept[concept.id]
        bucket["claims"].add(claim.id)
        bucket["challenges"] += 1

        if ch.is_gap is None:
            pending += 1
            continue

        adjudicated += 1
        bucket["adjudicated"] += 1
        if not ch.is_gap:
            continue

        total_gaps += 1
        sev = ch.gap_severity or 1
        bucket["gap_count"] += 1
        bucket["severities"].append(sev)
        if len(bucket["samples"]) < 3:
            bucket["samples"].append(ch.question)
        if bucket["last"] is None or ch.created_at > bucket["last"]:
            bucket["last"] = ch.created_at

        severity_hist[sev] += 1
        track_stats[concept.track]["gap"] += 1
        track_stats[concept.track]["concepts"].add(concept.id)

        iso = ch.created_at.isocalendar()
        week_stats[f"{iso[0]}-W{iso[1]:02d}"] += 1

        # 未关闭 = 该回讲既没有第二版标记关闭，也没有任何已关闭的第二版子记录
        if not (claim.gap_closed or claim.id in revised_closed):
            open_gaps += 1
            bucket["open"] += 1

    by_concept = []
    for cid, b in per_concept.items():
        if b["gap_count"] == 0 and b["adjudicated"] == 0:
            continue
        concept = next(cp for (_, _, cp) in rows if cp.id == cid)
        sevs = b["severities"]
        by_concept.append(GapConceptItem(
            concept_id=cid, code=concept.code, title=concept.title,
            d2l_ref_zh=concept.d2l_ref_zh, track=concept.track,
            gap_count=b["gap_count"], adjudicated_count=b["adjudicated"],
            avg_severity=round(sum(sevs) / len(sevs), 2) if sevs else None,
            max_severity=max(sevs) if sevs else None,
            claim_count=len(b["claims"]), challenge_count=b["challenges"],
            open_gap_count=b["open"], sample_questions=b["samples"],
            last_gap_at=b["last"],
        ))

    # 排序：卡壳点多者优先，同数量时严重度高的优先 —— 这就是下周的讲课顺序
    by_concept.sort(key=lambda x: (-x.gap_count, -(x.avg_severity or 0), x.code))

    return GapSummary(
        generated_at=datetime.utcnow(),
        total_gaps=total_gaps,
        adjudicated_challenges=adjudicated,
        pending_challenges=pending,
        open_gaps=open_gaps,
        concept_count_with_gaps=len([c for c in by_concept if c.gap_count > 0]),
        by_concept=by_concept[:top],
        by_severity=[
            GapSeverityBucket(severity=s, count=severity_hist.get(s, 0)) for s in (1, 2, 3)
        ],
        by_track=[
            GapTrackBucket(track=t, gap_count=v["gap"], concept_count=len(v["concepts"]))
            for t, v in sorted(track_stats.items(), key=lambda kv: -kv[1]["gap"])
        ],
        by_week=[
            GapWeekBucket(week=w, gap_count=c)
            for w, c in sorted(week_stats.items())
        ],
    )


@router.get("/gaps", response_model=List[GapDetailItem], summary="卡壳点明细（教师端）")
def gaps_detail(
    concept_id: Optional[int] = None,
    min_severity: Optional[int] = Query(None, ge=1, le=3),
    include_closed: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """卡壳点逐条明细，含原问题原文 —— 用于备课时看「学生究竟问的是什么」。"""
    query = (
        db.query(ExplainChallenge, ExplainClaim, Concept)
        .join(ExplainClaim, ExplainChallenge.claim_id == ExplainClaim.id)
        .join(Concept, ExplainClaim.concept_id == Concept.id)
        .filter(ExplainChallenge.is_gap == True)  # noqa: E712
    )
    if concept_id:
        query = query.filter(Concept.id == concept_id)
    if min_severity is not None:
        query = query.filter(ExplainChallenge.gap_severity >= min_severity)

    rows = query.order_by(ExplainChallenge.gap_severity.desc(), ExplainChallenge.created_at.desc()).limit(limit).all()

    revised_closed = _closed_parent_ids(db)

    result = []
    for ch, claim, concept in rows:
        closed = bool(claim.gap_closed or claim.id in revised_closed)
        if not include_closed and closed:
            continue
        challenger = db.query(User).filter(User.id == ch.challenger_id).first()
        result.append(GapDetailItem(
            challenge_id=ch.id, claim_id=claim.id,
            concept_id=concept.id, concept_code=concept.code, concept_title=concept.title,
            question=ch.question, gap_severity=ch.gap_severity, is_gap=ch.is_gap,
            gap_closed=closed,
            challenger_name=challenger.name if challenger else None,
            created_at=ch.created_at,
        ))
    return result


# ---------------------------------------------------------------------------
# 我的讲轨
# ---------------------------------------------------------------------------

@router.get("/me", response_model=MyExplainResponse, summary="我的讲轨进度")
def my_explain(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claimed = db.query(Concept).filter(Concept.claimed_by_user_id == current_user.id).order_by(Concept.code).all()

    briefs = []
    for c in claimed:
        claim_ids = [cid for (cid,) in db.query(ExplainClaim.id).filter(ExplainClaim.concept_id == c.id).all()]
        gaps = 0
        if claim_ids:
            gaps = db.query(ExplainChallenge).filter(
                ExplainChallenge.claim_id.in_(claim_ids),
                ExplainChallenge.is_gap == True,  # noqa: E712
            ).count()
        briefs.append(ConceptBrief(
            id=c.id, code=c.code, title=c.title, d2l_ref_zh=c.d2l_ref_zh,
            track=c.track, status=c.status, claimed_by_group=c.claimed_by_group,
            claim_count=len(claim_ids), gap_count=gaps,
        ))

    claims = db.query(ExplainClaim).filter(
        ExplainClaim.user_id == current_user.id
    ).order_by(ExplainClaim.created_at.desc()).all()

    raised = db.query(ExplainChallenge).filter(
        ExplainChallenge.challenger_id == current_user.id
    ).count()
    effective = db.query(ExplainChallenge).filter(
        ExplainChallenge.challenger_id == current_user.id,
        ExplainChallenge.is_gap == True,  # noqa: E712
    ).count()

    my_claim_ids = [c.id for c in claims]
    on_me = 0
    if my_claim_ids:
        on_me = db.query(ExplainChallenge).filter(
            ExplainChallenge.claim_id.in_(my_claim_ids),
            ExplainChallenge.is_gap == True,  # noqa: E712
        ).count()

    credit = db.query(CreditScore).filter(CreditScore.user_id == current_user.id).first()

    return MyExplainResponse(
        user_id=current_user.id, name=current_user.name,
        concepts_claimed=briefs,
        claims_submitted=[_claim_to_response(db, c) for c in claims],
        challenges_raised=raised,
        effective_challenges=effective,
        gaps_flagged_on_me=on_me,
        explain_score=credit.explain_score if credit else None,
        challenge_credits=credit.challenge_credits if credit else 0,
    )
