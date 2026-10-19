"""Model metadata and dialect compilation without opening a database connection."""
import unittest

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.models import Base, User, ApiKey, ApiCall, UsageCharge, InferenceSuccessReceipt


class ModelMetadataTests(unittest.TestCase):
    def test_all_existing_tables_have_explicit_models(self):
        self.assertEqual(set(Base.metadata.tables), {
            'users', 'user_sessions', 'login_throttle', 'api_keys', 'pricing_rules',
            'api_calls', 'usage_charges', 'platform_settings', 'model_connection',
            'admin_audit_events', 'request_rate_windows', 'inference_success_receipts',
            'request_idempotency',
        })
        for table in Base.metadata.sorted_tables:
            with self.subTest(table=table.name):
                sql = str(CreateTable(table).compile(dialect=mysql.dialect()))
                self.assertIn('CREATE TABLE', sql)
                self.assertIn('InnoDB', sql)

    def test_precision_and_sensitive_collations_are_preserved(self):
        self.assertEqual(User.__table__.c.email_normalized.type.collation, 'utf8mb4_0900_as_cs')
        self.assertEqual(ApiKey.__table__.c.id.type.collation, 'ascii_bin')
        self.assertEqual(ApiCall.__table__.c.started_at.type.fsp, 3)
        amount = UsageCharge.__table__.c.amount_yuan.type
        self.assertEqual((amount.precision, amount.scale, amount.asdecimal), (20, 6, True))
        self.assertTrue(InferenceSuccessReceipt.__table__.c.input_tokens.type.unsigned)
        self.assertIsInstance(InferenceSuccessReceipt.__table__.c.truncated.type, mysql.TINYINT)

    def test_additive_columns_and_compound_ownership_are_mapped(self):
        self.assertIn('is_admin', User.__table__.c)
        self.assertIn('deleted_at', ApiKey.__table__.c)
        ownership = next(c for c in ApiCall.__table__.foreign_key_constraints if c.name == 'fk_calls_key_user')
        self.assertEqual(list(ownership.column_keys), ['api_key_id', 'user_id'])
        self.assertEqual([column.name for column in Base.metadata.tables['request_idempotency'].primary_key],
                         ['user_id', 'key_hash'])
