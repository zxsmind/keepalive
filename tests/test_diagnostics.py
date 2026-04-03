import os
import tempfile
import unittest
from unittest.mock import patch

from keepalive_service.config import AppConfig
from keepalive_service.diagnostics import RuntimeDoctor


class RuntimeDoctorTests(unittest.TestCase):
    def test_reports_warning_when_cpu_cores_exceed_visible_count(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "WORK_DIR": directory,
                    "CPU_CORES": "999",
                },
                clear=True,
            ):
                config = AppConfig.from_env()

        with patch("keepalive_service.diagnostics.platform.system", return_value="Linux"):
            with patch("keepalive_service.diagnostics.shutil.which", return_value="/usr/bin/stress-ng"):
                report = RuntimeDoctor(config).inspect()

        self.assertTrue(report.warnings)


if __name__ == "__main__":
    unittest.main()
