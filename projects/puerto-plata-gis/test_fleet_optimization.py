import unittest
from fleet_optimization import fleet,soft_penalty,solve
class FleetTests(unittest.TestCase):
 def test_reserves(self):self.assertEqual(fleet(110,10,0.15),13)
 def test_penalty_is_soft(self):
  c={"penalties":{"max_desirable_sinuosity":1.4,"sinuosity_excess_weight":2,"reference_grade_percent":10,"grade_excess_weight":3}}
  self.assertEqual(soft_penalty(1.8,12,c),6.8)
 def test_control_without_l1_can_win(self):
  routes=[{"id":"L1","buses":10,"covered_cells":["a"]},
   {"id":"B","buses":5,"covered_cells":["b","c"]}]
  cells={"a":20,"b":60,"c":30}
  self.assertEqual(solve(routes,cells,[10],True)[0]["selected"],["L1"])
  self.assertEqual(solve(routes,cells,[10],False)[0]["selected"],["B"])
 def test_double_count(self):
  routes=[{"id":"L1","buses":5,"covered_cells":["a","b"]},{"id":"B","buses":5,"covered_cells":["b","c"]}]
  r=solve(routes,{"a":10,"b":20,"c":30},[10],False)[0]
  self.assertEqual(r["estimated_residents_with_stop_access"],60)
if __name__=="__main__":unittest.main()
