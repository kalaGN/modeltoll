"""运维入口：python -m app.manage；口令不得作为命令行参数传入。"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import warnings

from app.core import config
from app.db import migrations
from app.services.access import bootstrap
from app.services.inference import recovery as inference_recovery


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse 默认回显未知参数；误传 --password 会因此泄露口令。
        self.print_usage(sys.stderr)
        self.exit(2, "参数无效，请使用 --help 查看用法；密码只允许交互或标准输入\n")


def _password_from_stdin() -> str:
    # 有限读取防止误传大文件；只删除一组结尾换行，不修改口令空格。
    password = sys.stdin.read(config.PASSWORD_MAX + 3)
    if password.endswith("\n"):
        password = password[:-1]
        if password.endswith("\r"):
            password = password[:-1]
    if "\n" in password or "\r" in password:
        raise bootstrap.BootstrapError("标准输入只允许一行密码")
    return password


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(description="Laya 平台数据库迁移与首个管理员初始化")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="执行已有幂等迁移；不会删除数据")
    admin = commands.add_parser("init-admin", help="创建首个管理员；必须先执行 migrate")
    admin.add_argument("--email", required=True, help="明确指定首个管理员邮箱")
    admin.add_argument("--password-stdin", action="store_true", help="显式从标准输入读取一行口令，默认交互输入")
    recovery = commands.add_parser("recover-calls", help="默认只读巡检；显式apply恢复可信成功回执的调用")
    recovery.add_argument("--call-id", help="定位单调用ID；apply必填")
    recovery.add_argument("--limit", type=int, default=100, help="巡检条数1–100，默认100")
    recovery.add_argument("--offset", type=int, default=0, help="只读巡检分页偏移0–1000000，默认0")
    recovery.add_argument("--apply", action="store_true", help="确认按原价格补账，可能对原HTTP500调用产生费用")
    args = parser.parse_args(argv)
    if args.command == "recover-calls" and (not 1 <= args.limit <= 100 or not 0 <= args.offset <= 1000000 or (args.apply and not args.call_id)):
        parser.error("恢复参数无效")
    try:
        if args.command == "migrate":
            migrations.init_db()
            print("数据库迁移完成")
        elif args.command == "recover-calls":
            if args.apply:
                amount = inference_recovery.recover(args.call_id)
                print(json.dumps({"call_id": args.call_id, "amount_yuan": str(amount)}, ensure_ascii=False))
            else:
                options = {"offset": args.offset} if args.offset else {}
                print(json.dumps(inference_recovery.inspect_calls(limit=args.limit, call_id=args.call_id, **options), ensure_ascii=False))
        else:
            if args.password_stdin:
                password = _password_from_stdin()
            else:
                if not sys.stdin.isatty():
                    raise bootstrap.BootstrapError("非交互终端请显式使用 --password-stdin")
                with warnings.catch_warnings():
                    # 即使终端控制失败，也不能让 getpass 回退到明文回显。
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    password = getpass.getpass("管理员密码: ")
                    if password != getpass.getpass("再次输入密码: "):
                        raise bootstrap.BootstrapError("两次密码不一致")
            result = bootstrap.init_admin(args.email, password)
            print("首个管理员已创建" if result.created else "该邮箱已是启用管理员，未作任何修改")
        return 0
    except bootstrap.BootstrapError as exc:
        print(str(exc), file=sys.stderr)
    except (KeyboardInterrupt, EOFError):
        print("操作已取消", file=sys.stderr)
    except Exception:
        # 数据库异常可能包含连接字符串/用户/密码，禁止输出 traceback。
        print("操作失败，请检查数据库配置与迁移状态；未确认完成", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
