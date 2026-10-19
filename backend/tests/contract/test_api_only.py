"""The API is deployable without frontend source or build artifacts."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core import config
from app.services.access import accounts


class ApiOnlyTests(unittest.TestCase):
    def test_business_pages_and_assets_are_not_backend_routes(self):
        client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(client.close)
        with patch.object(accounts, "current_user") as current:
            for route in ["/", "/login", "/register", "/keys", "/usage", "/billing", "/admin", "/admin/settings", "/admin/users", "/assets/app.css"]:
                with self.subTest(route=route):
                    self.assertEqual(client.get(route, follow_redirects=False).status_code, 404)
            current.assert_not_called()

    def test_no_frontend_filesystem_setting(self):
        self.assertFalse(hasattr(config, "FRONTEND_DIST"))
