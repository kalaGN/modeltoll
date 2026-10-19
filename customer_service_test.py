#!/usr/bin/env python3
"""使用本地 Laya 模型对中文客服消息进行分类和分流的命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "backend"))

from app.services.inference import customer_service  # noqa: E402  (需先加入 backend 到导入路径)


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


def print_summary(report: dict) -> None:
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
        report = customer_service.analyse(message, args.device)
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
