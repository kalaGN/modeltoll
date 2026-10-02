#!/usr/bin/env python3
"""使用本地 Laya 模型对中文客服消息进行分类和分流。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(PROJECT_DIR / ".hf-cache"))

from laya import Router  # noqa: E402  (HF_HOME 必须先设置)
from laya.presets import triage_questions  # noqa: E402


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用本地 Laya multilingual 模型分析中文客服消息。"
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="客户消息；不传时从标准输入读取",
    )
    parser.add_argument(
        "--device",
        choices=("mps", "cpu"),
        default="mps",
        help="推理设备（默认：mps，适合 Apple Silicon）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出便于程序读取的 JSON",
    )
    return parser.parse_args()


def read_message(parts: list[str]) -> str:
    if parts:
        return " ".join(parts).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return input("请输入客户消息：").strip()


def probability(answer: dict[str, Any], key: str) -> float:
    return float(answer.get("probabilities", {}).get(key, 0.0))


def analyse(
    message: str, device: str = "mps", router: Router | None = None
) -> dict[str, Any]:
    if router is None:
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

    return {
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


def print_summary(report: dict[str, Any]) -> None:
    print(f"客户消息：{report['message']}")
    print(
        f"问题分类：{report['category_name']} "
        f"(置信概率 {report['category_probability']:.1%})"
    )
    print(f"处理优先级：{report['priority']}")
    print(f"需要人工：{'是' if report['needs_human'] else '否'}")
    print(f"建议动作：{report['recommended_action']}")
    print("风险信号：")
    print(f"  紧急概率：{report['signals']['urgent_probability']:.1%}")
    print(f"  不满程度：{report['signals']['frustration_score_0_to_3']:.2f}/3")
    print(f"  退款概率：{report['signals']['refund_probability']:.1%}")
    print(f"  流失概率：{report['signals']['churn_probability']:.1%}")


def main() -> int:
    args = parse_args()
    message = read_message(args.message)
    if not message:
        print("错误：客户消息不能为空。", file=sys.stderr)
        return 2

    try:
        report = analyse(message, args.device)
    except Exception as exc:
        print(f"分析失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
