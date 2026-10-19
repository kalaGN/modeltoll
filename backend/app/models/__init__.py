"""Explicit mappings for all existing platform tables."""
from app.models.base import Base
from app.models.user import User
from app.models.user_session import UserSession
from app.models.login_throttle import LoginThrottle
from app.models.api_key import ApiKey
from app.models.pricing_rule import PricingRule
from app.models.api_call import ApiCall
from app.models.usage_charge import UsageCharge
from app.models.platform_setting import PlatformSetting
from app.models.model_connection import ModelConnection
from app.models.admin_audit_event import AdminAuditEvent
from app.models.request_rate_window import RequestRateWindow
from app.models.inference_success_receipt import InferenceSuccessReceipt
from app.models.request_idempotency import RequestIdempotency
