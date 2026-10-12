import unittest
from mobility_multicriteria_cp_sat import optimize,transfer_pairs

def fixture():
 routes=[{"id":"L1","cycle_minutes":20,"covered_cells":["a"]},
         {"id":"R2","cycle_minutes":25,"covered_cells":["b"]},
         {"id":"R3","cycle_minutes":32,"covered_cells":["c"]}]
 cells={"a":1200,"b":950,"c":300}
 stops={"L1":[[-70.7,19.8]],"R2":[[-70.7001,19.8]],"R3":[[-70.7010,19.8]]}
 poi=[{"geometry":{"type":"Point","coordinates":[-70.7001,19.8]},"properties":{"type":"hospital"}}]
 return routes,cells,stops,poi
class Tests(unittest.TestCase):
 def test_nested_route_retention_and_no_approval(self):
  x=optimize(*fixture(),budgets=(4,9,15),headways=(20,),reserve=0,peak_multiplier=1.2,l1_required=True)
  self.assertEqual(x["status"],"EXPLORATORY_MULTIOBJECTIVE_NESTED_CP_SAT")
  selected=[{y["route"] for y in b.get("selected",[])} for b in x["budgets"]]
  self.assertIn("L1",selected[0])
  self.assertTrue(selected[0].issubset(selected[1]))
  self.assertTrue(selected[1].issubset(selected[2]))
  self.assertEqual(x["physical_routes_approved"],0)
 def test_missing_l1_is_error(self):
  r,c,s,p=fixture()
  with self.assertRaises(ValueError):optimize(r[1:],c,s,p,l1_required=True)
 def test_transfer_candidates(self):
  *_,stops,poi=fixture()
  self.assertTrue(any({a,b}=={"L1","R2"} for a,b,d in transfer_pairs(stops,["L1","R2","R3"])))
if __name__=="__main__":unittest.main()
