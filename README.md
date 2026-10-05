# INT305 ML Arena — 机器学习竞赛教学平台

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    Nginx (反向代理)                     │
│               :80 → frontend / :8080 → api            │
├──────────────────────────────────────────────────────┤
│                                                       │
│   ┌──────────────┐     ┌───────────────────────┐     │
│   │   Frontend    │     │   FastAPI Backend      │     │
│   │   (HTML/JS)   │────▶│   :8000               │     │
│   │               │     │                       │     │
│   └──────────────┘     │  ┌─ Auth (JWT)        │     │
│                         │  ├─ Competitions      │     │
│                         │  ├─ Submissions       │     │
│                         │  ├─ Leaderboard       │     │
│                         │  ├─ Task Market ★     │     │
│                         │  └─ Admin             │     │
│                         │                       │     │
│                         │  SQLite + 文件存储      │     │
│                         └───────────────────────┘     │
└──────────────────────────────────────────────────────┘
```

## ★ 任务市场（v2.0 新增）

大四学生从自己的毕业设计中拆出 ML 子任务，发布到任务市场让其他同学认领完成。

### 核心流程

```
出题者（毕设需求方）                    做题者（接单方）
     │                                      │
  发布任务 ──────────────────▶ 浏览任务市场
     │                                      │
  管理员审核 ────────────────▶ 申请接单
     │                                      │
  接受申请 ◀────────────────── 提交方案
     │                                      │
  验收交付 ◀────────────────── 提交交付物
     │                                      │
  评分 + 信用更新                         获得完成分
```

### 任务类别

| 类别 | 说明 | 示例 |
|------|------|------|
| 数据预处理 Pipeline | 数据清洗、特征工程 | 医学图像增强、文本预处理 |
| 模型训练脚本 | 指定架构+数据集的训练代码 | ResNet 分类器、BERT 微调 |
| 可视化 Dashboard | 交互式数据展示 | 训练曲线、混淆矩阵面板 |
| API/Docker | 模型封装为可部署服务 | Flask API + Docker 镜像 |
| 基线复现 | 复现论文基线结果 | 复现某论文的实验 |
| 测试/Benchmark | 单元测试和性能基准 | 模型推理速度测试 |

### 信用体系

- 初始信用分：100
- 按时交付：+2，逾期：-2
- 一次通过：+3，需修改：-1，被拒：-3
- 信用分影响接单优先级

### API 端点（21 个）

```
GET    /market/tasks                    浏览任务市场
GET    /market/tasks/{id}               查看任务详情
POST   /market/tasks                    发布任务
PUT    /market/tasks/{id}               修改任务
DELETE /market/tasks/{id}               取消任务
GET    /market/tasks/pending/list       待审核任务（管理员）
POST   /market/tasks/{id}/review        审核任务（管理员）
POST   /market/tasks/{id}/apply         申请接单
GET    /market/tasks/{id}/applications  查看申请列表
POST   /market/applications/{id}/action 接受/拒绝申请
POST   /market/applications/{id}/withdraw 撤回申请
POST   /market/tasks/{id}/deliver       提交交付物
POST   /market/tasks/{id}/deliver/upload 上传附件
GET    /market/tasks/{id}/deliveries    查看交付列表
POST   /market/deliveries/{id}/review   验收交付物
GET    /market/credit/me                我的信用分
GET    /market/credit/leaderboard       信用排行榜
GET    /market/my/posted                我发布的任务
GET    /market/my/applied               我申请的任务
GET    /market/stats                    市场统计
```

## ★ 讲轨（v2.1 新增）：把「讲」做成一等交付物

平台原本只能验证「你做出来了」，不能验证「你懂了」；而排行榜的最优策略（换权重 + 调参）
恰恰是最不需要理解的一条路。讲轨补上缺失的那一半。

五步闭环：**认领概念卡 → 回讲三件套 → 全员质询 → 助教裁定卡壳 → 重构第二版**。

- 概念卡种子 20 条（附录 B），含 d2l 中英定位、**判定边界**（回讲是否到位的判定依据）、常见卡壳点、高危术语
- 卡壳点面板：`/gaps.html`（教师端），回答「这周学生到底在哪里讲不通」，按概念卡排序给出下周讲课顺序
- 当前范围：采集链路 + 只读视图。**不改变任何现有教学流程**，四维打分与两道闸门在迭代二

```
GET    /explain/concepts                概念卡列表（登录）
POST   /explain/concepts                创建概念卡（管理员）
POST   /explain/concepts/import         批量导入概念卡（管理员，按 code 幂等）
GET    /explain/concepts/{id}           概念卡详情（含回讲与质询）
POST   /explain/concepts/{id}/claim     认领（一卡一组，单语句原子抢占）
POST   /explain/concepts/{id}/release   释放认领
POST   /explain/claims                  提交回讲三件套
GET    /explain/claims                  质询池（全班可见）
POST   /explain/claims/{id}/challenge   提交质询（须为疑问句）
POST   /explain/claims/{id}/revise      提交第二版（revision_diff 必填）
POST   /explain/challenges/{id}/respond 讲解组回应
POST   /explain/challenges/{id}/arbitrate 裁定卡壳点（教师）
GET    /explain/gaps/summary            卡壳点聚合视图（教师）★
GET    /explain/gaps                    卡壳点明细（教师）
GET    /explain/me                      我的讲轨进度
```

## 快速部署（Docker 一键启动）

```bash
# 1. 克隆项目
cd int305-arena

# 2. 配置环境变量（⚠️ 必须）
cp .env.example .env
# 编辑 .env，至少填好 SECRET_KEY 与 ADMIN_PASSWORD：
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# 这两个值为空或仍是示例值时，应用会拒绝启动并给出提示。

# 3. 一键启动
docker-compose up -d

# 4. 初始化数据库、管理员账号与 20 条概念卡种子
docker exec int305-api python scripts/init_db.py

# 5. 访问
# 前端: http://your-server
# API:  http://your-server/api
# 讲轨卡壳点面板: http://your-server/gaps.html
```

## 手动部署（无 Docker）

```bash
# 1. 安装 Python 依赖
cd backend
pip install -r requirements.txt

# 2. 初始化数据库（含概念卡种子）
python scripts/init_db.py

# 3. 启动后端
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. 用 Nginx 代理前端和 API
# 参见 nginx.conf
```

## 测试

```bash
cd backend
pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m pytest tests/ -q      # Windows
# python -m pytest tests/ -q                        # Linux/macOS
```

真实服务器验收（起真 uvicorn、走真 HTTP）：

```bash
cd backend && ./.venv/Scripts/python.exe ../audit/verify_iter1.py
```

## 旧版本升级提示

从 v2.0 升级到 v2.1 有两处**必须处理**的变更：

1. **补上 `SECRET_KEY` / `ADMIN_PASSWORD`** —— 否则服务起不来（原来会静默用公开兜底值）。
2. **迁移标准答案**：答案文件已改存 `ANSWERS_DIR`（默认 `data/answers`），
   且 `datasets` / `uploads` 的无鉴权静态挂载已移除。存量实例执行：

```bash
cd backend
python scripts/migrate_answers.py --dry-run   # 先看会动哪些文件
python scripts/migrate_answers.py             # 实际迁移
```

已部署过的实例，**S1（答案可匿名下载）应按「已泄露」处理**：核对排行榜有无异常满分提交。

## 学生使用流程

1. **注册** → 用学校邮箱注册账号（需管理员审核或自动通过）
2. **登录** → 进入平台，查看竞赛列表
3. **下载数据** → 每场竞赛提供训练集、测试集、样例提交、基线代码
4. **本地训练** → 在自己电脑上训练模型
5. **提交结果** → 上传预测文件（CSV/JSON），系统自动评分
6. **查看排名** → 实时排行榜，看到自己的排名和分数
7. **迭代优化** → 每天最多提交 N 次，持续改进

## 管理员操作

1. **创建竞赛** → 设置标题、描述、评估指标、截止时间、提交上限
2. **上传数据集** → 训练集、测试集、样例提交文件
3. **审核学生** → 批准注册或设置自动通过
4. **查看提交** → 审查学生代码和报告
5. **导出成绩** → 一键导出最终成绩表

## 核心技术栈

- **后端**: FastAPI + SQLAlchemy + SQLite
- **认证**: JWT (JSON Web Token)
- **文件存储**: 本地文件系统（可扩展至 S3）
- **自动评分**: Python 评估脚本（RMSE, Accuracy, AUC-ROC, F1 等）
- **前端**: 原生 HTML/CSS/JS（零依赖，易定制）
- **部署**: Docker + Docker Compose + Nginx

## 参考资源

- [D21 AI 任务市场](https://zh.d21.ai/) — AI 任务众包平台，参考了其任务发布格式和验收流程设计
