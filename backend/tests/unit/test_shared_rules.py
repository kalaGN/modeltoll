"""Shared rules retain the original contract after being moved out of services."""
import datetime
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.core import config, validation
from app.core.time import iso_utc, utc_now
from app.schemas.auth import CredentialsRequest


class SharedRulesTests(unittest.TestCase):
    def test_utc_clock_preserves_naive_utc_and_microseconds(self):
        now = datetime.datetime(2026, 10, 19, 2, 3, 4, 567000, tzinfo=datetime.timezone.utc)
        with patch('app.core.time.datetime.datetime') as clock:
            clock.now.return_value = now
            self.assertEqual(utc_now(), now.replace(tzinfo=None))
            clock.now.assert_called_once_with(datetime.timezone.utc)

    def test_email_normalization_does_not_merge_aliases(self):
        self.assertEqual(validation.normalize_email('  First.Last+Tag@EXAMPLE.COM  '),
                         'first.last+tag@example.com')

    def test_email_shape_boundaries_are_unchanged(self):
        valid = 'a' * (config.EMAIL_MAX - len('@b.co')) + '@b.co'
        self.assertTrue(validation.valid_email_shape(valid))
        for value in ['', 'a@b', 'a b@c.co', 'a@@b.co', 'a' + valid]:
            with self.subTest(value=value):
                self.assertFalse(validation.valid_email_shape(value))

    def test_credentials_still_normalize_and_reject_bad_email(self):
        body = CredentialsRequest(email='  TEST@EXAMPLE.COM  ', password='x' * config.PASSWORD_MIN)
        self.assertEqual(body.email, 'test@example.com')
        with self.assertRaises(ValidationError):
            CredentialsRequest(email='not-an-email', password='x' * config.PASSWORD_MIN)

    def test_utc_serialization_preserves_none_and_second_precision(self):
        self.assertIsNone(iso_utc(None))
        self.assertEqual(iso_utc(datetime.datetime(2026, 10, 18, 1, 2, 3, 456000)),
                         '2026-10-18T01:02:03Z')
