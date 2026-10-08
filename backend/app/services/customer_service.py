"""中文客服消息的分类与人工分流业务规则。阈值属业务策略，不随模型结果改动。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.core import config

if TYPE_CHECKING:
    from laya import Router

INTENT_NAMES = {
    "refund": "退款/重复扣款",
    "technical_help": "技术问题",
    "billing_question": "账单/支付咨询",
    "information": "产品信息/使用咨询",
    "cancellation": "取消/降级服务",
    "other": "其他问题",
}

ACTION_NAMES = {
    "refund": "转交账务人员核查并处理退款",
    "technical_help": "转交技术支持",
    "billing_question": "转交账单与支付支持",
    "information": "由客服直接答复产品信息",
    "cancellation": "转交客户挽留或取消服务流程",
    "other": "补充询问客户的具体诉求",
}


def probability(answer: dict[str, Any], key: str) -> float:
    return float(answer.get("probabilities", {}).get(key, 0.0))


def analyse(
    message: str, device: str = "mps", router: Router | None = None
) -> dict[str, Any]:
    payload, _usage = analyse_with_usage(message, device=device, router=router)
    return payload


def analyse_with_usage(
    message: str, device: str = "mps", router: Router | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """客服分析同时返回原生 usage：接口响应保持原样，但计量必须能拿到用量。"""
    config.configure_model_cache()
    from laya.presets import triage_questions
    if router is None:
        from laya import Router
        router = Router(device=device, default="multilingual")
    result = router.predict(
        {"message": message},
        triage_questions(),
        model="multilingual",
        lang="zh",
    )
    answers = result["answers"]

    intent = answers["intent"]["choice"]
    intent_probability = probability(answers["intent"], intent)
    urgent_probability = float(answers["is_urgent"]["noul"])
    frustration = float(answers["frustration"]["score"])
    refund_probability = float(answers["refund_requested"]["noul"])
    churn_probability = float(answers["churn_risk"]["noul"])

    # 这里的人工分流规则是业务规则，不是模型直接生成的结论。
    needs_human = (
        urgent_probability >= 0.5
        or frustration >= 2.0
        or churn_probability >= 0.5
        or intent in {"refund", "cancellation"}
    )
    priority = (
        "高"
        if (
            urgent_probability >= 0.5
            or frustration >= 2.5
            or churn_probability >= 0.75
        )
        else "中"
        if frustration >= 1.5 or churn_probability >= 0.5
        else "低"
    )

    payload = {
        "message": message,
        "category": intent,
        "category_name": INTENT_NAMES.get(intent, intent),
        "category_probability": round(intent_probability, 4),
        "recommended_action": ACTION_NAMES.get(intent, ACTION_NAMES["other"]),
        "priority": priority,
        "needs_human": needs_human,
        "signals": {
            "urgent_probability": round(urgent_probability, 4),
            "frustration_score_0_to_3": round(frustration, 4),
            "refund_probability": round(refund_probability, 4),
            "churn_probability": round(churn_probability, 4),
        },
        "model": result.get("routing", {}).get("model", "multilingual"),
    }
    return payload, result.get("usage", {})
