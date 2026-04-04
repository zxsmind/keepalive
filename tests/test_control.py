import os
import tempfile
import unittest
from unittest.mock import patch

from keepalive_service.config import AppConfig
from keepalive_service.control import IdleStateMachine, TargetPlanner
from keepalive_service.models import ResourceSample, Snapshot


def build_snapshot(cpu: float, memory: float, disk: float, network: float) -> Snapshot:
    def sample(real: float) -> ResourceSample:
        return ResourceSample(total_percent=real, synthetic_percent=0.0, real_percent=real)

    return Snapshot(
        cpu=sample(cpu),
        memory=sample(memory),
        disk=sample(disk),
        network=sample(network),
    )


class ControlTests(unittest.TestCase):
    def test_service_pauses_when_real_activity_appears(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"WORK_DIR": directory}, clear=True):
                config = AppConfig.from_env()

        machine = IdleStateMachine(config)
        state = machine.evaluate(build_snapshot(cpu=13.0, memory=0.0, disk=0.0, network=0.0))
        self.assertTrue(state.paused)
        self.assertEqual(state.pause_reason, "cpu")

    def test_service_resumes_after_hysteresis(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"WORK_DIR": directory, "IDLE_RESUME_CYCLES": "2"}, clear=True):
                config = AppConfig.from_env()

        machine = IdleStateMachine(config)
        machine.evaluate(build_snapshot(cpu=13.0, memory=0.0, disk=0.0, network=0.0))
        state = machine.evaluate(build_snapshot(cpu=1.0, memory=1.0, disk=1.0, network=1.0))
        self.assertTrue(state.paused)
        state = machine.evaluate(build_snapshot(cpu=1.0, memory=1.0, disk=1.0, network=1.0))
        self.assertFalse(state.paused)

    def test_memory_alone_does_not_pause_service(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"WORK_DIR": directory}, clear=True):
                config = AppConfig.from_env()

        machine = IdleStateMachine(config)
        state = machine.evaluate(build_snapshot(cpu=0.0, memory=70.0, disk=0.0, network=0.0))
        self.assertFalse(state.paused)

    def test_planner_tops_up_to_targets_when_active(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "WORK_DIR": directory,
                    "MEMORY_ENABLED": "true",
                    "MEMORY_TARGET_PERCENT": "23",
                    "DISK_ENABLED": "true",
                    "DISK_TARGET_PERCENT": "23",
                    "NETWORK_ENABLED": "true",
                    "NETWORK_TARGET_PERCENT": "23",
                },
                clear=True,
            ):
                config = AppConfig.from_env()

        planner = TargetPlanner(config)
        state = IdleStateMachine(config).state
        plan = planner.build(build_snapshot(cpu=4.0, memory=8.0, disk=2.0, network=3.0), state)
        self.assertEqual(plan.cpu_percent, 19.0)
        self.assertEqual(plan.memory_percent, 15.0)
        self.assertEqual(plan.disk_percent, 21.0)
        self.assertEqual(plan.network_percent, 20.0)

    def test_defaults_are_cpu_first(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"WORK_DIR": directory}, clear=True):
                config = AppConfig.from_env()

        planner = TargetPlanner(config)
        state = IdleStateMachine(config).state
        plan = planner.build(build_snapshot(cpu=4.0, memory=8.0, disk=2.0, network=3.0), state)
        self.assertEqual(plan.cpu_percent, 19.0)
        self.assertEqual(plan.memory_percent, 0.0)
        self.assertEqual(plan.disk_percent, 0.0)
        self.assertEqual(plan.network_percent, 0.0)


if __name__ == "__main__":
    unittest.main()
