"""评估器 — 自动评分核心"""
import numpy as np
import pandas as pd
import json
from pathlib import Path
from sklearn.metrics import (
    mean_squared_error, accuracy_score, roc_auc_score,
    f1_score, normalized_mutual_info_score
)


class EvaluationError(Exception):
    """评估失败异常"""
    pass


def evaluate_submission(
    prediction_path: str,
    answer_path: str,
    metric: str,
    metric_direction: str = "lower"
) -> dict:
    """
    评估提交的预测文件

    Args:
        prediction_path: 学生提交的预测文件路径
        answer_path: 标准答案文件路径
        metric: 评估指标名称
        metric_direction: "lower" = 越低越好, "higher" = 越高越好

    Returns:
        {"score": float, "detail": str}
    """
    try:
        # 读取答案
        answer_df = pd.read_csv(answer_path)

        # 读取预测
        pred_df = pd.read_csv(prediction_path)

        # 验证格式
        if len(pred_df) != len(answer_df):
            raise EvaluationError(
                f"预测行数 ({len(pred_df)}) 与答案行数 ({len(answer_df)}) 不匹配"
            )

        # 计算分数
        score = _compute_metric(pred_df, answer_df, metric)

        return {
            "score": round(score, 6),
            "detail": json.dumps({
                "metric": metric,
                "value": round(score, 6),
                "direction": metric_direction,
                "num_samples": len(answer_df)
            })
        }

    except EvaluationError:
        raise
    except Exception as e:
        raise EvaluationError(f"评估失败: {str(e)}")


def _compute_metric(pred_df: pd.DataFrame, answer_df: pd.DataFrame, metric: str) -> float:
    """根据指标名称计算分数"""

    # 假设答案文件有两列: id + target
    # 预测文件也有两列: id + target (或 prediction)
    pred_col = _find_target_column(pred_df, ["target", "prediction", "label", "score", "saleprice"])
    ans_col = _find_target_column(answer_df, ["target", "label", "saleprice", "ground_truth"])

    y_true = answer_df[ans_col].values
    y_pred = pred_df[pred_col].values

    metric_lower = metric.lower().replace("-", "").replace("_", "").replace(" ", "")

    if metric_lower in ("rmse", "rootmeansquarederror"):
        return np.sqrt(mean_squared_error(y_true, y_pred))

    elif metric_lower in ("mse", "meansquarederror"):
        return mean_squared_error(y_true, y_pred)

    elif metric_lower in ("mae", "meanabsoluteerror"):
        return float(np.mean(np.abs(y_true - y_pred)))

    elif metric_lower in ("accuracy", "acc"):
        return accuracy_score(y_true, np.round(y_pred).astype(int) if y_pred.dtype == float else y_pred)

    elif metric_lower in ("aucroc", "auc", "rocauc", "aucroc"):
        return roc_auc_score(y_true, y_pred)

    elif metric_lower in ("f1", "f1score", "f1macro"):
        y_pred_int = np.round(y_pred).astype(int) if y_pred.dtype == float else y_pred
        return f1_score(y_true, y_pred_int, average="macro")

    elif metric_lower in ("nmi", "normalizedmutualinfo"):
        return normalized_mutual_info_score(y_true.astype(int), y_pred.astype(int))

    elif metric_lower in ("logloss", "crossentropy"):
        from sklearn.metrics import log_loss
        return log_loss(y_true, y_pred)

    else:
        raise EvaluationError(f"不支持的评估指标: {metric}")


def _find_target_column(df: pd.DataFrame, candidates: list) -> str:
    """在 DataFrame 中找到目标列"""
    cols_lower = {c.lower(): c for c in df.columns}

    # 排除 id 列
    for candidate in candidates:
        if candidate.lower() in cols_lower:
            return cols_lower[candidate.lower()]

    # 取最后一列（通常 id 在前，target 在后）
    if len(df.columns) >= 2:
        return df.columns[-1]

    raise EvaluationError(f"无法确定目标列。可用列: {list(df.columns)}")


def validate_prediction_format(prediction_path: str, answer_path: str) -> tuple:
    """
    验证预测文件格式是否正确

    Returns:
        (is_valid, error_message)
    """
    try:
        pred_df = pd.read_csv(prediction_path)
        ans_df = pd.read_csv(answer_path)

        if len(pred_df) != len(ans_df):
            return False, f"行数不匹配: 预测 {len(pred_df)} 行, 答案 {len(ans_df)} 行"

        # 检查 id 列是否一致
        id_col = ans_df.columns[0]
        if id_col not in pred_df.columns:
            return False, f"缺少 ID 列: {id_col}"

        if not pred_df[id_col].equals(ans_df[id_col]):
            return False, "ID 列与答案不匹配"

        # 检查是否有 NaN
        target_col = pred_df.columns[-1]
        if pred_df[target_col].isna().any():
            return False, f"预测列包含 {pred_df[target_col].isna().sum()} 个空值"

        return True, None

    except Exception as e:
        return False, f"文件解析失败: {str(e)}"
