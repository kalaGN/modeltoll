"""客服后处理失败仍能携带已知用量；只使用合成模型响应。"""

import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from app.services import customer_service


class CustomerServiceUsageTests(unittest.TestCase):
    def run_analysis(self, router):
        presets = ModuleType('laya.presets')
        presets.triage_questions = lambda: {}
        with patch.dict(sys.modules, {'laya.presets': presets}), patch.object(
            customer_service.config, 'configure_model_cache'
        ):
            return customer_service.analyse_with_usage('合成客户文本', router=router)

    def test_postprocessing_failure_carries_only_usage_metadata(self):
        router = Mock()
        router.predict.return_value = {
            'answers': {},
            'usage': {'input_tokens': 17, 'output_tokens': 0, 'private': '不要持久化'},
        }
        try:
            self.run_analysis(router)
        except Exception as exc:
            self.assertEqual(type(exc).__name__, 'AnalysisPostprocessingError')
            self.assertEqual(exc.usage, {'input_tokens': 17, 'output_tokens': 0})
            self.assertNotIn('合成客户文本', str(exc))
            self.assertNotIn('不要持久化', str(exc))
        else:
            self.fail('Malformed answers must fail')

    def test_predict_failure_is_not_postprocessing_failure(self):
        router = Mock()
        failure = RuntimeError('synthetic upstream failure')
        router.predict.side_effect = failure
        with self.assertRaises(RuntimeError) as caught:
            self.run_analysis(router)
        self.assertIs(caught.exception, failure)

    def test_valid_response_keeps_business_rules_and_usage(self):
        router = Mock()
        usage = {'input_tokens': 12, 'output_tokens': 0}
        router.predict.return_value = {
            'answers': {
                'intent': {'choice': 'refund', 'probabilities': {'refund': 0.8}},
                'is_urgent': {'noul': 0.1}, 'frustration': {'score': 1.6},
                'refund_requested': {'noul': 0.9}, 'churn_risk': {'noul': 0.2},
            }, 'usage': usage,
        }
        payload, actual_usage = self.run_analysis(router)
        self.assertEqual(actual_usage, usage)
        self.assertEqual(payload['category'], 'refund')
        self.assertEqual(payload['priority'], '中')
        self.assertTrue(payload['needs_human'])
        self.assertEqual(payload['message'], '合成客户文本')
