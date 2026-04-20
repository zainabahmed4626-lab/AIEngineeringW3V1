"""Tests for heuristic router classification (no Gemini required)."""

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from src.agents.router_agent import classify_intent_fallback  # noqa: E402


class TestRouterFallback(unittest.TestCase):
    def test_returns_keywords(self) -> None:
        d = classify_intent_fallback("I need a return label for order 9")
        self.assertEqual(d.route, "returns")
        self.assertFalse(d.escalate)

    def test_billing_keywords(self) -> None:
        d = classify_intent_fallback("Duplicate charge on my Visa")
        self.assertEqual(d.route, "billing")

    def test_escalate_legal(self) -> None:
        d = classify_intent_fallback("I will contact my lawyer tomorrow")
        self.assertTrue(d.escalate)
        self.assertEqual(d.route, "support")

    def test_generic_support(self) -> None:
        d = classify_intent_fallback("The notifications tab freezes")
        self.assertEqual(d.route, "support")
        self.assertFalse(d.escalate)


if __name__ == "__main__":
    unittest.main()
