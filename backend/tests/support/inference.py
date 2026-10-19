"""Synthetic SQLAlchemy result store; not evidence of real MySQL locks."""
from copy import deepcopy
from datetime import datetime
from sqlalchemy.dialects import mysql
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select


class Cursor:
    def __init__(self, status='running'):
        self.row = dict(status=status, http_status=None, error_code=None,
                        input_tokens=None, output_tokens=None, truncated=None,
                        state_tokens_dropped=None, billing_status='pending',
                        billing_reason=None, pricing_rule_id='rule', completed_at=None, duration_ms=None)
        self.charge = None
        self.receipt = None
        self.writes = []
        self.rowcount = 1
        self.result = None

    def execute(self, statement, args=()):
        compiled = statement.compile(dialect=mysql.dialect())
        sql, values = str(compiled), compiled.params
        if isinstance(statement, Select):
            table = statement.get_final_froms()[0].name
            self.result = deepcopy({'inference_success_receipts': self.receipt,
                                    'usage_charges': self.charge,
                                    'pricing_rules': getattr(self, 'pricing', None),
                                    'api_calls': self.row}[table])
        elif isinstance(statement, Insert) and statement.table.name == 'inference_success_receipts':
            if getattr(self, 'fail_receipt', False):
                raise RuntimeError('synthetic receipt fault')
            self.writes.append(sql)
            self.receipt = {key: values[key] for key in ('input_tokens', 'output_tokens',
                'truncated', 'state_tokens_dropped', 'duration_ms')}
            self.receipt['completed_at'] = datetime(2026, 10, 10)
        elif isinstance(statement, Update):
            self.writes.append(sql)
            updates = {}
            for column, value in statement._values.items():
                name = getattr(column, 'key', column)
                updates[name] = getattr(value, 'value', datetime(2026, 10, 10))
            if updates.get('status') == 'running':
                self.rowcount = int(self.row is not None and self.row['status'] == 'accepted')
            if self.row is not None and self.rowcount:
                self.row.update(updates)
        else:
            raise AssertionError(sql)
        return self

    def mappings(self):
        return self

    def first(self):
        return self.result

    def fetchone(self):
        return self.result
