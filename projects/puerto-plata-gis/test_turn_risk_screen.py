"""Regresiones de filtro de cambios angulares de puntos GIS."""
import unittest
from turn_risk_screen import screen

def candidate(points):
    return {"type":"Feature","geometry":{"type":"MultiPoint","coordinates":points},
            "properties":{"id":"C-test"}}

class TurnRiskTests(unittest.TestCase):
    def test_waypoint_bend_is_not_certified(self):
        result=screen([candidate([[0,0],[0.001,0],[0.001,0.001]])])
        self.assertEqual(len(result["risks"]),1)
        self.assertEqual(result["risks"][0]["status"],"PENDIENTE_VERIFICACION")
        self.assertEqual(result["risks"][0]["heading_change_deg"],90)
        self.assertEqual(result["status"],"EXPLORATORIO_SIN_APROBACION_FISICA")

    def test_straight_is_not_risk(self):
        self.assertFalse(screen([candidate([[0,0],[0.001,0],[0.002,0]])])["risks"])

    def test_duplicate_waypoint_is_ignored(self):
        self.assertFalse(screen([candidate([[0,0],[0,0],[0.001,0]])])["risks"])

if __name__=="__main__": unittest.main()
