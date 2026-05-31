"""数据库初始化脚本 — 创建管理员账号和示例竞赛"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, create_tables
from app.models import User, UserRole, UserStatus, Competition, CompStatus
from app.auth import hash_password
from app.config import ADMIN_EMAIL, ADMIN_PASSWORD
from datetime import datetime, timedelta


def init():
    print("🔧 创建数据表...")
    create_tables()

    db = SessionLocal()

    try:
        # 创建管理员
        admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not admin:
            admin = User(
                email=ADMIN_EMAIL,
                name="管理员",
                student_id="ADMIN",
                hashed_password=hash_password(ADMIN_PASSWORD),
                role=UserRole.ADMIN,
                status=UserStatus.APPROVED,
                avatar_color="#ef4444"
            )
            db.add(admin)
            print(f"✅ 管理员账号已创建: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        else:
            print(f"ℹ️  管理员账号已存在: {ADMIN_EMAIL}")

        # 创建示例竞赛
        competitions_data = [
            {
                "slug": "comp1-house-price",
                "title": "🏠 房价预测挑战赛",
                "subtitle": "Linear Regression & Regularization",
                "description": "使用线性回归和正则化方法预测房屋价格。你需要从给定的特征中学习模型，并在测试集上获得最低的 RMSE。\n\n**学习目标:**\n- 线性回归原理与实现\n- 梯度下降优化\n- L1/L2 正则化\n- 特征工程基础\n\n**提交格式:** CSV 文件，包含 Id 和 SalePrice 两列",
                "lectures": "Lecture 1-2",
                "week": "Week 1-2",
                "metric": "RMSE",
                "metric_direction": "lower",
                "baseline_score": 0.15,
                "status": CompStatus.LIVE,
                "start_time": datetime.utcnow(),
                "end_time": datetime.utcnow() + timedelta(days=14),
                "max_submissions_per_day": 5,
                "max_submissions_total": 50,
                "tags": ["回归", "线性模型", "正则化"]
            },
            {
                "slug": "comp2-image-classification",
                "title": "🖼️ 图像分类对抗赛",
                "subtitle": "SVM & Softmax Classifier",
                "description": "使用支持向量机和 Softmax 分类器对图像进行分类。探索不同核函数和超参数对分类性能的影响。\n\n**学习目标:**\n- SVM 原理与核方法\n- Softmax 回归\n- 多分类策略\n- 超参数调优\n\n**提交格式:** CSV 文件，包含 Id 和 Label 两列",
                "lectures": "Lecture 3-4",
                "week": "Week 3-4",
                "metric": "Accuracy",
                "metric_direction": "higher",
                "baseline_score": 0.65,
                "status": CompStatus.UPCOMING,
                "start_time": datetime.utcnow() + timedelta(days=14),
                "end_time": datetime.utcnow() + timedelta(days=28),
                "max_submissions_per_day": 5,
                "max_submissions_total": 50,
                "tags": ["分类", "SVM", "多分类"]
            },
            {
                "slug": "comp3-cifar10",
                "title": "🔍 CIFAR-10 挑战赛",
                "subtitle": "Convolutional Neural Network",
                "description": "使用卷积神经网络对 CIFAR-10 数据集进行分类。从零开始构建 CNN，探索不同架构对性能的影响。\n\n**学习目标:**\n- 卷积层原理\n- 池化与归一化\n- 经典 CNN 架构\n- 数据增强\n\n**提交格式:** CSV 文件，包含 Id 和 Label 两列",
                "lectures": "Lecture 5-6",
                "week": "Week 5-6",
                "metric": "Accuracy",
                "metric_direction": "higher",
                "baseline_score": 0.70,
                "status": CompStatus.UPCOMING,
                "start_time": datetime.utcnow() + timedelta(days=28),
                "end_time": datetime.utcnow() + timedelta(days=42),
                "max_submissions_per_day": 5,
                "max_submissions_total": 50,
                "tags": ["CNN", "深度学习", "图像分类"]
            },
            {
                "slug": "comp4-ensemble",
                "title": "🎯 集成学习擂台赛",
                "subtitle": "Decision Trees, Bagging & Boosting",
                "description": "使用决策树、Bagging 和 Boosting 方法构建强大的集成分类器。探索不同集成策略对模型性能的提升。\n\n**学习目标:**\n- 决策树与随机森林\n- Bagging 原理\n- Boosting (AdaBoost, GBDT)\n- 偏差-方差权衡\n\n**提交格式:** CSV 文件，包含 Id 和 Probability 两列",
                "lectures": "Lecture 7-8",
                "week": "Week 7-8",
                "metric": "AUC-ROC",
                "metric_direction": "higher",
                "baseline_score": 0.80,
                "status": CompStatus.UPCOMING,
                "start_time": datetime.utcnow() + timedelta(days=42),
                "end_time": datetime.utcnow() + timedelta(days=56),
                "max_submissions_per_day": 5,
                "max_submissions_total": 50,
                "tags": ["集成学习", "决策树", "Boosting"]
            },
            {
                "slug": "comp5-text-clustering",
                "title": "📝 文本分类 & 聚类赛",
                "subtitle": "Naive Bayes, k-Means & EM",
                "description": "使用朴素贝叶斯进行文本分类，使用 k-Means 和 EM 算法进行聚类分析。同时提交分类和聚类结果。\n\n**学习目标:**\n- 朴素贝叶斯分类\n- k-Means 聚类\n- EM 算法\n- 概率图模型\n\n**提交格式:** CSV 文件，包含 Id, Label (分类), Cluster (聚类) 三列",
                "lectures": "Lecture 9-10",
                "week": "Week 9-10",
                "metric": "F1",
                "metric_direction": "higher",
                "baseline_score": 0.75,
                "status": CompStatus.UPCOMING,
                "start_time": datetime.utcnow() + timedelta(days=56),
                "end_time": datetime.utcnow() + timedelta(days=70),
                "max_submissions_per_day": 5,
                "max_submissions_total": 50,
                "tags": ["NLP", "聚类", "概率模型"]
            },
            {
                "slug": "comp6-sequence-rl",
                "title": "🎮 序列预测 & 强化学习赛",
                "subtitle": "RNN/LSTM & Reinforcement Learning",
                "description": "使用 RNN/LSTM 进行时间序列预测，并训练强化学习智能体完成控制任务。\n\n**学习目标:**\n- RNN 与 LSTM 原理\n- 序列建模\n- 强化学习基础\n- Q-Learning 与 DQN\n\n**提交格式:** CSV 文件，包含 Id 和 Prediction 两列",
                "lectures": "Lecture 11-12",
                "week": "Week 11-12",
                "metric": "MAE",
                "metric_direction": "lower",
                "baseline_score": 0.20,
                "status": CompStatus.UPCOMING,
                "start_time": datetime.utcnow() + timedelta(days=70),
                "end_time": datetime.utcnow() + timedelta(days=84),
                "max_submissions_per_day": 5,
                "max_submissions_total": 50,
                "tags": ["RNN", "强化学习", "序列预测"]
            }
        ]

        for data in competitions_data:
            existing = db.query(Competition).filter(Competition.slug == data["slug"]).first()
            if not existing:
                comp = Competition(**data)
                db.add(comp)
                print(f"✅ 竞赛已创建: {data['title']}")
            else:
                print(f"ℹ️  竞赛已存在: {data['title']}")

        db.commit()
        print("\n🎉 初始化完成！")
        print(f"\n📧 管理员登录: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print(f"🔗 API 文档: http://localhost:8000/api/docs")

    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    init()
