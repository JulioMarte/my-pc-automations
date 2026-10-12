"""Pruebas que impiden convertir supuestos en aprobaciones."""
import unittest
from operational_validation import VEHICLES, cycle_minutes, report_from_valhalla


class OperationalValidationTests(unittest.TestCase):
    def test_cycle_decomposition(self):
        value = cycle_minutes(3600, 12, 30, 6, 12, 12)
        self.assertEqual(value["cycle_minutes"], 96.0)
        self.assertEqual(value["components_minutes"]["stop_dwell_minutes"], 6.0)
        self.assertEqual(value["calibration"], "EXPLORATORIO_NO_MEDIDO")

    def test_bad_inputs(self):
        for bad in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                cycle_minutes(bad, 8)
        with self.assertRaises(ValueError):
            cycle_minutes(1000, 1.5)

    def test_empty_evidence_must_not_approve(self):
        result = report_from_valhalla({"status": "BLOCKED_WITH_EVIDENCE"})
        self.assertEqual(result["routes"], [])
        self.assertTrue(all(v["status"] != "APROBADO" for v in result["vehicles"].values()))

    def test_real_routing_does_not_approve_turns(self):
        sample = {"status": "EXECUTED_ROUTES_REQUIRE_TURN_REVIEW",
                  "routing": {"routes": [{"id": "L1",
                    "outbound": {"status": "routed", "time_seconds": 1200},
                    "inbound": {"status": "routed", "time_seconds": 1400},
                    "turn_audit": [{"candidate": "L1", "point": {"lat": 19.8, "lon": -70.7}}]}]}}
        report = report_from_valhalla(sample, {"L1": 30})
        self.assertEqual(report["routes"][0]["routing"], "APROBADO")
        self.assertEqual(report["routes"][0]["physical_turns"], "PENDIENTE_DE_VERIFICACION")
        self.assertEqual(report["routes"][0]["cycle_status"], "EXPLORATORIO")
        self.assertEqual(report["vehicles"]["yutong_zk6126hg"]["turns"][0]["status"],
                         "PENDIENTE_DE_VERIFICACION")
        self.assertIsNone(VEHICLES["yutong_zk6126hg"]["turning_circle_m"])

    def test_missing_stop_count_does_not_invent_cycle(self):
        evidence = {"routing": {"routes": [{"id": "A", "outbound": {"status": "routed", "time_seconds": 200},
                   "inbound": {"status": "routed", "time_seconds": 200}}]}}
        route = report_from_valhalla(evidence)["routes"][0]
        self.assertEqual(route["cycle_status"], "PENDIENTE_DE_VERIFICACION")
        self.assertNotIn("cycle_scenarios", route)


if __name__ == "__main__":
    unittest.main()
