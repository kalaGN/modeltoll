"""可信成功回执与显式恢复的服务回归；仅合成数据。"""
import inspect
import unittest
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from app.db import session
from app.services.inference import lifecycle as inference, recovery as inference_recovery
from app.services.metering import billing
from tests.support.inference import Cursor


class RecoveryInterfaceTests(unittest.TestCase):
    def test_receipt_capture_is_explicit(self):
        self.assertTrue(callable(getattr(inference, 'capture_success', None)))

    def test_admission_supports_optional_idempotency(self):
        self.assertIn('idempotency', inspect.signature(inference.begin).parameters)


class ReceiptCursor(Cursor):
    def __init__(self):
        super().__init__()
        self.row.update(id='call', user_id='user', api_key_id='key', endpoint='/predict',
                        model='model', completed_at=None, duration_ms=None)
        self.receipt = None
        self.fail_receipt = False
        self.pricing = dict(id='rule', version='v1', model='model', currency='CNY',
                            token_basis='input', unit_tokens=1000000,
                            unit_price_yuan=Decimal('1'), billing_policy_version='succeeded_only_v1')
