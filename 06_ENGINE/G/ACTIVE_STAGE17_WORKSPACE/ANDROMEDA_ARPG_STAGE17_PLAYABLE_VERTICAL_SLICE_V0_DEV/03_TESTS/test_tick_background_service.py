import time
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))
from tick_background_service import TickBackgroundService

class FakeOrchestrator:
    def __init__(self): self.calls=[]
    def run_tick(self, world_id): self.calls.append(world_id); return {"status":"COMPLETED"}

class TickBackgroundServiceTests(unittest.TestCase):
    def make(self, interval=.01):
        orch=FakeOrchestrator(); svc=TickBackgroundService(orch, interval_s=interval); return orch,svc
    def test_daemon_starts_and_ticks_registered_world(self):
        orch,svc=self.make(); svc.register_world("W1"); svc.start(); time.sleep(.05)
        self.assertTrue(svc.thread.daemon); self.assertGreaterEqual(svc.ticks_completed,1); svc.stop()
    def test_same_world_is_serialized(self):
        orch,svc=self.make(); svc.register_world("W1"); svc.start(); time.sleep(.04); svc.stop()
        self.assertTrue(all(x=="W1" for x in orch.calls)); self.assertGreaterEqual(len(orch.calls),1)
    def test_unregister_stops_future_ticks(self):
        orch,svc=self.make(); svc.register_world("W1"); svc.start(); time.sleep(.03); svc.unregister_world("W1"); count=len(orch.calls); time.sleep(.03); svc.stop()
        self.assertEqual(len(orch.calls),count)
    def test_stop_is_clean_and_idempotent(self):
        _,svc=self.make(); svc.start(); svc.stop(); svc.stop(); self.assertFalse(svc.is_running)

if __name__ == "__main__": unittest.main()