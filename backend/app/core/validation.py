"""Pure input rules shared by HTTP contracts and account operations."""
import re

from app.core import config

_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    # 仅去首尾空白并转小写；不合并点号、加号或重音别名。
    return email.strip().lower()


def valid_email_shape(email: str) -> bool:
    return bool(email) and len(email) <= config.EMAIL_MAX and bool(_EMAIL_SHAPE.match(email))
