"""The shared builder changes neither payload fields nor serialization policy."""
import datetime
import unittest
from decimal import Decimal

from app.api.responses import success, utc_range
from app.core.time import iso_utc


class SuccessTests(unittest.TestCase):
    def test_empty_and_created_codes(self):
        self.assertEqual(success(), {'code': 'ok'})
        self.assertEqual(success(code='created', user={'id': 'fixture'}),
                         {'code': 'created', 'user': {'id': 'fixture'}})

    def test_flat_payload_preserves_values_and_does_not_mutate_input(self):
        payload = {'items': [], 'amount': Decimal('1.000000'), 'next_cursor': None}
        self.assertEqual(success(**payload), {'code': 'ok', **payload})
        self.assertNotIn('code', payload)
        self.assertIs(success(**payload)['items'], payload['items'])

    def test_existing_service_code_is_consumed_once(self):
        self.assertEqual(success(**{'code': 'ok', 'changed': False}),
                         {'code': 'ok', 'changed': False})

    def test_each_call_returns_its_own_dictionary(self):
        first = success()
        first['code'] = 'modified'
        self.assertEqual(success(), {'code': 'ok'})


class UtcRangeTests(unittest.TestCase):
    def test_range_preserves_legacy_year_width_and_second_precision(self):
        for year in (1, 999, 1000, 2026, 9999):
            with self.subTest(year=year):
                start = datetime.datetime(year, 1, 2, 3, 4, 5, 987654)
                end = datetime.datetime(year, 1, 3, 4, 5, 6, 123456)
                self.assertEqual(utc_range(start, end), {
                    'from': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'to': end.strftime('%Y-%m-%dT%H:%M:%SZ'), 'timezone': 'UTC',
                })

    def test_formatter_retains_clock_fields_and_does_not_add_a_second_conversion(self):
        # parse_range normalizes to UTC before this layer; legacy formatting never shifts clock fields.
        start = datetime.datetime(2026, 10, 19, 3, 4, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        self.assertEqual(utc_range(start, start)['from'], '2026-10-19T03:04:05Z')

    def test_existing_optional_timestamp_policy_is_unchanged(self):
        self.assertIsNone(iso_utc(None))
