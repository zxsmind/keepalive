import os
import tempfile
import unittest
from unittest.mock import patch

from keepalive_service.cli import _config_payload
from keepalive_service.config import AppConfig, ConfigError


class ConfigTests(unittest.TestCase):
    def test_defaults_load(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"WORK_DIR": directory}, clear=True):
                config = AppConfig.from_env()
        self.assertEqual(config.cpu.target_percent, 23.0)
        self.assertTrue(config.cpu.enabled)
        self.assertFalse(config.memory.enabled)
        self.assertFalse(config.disk.enabled)
        self.assertFalse(config.network.enabled)

    def test_invalid_pause_resume_pair_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "WORK_DIR": directory,
                    "IDLE_PAUSE_PERCENT": "2",
                    "IDLE_RESUME_PERCENT": "5",
                },
                clear=True,
            ):
                with self.assertRaises(ConfigError):
                    AppConfig.from_env()

    def test_normalized_config_payload_contains_memory_safety_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"WORK_DIR": directory}, clear=True):
                config = AppConfig.from_env()
        payload = _config_payload(config)
        self.assertIn("memory_max_reserve_of_available_percent", payload)
        self.assertFalse(payload["memory_enabled"])


if __name__ == "__main__":
    unittest.main()
