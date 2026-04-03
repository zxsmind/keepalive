import unittest

from keepalive_service.status import format_status


class StatusTests(unittest.TestCase):
    def test_status_output_contains_started_runtime_and_resource_breakdown(self):
        payload = {
            "started_at": 1_700_000_000,
            "timestamp": 1_700_000_120,
            "paused": False,
            "reason": None,
            "targets": {
                "cpu": 20.0,
                "memory": 20.0,
                "disk": 20.0,
                "network": 20.0,
            },
            "cpu": {"total_percent": 18.0, "real_percent": 2.0, "synthetic_percent": 16.0},
            "memory": {"total_percent": 30.0, "real_percent": 14.0, "synthetic_percent": 16.0},
            "disk": {"total_percent": 21.0, "real_percent": 1.0, "synthetic_percent": 20.0},
            "network": {"total_percent": 10.0, "real_percent": 2.0, "synthetic_percent": 8.0},
        }

        output = format_status(payload, max_age_seconds=300, now=1_700_000_180)

        self.assertIn("KeepAlive Status", output)
        self.assertIn("Load Score : 15.0% synthetic", output)
        self.assertIn("CPU      total= 18.0%  real=  2.0%  keepalive= 16.0%  target= 20.0%", output)
        self.assertIn("Heartbeat  :", output)


if __name__ == "__main__":
    unittest.main()
