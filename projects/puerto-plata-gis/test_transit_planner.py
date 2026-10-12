"""Regression checks for headways, fleet, boarding capacities and transfers."""
import unittest
import copy
import transit_planner as p

class PlannerTests(unittest.TestCase):
 def setUp(self):self.cfg=copy.deepcopy(p.DEFAULT)
 def test_peak_fleet(self):
  r=p.evaluate(self.cfg)
  self.assertEqual(r["fleet"]["fleet_total"],21) # 11 large + 6 small + 4 reserves
  self.assertEqual(r["fleet"]["capital_dop_assumption"],(11+2)*8800000+(6+2)*4000000)
 def test_headways_and_capacity(self):
  r=p.evaluate(self.cfg)
  morn=next(x for x in r["periods"] if x["period"]=="manana")
  self.assertEqual([x["active_vehicles"] for x in morn["lines"]],[11,6])
  self.assertEqual([x["places_per_hour_per_direction"] for x in morn["lines"]],[360,120])
  self.assertEqual([x["expected_random_wait_minutes"] for x in morn["lines"]],[5,7.5])
 def test_offpeak(self):
  r=p.evaluate(self.cfg)
  row=next(x for x in r["periods"] if x["period"]=="tarde")
  self.assertEqual([x["active_vehicles"] for x in row["lines"]],[8,5])
 def test_transfer_is_not_claimed_verified(self):
  r=p.evaluate(self.cfg)
  self.assertTrue(all(q["coordination_unverified"] for q in r["transfers"][0]["periods"]))
 def test_invalid_config(self):
  self.cfg["routes"][0]["peak_headway"]=0
  with self.assertRaises(ValueError):p.evaluate(self.cfg)
 def test_no_fictitious_line(self):
  self.cfg["transfers"][0]["to"]="L10"
  with self.assertRaises(ValueError):p.evaluate(self.cfg)
if __name__=="__main__":unittest.main()
