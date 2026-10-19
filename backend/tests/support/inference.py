"""Shared synthetic inference cursor; no database connections."""
from copy import deepcopy


class Cursor:
    def __init__(self, status='running'):
        self.row = dict(status=status, http_status=None, error_code=None,
                        input_tokens=None, output_tokens=None, truncated=None,
                        state_tokens_dropped=None, billing_status='pending',
                        billing_reason=None, pricing_rule_id='rule')
        self.charge = None
        self.writes = []
        self.rowcount = 1
        self.result = None

    def execute(self, sql, args=()):
        if sql.startswith('SELECT'):
            if 'FROM inference_success_receipts' in sql:
                self.result = None
            else:
                self.result = deepcopy(self.charge if 'FROM usage_charges' in sql else self.row)
            return
        self.writes.append(sql)
        if "status = 'running'" in sql:
            self.rowcount = int(self.row is not None and self.row['status'] == 'accepted')
            if self.rowcount:
                self.row['status'] = 'running'
        elif "status = 'succeeded'" in sql:
            self.row.update(status='succeeded', http_status=args[0], input_tokens=args[2],
                            output_tokens=args[3], truncated=args[4], state_tokens_dropped=args[5],
                            billing_status='charged', billing_reason=args[6])
        elif "status = 'failed'" in sql:
            self.row.update(status='failed', http_status=args[0], error_code=args[1],
                            billing_status=args[3], billing_reason=args[4])
        elif "status = 'interrupted'" in sql:
            self.row.update(status='interrupted', http_status=args[0], error_code=args[1],
                            billing_status='not_billable', billing_reason=args[3])
        elif 'SET input_tokens' in sql:
            self.row.update(input_tokens=args[0], output_tokens=args[1],
                            truncated=args[2], state_tokens_dropped=args[3])

    def fetchone(self):
        return self.result
