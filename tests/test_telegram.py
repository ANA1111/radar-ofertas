"""Offline regression checks; no Telegram messages and no paid API requests."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor import SCHEMA
from offer_workflow import message_for, valid_shopee_link
import web_panel


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = web_panel.DB
        web_panel.DB = Path(self.tmp.name) / "offers.sqlite3"
        with web_panel.db() as c:
            c.execute(
                "INSERT INTO candidates(source,product_id,title,url,price_cents,previous_cents,observed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                ("SHOPEE", "sku123", "Fone Bluetooth", "https://s.shopee.com.br/114DD7PTU0", 7990, 9990, "2026-11-04T12:00:00+00:00")
            )
            c.commit()

    def tearDown(self):
        web_panel.DB = self.old
        self.tmp.cleanup()

    def test_preview_accurate(self):
        with web_panel.db() as c:
            r = c.execute("SELECT * FROM candidates LIMIT 1").fetchone()
            text = message_for(r)
        self.assertIn("R$ 79,90", text)
        self.assertIn("R$ 99,90", text)
        self.assertIn("20%", text)

    def test_host_allowlist(self):
        self.assertTrue(valid_shopee_link("https://s.shopee.com.br/114DD7PTU0"))
        self.assertFalse(valid_shopee_link("https://shopee.com.br.evil.example/item"))
        self.assertFalse(valid_shopee_link("http://shopee.com.br/item"))

    def test_no_generation_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                web_panel.generate_link(1)

    def test_stored_affiliate_link_reused(self):
        with web_panel.db() as c:
            c.execute("INSERT INTO affiliate_links VALUES(?,?,?,?)",
                      (1, "telegram", "https://s.shopee.com.br/114DD7PTU0", "now"))
            c.commit()
        with patch("web_panel.connector_for", side_effect=AssertionError("API must not be called")):
            self.assertEqual(web_panel.generate_link(1), "https://s.shopee.com.br/114DD7PTU0")

    def test_no_send_when_not_approved(self):
        with patch.object(web_panel, "SEND", True), patch.object(web_panel, "TOKEN", "test-token"), patch.object(web_panel, "CHAT", "-1000000000"):
            with patch("web_panel.urllib.request.urlopen", side_effect=AssertionError("should not send")):
                web_panel.deliver(1)


if __name__ == "__main__":
    unittest.main()
