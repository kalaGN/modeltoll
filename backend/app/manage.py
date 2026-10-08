"""运维入口：python -m app.manage；口令不得作为命令行参数传入。"""

from __future__ import annotations

import argparse
import getpass
import sys
import warnings

from app.core import config
from app.db import models
from app.services import bootstrap


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
    args = parser.parse_args(argv)
    try:
        if args.command == "migrate":
            models.init_db()
            print("数据库迁移完成")
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
