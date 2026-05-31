# INT305 ML Arena v2.0 — 技术栈全景映射

## 教授技术栈全景（27 个原创仓库）

### 🦀 Rust 基础设施层（5 个仓库）
| 仓库 | 核心能力 | 可复用于教学平台 |
|------|----------|-----------------|
| **FedCtx** (unified-fl-backend) | 单二进制联邦语义基础设施：HNSW向量搜索 + 知识图谱 + SHA-256审计链 + Ebbinghaus记忆 + FedAvg/FedProx/EWA + GraphRAG + MCP + gRPC + REST | ⭐⭐⭐ **核心后端引擎** |
| **organoid-fl** | 类器官图像FL平台：Rust向量DB + HNSW + 区块链审计 + gRPC + Axum Dashboard | ⭐⭐⭐ FL竞赛后端 |
| **embodied-fl** | 具身智能FL：贡献度追踪 + 任务嵌入 + HNSW + VLA服务 | ⭐⭐ 贡献度评分系统 |
| **FundFL** | 金融FL：幻觉检测 + Agent + HNSW + 审计 | ⭐⭐ 反作弊/幻觉检测 |
| **federated-ai-platform** | 联邦AI平台：Agent + 审计 + 幻觉检测 + 向量DB | ⭐⭐ 平台架构参考 |

### 🐍 Python 联邦学习应用层（8 个仓库）
| 仓库 | 核心能力 | 可复用于教学平台 |
|------|----------|-----------------|
| **ewa-fed** | 熵加权聚合监控框架 + Streamlit Dashboard | ⭐⭐⭐ FL竞赛监控面板 |
| **PCB-Defect-FL** | PCB缺陷检测FL：YOLOv11 + DINOv2 + 54测试通过 | ⭐⭐ 计算机视觉竞赛模板 |
| **medical-fl** | 医学图像FL：ViT + MAE + UNet + Dice/IoU/AUC/F1 | ⭐⭐⭐ 医学图像竞赛模板 |
| **reading-fl** | 阅读情感FL：情绪识别 + 联邦训练 | ⭐⭐ NLP竞赛模板 |
| **twc-fl-prod** | 三元催化剂FL：隐私保护 + 跨企业协作 | ⭐⭐ 工业应用案例 |
| **embroidery-agent** | 刺绣AI Agent：Rust后端 + gRPC + Web前端 | ⭐⭐ Agent竞赛模板 |
| **NeuroSync** | fMRI预测：对比学习 + SHAP可解释 + CROWN防御 | ⭐⭐ 可解释AI教学 |
| **defect-fl** | 缺陷检测FL v1（已被PCB-Defect-FL取代） | ⭐ 归档 |

### 🧬 生物医学AI层（2 个仓库）
| 仓库 | 核心能力 | 可复用于教学平台 |
|------|----------|-----------------|
| **mediaai-platform** | 培养基优化AI：贝叶斯优化 + U-Net++分割 + FL + 审计链 | ⭐⭐⭐ 独特竞赛数据集+贝叶斯优化教学 |
| **organoid-fl** (同上) | 类器官图像分析 | ⭐⭐⭐ 独特竞赛数据集 |

### 💰 金融AI层（2 个仓库）
| 仓库 | 核心能力 | 可复用于教学平台 |
|------|----------|-----------------|
| **mutual-fund-risk-adjusted-performance** | 基金风险调整绩效：63只基金60个月数据 | ⭐⭐ 回归竞赛数据集 |
| **monetary-policy-lab** | 货币政策实验室 | ⭐⭐ 时间序列竞赛数据集 |

### 🤖 AI Agent + 公益层（2 个仓库）
| 仓库 | 核心能力 | 可复用于教学平台 |
|------|----------|-----------------|
| **pai** | 公益资产智能：联邦RAG + 审计 + 云端 | ⭐⭐ RAG竞赛 + 伦理教学 |
| **NeuroSync** (同上) | fMRI + 可解释AI | ⭐⭐ |

### 🎨 创意/前端层（4 个仓库）
| 仓库 | 核心能力 | 可复用于教学平台 |
|------|----------|-----------------|
| **dgy-treehole** | 红楼梦心理疗愈H5：纯HTML/CSS/JS零依赖 | ⭐⭐ 前端设计参考 |
| **suzhou-tt-research** | React + TypeScript + Vite | ⭐⭐ 前端技术栈 |
| **AIBT2026** | AI商业转型展示 | ⭐ 展示页 |
| **dechang64.github.io** | 个人主页 | ⭐ |

### 📖 技术转移/OPC层（3 个仓库）
| 仓库 | 核心能力 | 可复用于教学平台 |
|------|----------|-----------------|
| **AI-for-TT-OPC** | OPC技术转移全链路指南（3星，最热门） | ⭐⭐ 产教融合/创业教学 |
| **hw_opc_platform** | 华为OPC平台 | ⭐ |
| **tt_opc_platform** | TT OPC平台 | ⭐ |

---

## 核心技术能力总结

1. **Rust 全栈**：HNSW向量DB、gRPC、REST、MCP、区块链审计、Web Dashboard
2. **联邦学习全链路**：FedAvg/FedProx/EWA聚合、差分隐私、贡献度追踪、Non-IID处理
3. **多模态ML**：CV(YOLO/DINOv2/U-Net++)、NLP(情感分析)、医学图像(ViT/MAE)、fMRI
4. **可解释AI**：SHAP、Grad-CAM、CROWN防御
5. **贝叶斯优化**：高斯过程、Expected Improvement
6. **知识图谱 + GraphRAG**：语义检索增强生成
7. **Ebbinghaus记忆模型**：遗忘曲线感知的记忆存储
8. **审计链**：SHA-256 + Ed25519签名 + Merkle根
9. **Streamlit Dashboard**：快速原型和数据可视化
10. **真实数据集**：类器官图像、PCB缺陷、fMRI、基金、催化剂、培养基
