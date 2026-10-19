"""可信成功回执与显式恢复的服务回归；仅合成数据。"""
import inspect
import unittest
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from app.db import session
from app.services import inference, inference_recovery, billing
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

    def execute(self, sql, args=()):
        if sql.startswith('SELECT') and 'FROM inference_success_receipts' in sql:
            self.result = deepcopy(self.receipt)
        elif sql.startswith('SELECT') and 'FROM pricing_rules' in sql:
            self.result = deepcopy(self.pricing)
        elif sql.startswith('INSERT INTO inference_success_receipts'):
            if self.fail_receipt:
                raise RuntimeError('synthetic receipt fault')
            self.writes.append(sql)
            self.receipt = dict(input_tokens=args[1], output_tokens=args[2], truncated=args[3],
                                state_tokens_dropped=args[4], completed_at=datetime(2026, 10, 10),
                                duration_ms=args[5])
        else:
            super().execute(sql, args)
            if sql.startswith('UPDATE') and "status = 'succeeded'" in sql:
                self.row.update(duration_ms=args[1], completed_at=args[7] if len(args) == 9 else None)
