"""平台品牌、Logo 校验与配置持久化。"""
from __future__ import annotations

import base64
import binascii
import io
import warnings

from PIL import Image, UnidentifiedImageError

from app.core.time import iso_utc
from app.db import session
from app.repositories import settings

MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 4096 * 4096
DEFAULT_BRANDING = {"name": "Laya", "description": "模型 API 平台", "logo_url": ""}


class InvalidLogo(ValueError):
    pass


def validate_logo(data_url: str) -> bytes:
    if len(data_url) > 4 * ((MAX_LOGO_BYTES + 2) // 3) + 64:
        raise InvalidLogo("Logo 不能超过 2 MB")
    try:
        header, encoded = data_url.split(",", 1)
        mime = header.removeprefix("data:").removesuffix(";base64")
        formats = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
        if header != f"data:{mime};base64" or mime not in formats:
            raise InvalidLogo("仅支持 PNG、JPEG、WebP 图片")
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > MAX_LOGO_BYTES:
            raise InvalidLogo("Logo 不能为空且不能超过 2 MB")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != formats[mime]:
                    raise InvalidLogo("图片格式与声明类型不符")
                if image.width > 4096 or image.height > 4096 or image.width * image.height > MAX_PIXELS:
                    raise InvalidLogo("图片尺寸不能超过 4096 × 4096")
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                # 品牌图最多 512px；重新编码为 PNG，丢弃元数据和附加内容。
                image = image.convert("RGBA")
                image.thumbnail((512, 512))
                clean = Image.frombytes("RGBA", image.size, image.tobytes())
                output = io.BytesIO()
                clean.save(output, format="PNG")
                result = output.getvalue()
                if len(result) > MAX_LOGO_BYTES:
                    raise InvalidLogo("处理后的 Logo 超过 2 MB，请使用较小图片")
                return result
    except InvalidLogo:
        raise
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidLogo("Logo 图片无效或已损坏") from None


def _public(row: dict) -> dict:
    return {
        "name": row["name"], "description": row["description"],
        "logo_url": f"/v1/platform/logo?v={iso_utc(row['updated_at'])}" if row["has_logo"] else "",
    }


def branding() -> dict:
    with session.read_session() as db:
        row = settings.branding(db)
    return _public(row) if row else dict(DEFAULT_BRANDING)


def logo() -> bytes | None:
    with session.read_session() as db:
        return settings.logo(db)


def save_settings(name: str, description: str, logo_data_url: str | None) -> dict:
    image = validate_logo(logo_data_url) if logo_data_url else None
    with session.unit_of_work() as db:
        settings.save_branding(db, name, description, image, keep_logo=logo_data_url is None)
        row = settings.branding(db)
        if row is None:
            raise RuntimeError("平台配置记录缺失，请执行迁移")
        return _public(row)
