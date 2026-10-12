import unittest
from optimize_headways import vehicle_requirement,optimize
class HeadwayTests(unittest.TestCase):
 def test_fleet_by_headway(self):
  self.assertEqual(vehicle_requirement(100,10,0.15)["total"],12)
  self.assertEqual(vehicle_requirement(100,20,0.15)["total"],6)
 def test_critical_missing_cycle(self):
  with self.assertRaises(ValueError):vehicle_requirement(None,10,0.15)
 def test_unknown_not_allowed(self):
  with self.assertRaises(ValueError):
   optimize([{"id":"L1","covered_cells":["a"],"cycle_minutes":100,"cycle_source":"uncalibrated_simulation","operational_geometry_approved":False}],{"a":100},[10])
 def test_control_arm_and_headways(self):
  routes=[{"id":"L1","covered_cells":["a"],"cycle_minutes":100,"cycle_source":"calibrated_simulation","operational_geometry_approved":True},
    {"id":"B","covered_cells":["b"],"cycle_minutes":60,"cycle_source":"measured","operational_geometry_approved":True}]
  cells={"a":20,"b":200}
  a=optimize(routes,cells,[6],[10,15,20],l1_required=True)[0]
  b=optimize(routes,cells,[6],[10,15,20],l1_required=False)[0]
  self.assertIn("L1",[x["route"] for x in a["selected"]])
  self.assertEqual([x["route"] for x in b["selected"]],["B"])
  self.assertLessEqual(b["buses"],10)
 def test_union_no_double_count(self):
  routes=[{"id":n,"covered_cells":["same"],"cycle_minutes":40,"cycle_source":"measured","operational_geometry_approved":True} for n in ("L1","B")]
  r=optimize(routes,{"same":90},[15],[10,15,20])[0]
  self.assertEqual(r["covered_residents_estimate"],90)
if __name__=="__main__":unittest.main()
