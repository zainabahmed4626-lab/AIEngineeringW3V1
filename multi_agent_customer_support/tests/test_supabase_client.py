"""Unit tests for mcp.supabase_client (mocked Supabase)."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Resolve `mcp` from src/ when tests are run without editable install.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Import via the `src` package (`src.mcp`) so we do not clash with PyPI `mcp` SDK.
sys.path.insert(0, _ROOT)

from src.mcp import supabase_client as sc  # noqa: E402


class TestSupabaseClient(unittest.TestCase):
    def setUp(self) -> None:
        sc.reset_supabase_client_cache()

    def tearDown(self) -> None:
        sc.reset_supabase_client_cache()

    def test_get_customer_by_email_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            sc.get_customer_by_email("  ")

    @patch.object(sc, "get_supabase_client")
    def test_get_customer_by_email_found(self, mock_get: MagicMock) -> None:
        row = {"id": "1", "email": "a@b.com", "name": "A"}
        chain = MagicMock()
        mock_get.return_value.table.return_value = chain
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            SimpleNamespace(data=[row])
        )

        out = sc.get_customer_by_email("a@b.com")
        self.assertEqual(out, row)
        chain.select.assert_called_with("*")
        chain.select.return_value.eq.assert_called_with("email", "a@b.com")

    @patch.object(sc, "get_supabase_client")
    def test_get_customer_by_email_not_found(self, mock_get: MagicMock) -> None:
        chain = MagicMock()
        mock_get.return_value.table.return_value = chain
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            SimpleNamespace(data=[])
        )
        self.assertIsNone(sc.get_customer_by_email("x@y.com"))

    @patch.object(sc, "get_supabase_client")
    def test_get_customer_by_id_found(self, mock_get: MagicMock) -> None:
        row = {"id": "uuid-1", "email": "a@b.com", "name": "A"}
        chain = MagicMock()
        mock_get.return_value.table.return_value = chain
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            SimpleNamespace(data=[row])
        )

        out = sc.get_customer_by_id("uuid-1")
        self.assertEqual(out, row)
        chain.select.return_value.eq.assert_called_with("id", "uuid-1")

    def test_get_customer_by_id_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            sc.get_customer_by_id("  ")

    @patch.object(sc, "get_supabase_client")
    def test_get_orders_by_customer(self, mock_get: MagicMock) -> None:
        rows = [{"id": "o1", "customer_id": "c1"}]
        chain = MagicMock()
        mock_get.return_value.table.return_value = chain
        chain.select.return_value.eq.return_value.order.return_value.execute.return_value = (
            SimpleNamespace(data=rows)
        )

        out = sc.get_orders_by_customer("c1")
        self.assertEqual(out, rows)
        chain.select.return_value.eq.assert_called_with("customer_id", "c1")
        chain.select.return_value.eq.return_value.order.assert_called()

    @patch.object(sc, "get_supabase_client")
    def test_get_support_tickets_by_category(self, mock_get: MagicMock) -> None:
        rows = [{"id": "t1", "category": "billing"}]
        chain = MagicMock()
        mock_get.return_value.table.return_value = chain
        chain.select.return_value.eq.return_value.order.return_value.execute.return_value = (
            SimpleNamespace(data=rows)
        )

        out = sc.get_support_tickets_by_category("billing")
        self.assertEqual(out, rows)
        chain.select.return_value.eq.assert_called_with("category", "billing")

    @patch.dict(
        os.environ,
        {"SUPABASE_URL": "", "SUPABASE_ANON_KEY": "", "SUPABASE_KEY": ""},
        clear=False,
    )
    def test_configuration_error_missing_env(self) -> None:
        sc.reset_supabase_client_cache()
        with self.assertRaises(sc.SupabaseConfigurationError):
            sc.get_supabase_client()


if __name__ == "__main__":
    unittest.main()
