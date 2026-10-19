"""Executable module boundaries; no database, network, or model startup."""
import ast
import unittest

from tests.support.paths import ROOT

APP = ROOT / 'backend' / 'app'


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            yield module
            yield from (module + '.' + alias.name for alias in node.names)


class ArchitectureTests(unittest.TestCase):
    def assert_no_imports(self, folder, prefixes):
        for path in (APP / folder).rglob('*.py'):
            with self.subTest(path=str(path.relative_to(APP))):
                forbidden = [name for name in imports(path)
                             if any(name == p or name.startswith(p + '.') for p in prefixes)]
                self.assertEqual(forbidden, [])

    def test_routes_do_not_import_other_routes(self):
        self.assert_no_imports('api/v1', ('app.api.v1',))

    def test_schemas_do_not_depend_on_services_or_database(self):
        self.assert_no_imports('schemas', ('app.services', 'app.db', 'app.api'))

    def test_services_do_not_depend_on_http_or_composition(self):
        self.assert_no_imports('services', ('app.api', 'app.main', 'fastapi', 'starlette'))

    def test_upstream_adapter_is_separate_from_business_and_database(self):
        self.assertTrue((APP / 'integrations/openai_client.py').is_file())
        self.assert_no_imports('integrations', ('app.services', 'app.db', 'app.api', 'app.main'))
        self.assertNotIn('httpx', set(imports(APP / 'services/gateway.py')))

    def test_migration_executor_is_not_named_models(self):
        self.assertTrue((APP / 'db/migrations.py').is_file())
        self.assertFalse((APP / 'db/models.py').exists())

    def test_settings_contract_is_in_schemas(self):
        self.assertTrue((APP / 'schemas/platform.py').is_file())
        tree = ast.parse((APP / 'api/v1/admin.py').read_text())
        self.assertFalse(any(isinstance(n, ast.ClassDef) and n.name == 'SettingsRequest'
                             for n in ast.walk(tree)))

    def test_recovery_does_not_call_private_inference_functions(self):
        tree = ast.parse((APP / 'services/inference_recovery.py').read_text())
        private = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                   and isinstance(node.value, ast.Name) and node.value.id == 'inference'
                   and node.attr.startswith('_')]
        self.assertEqual(private, [])

    def test_branding_and_admin_overview_have_separate_owners(self):
        branding = ast.parse((APP / 'services/branding.py').read_text())
        self.assertNotIn('overview', [n.name for n in branding.body if isinstance(n, ast.FunctionDef)])
        self.assertTrue((APP / 'services/admin_overview.py').is_file())
        from app.api.v1 import admin, platform
        self.assertTrue(all(route.path.startswith('/v1/admin/') for route in admin.router.routes))
        self.assertTrue(all(route.path.startswith('/v1/platform/') for route in platform.router.routes))
