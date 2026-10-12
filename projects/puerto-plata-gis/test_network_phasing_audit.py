import unittest
from network_phasing_audit import audit

def case(budget,ids):
 return {"budget":budget,"assumed_speed_kmh":18,"scenario":"with_l1",
         "selected_routes":[{"route":id} for id in ids]}
class PhaseTests(unittest.TestCase):
 def test_non_nested_routes_flagged(self):
  x=audit({"proposals":[case(10,["L1","A"]),case(20,["L1","B"]),case(30,["L1","B","C"])]})
  transitions=x["groups"][0]["transitions"]
  self.assertEqual(transitions[0]["status"],"REPLACEMENT_NOT_STRAIGHT_EXPANSION")
  self.assertEqual(transitions[0]["lost"],["A"])
  self.assertFalse(x["groups"][0]["fully_nested_candidate_sequence"])
 def test_nested_still_not_approved(self):
  x=audit({"proposals":[case(10,["L1"]),case(20,["L1","A"]),case(30,["L1","A","B"])]})
  self.assertTrue(x["groups"][0]["fully_nested_candidate_sequence"])
  self.assertEqual(x["phased_expansion_approved"],0)
 def test_missing_budget_blocks(self):
  x=audit({"proposals":[case(10,["L1"])]})
  self.assertEqual(x["groups"][0]["transitions"][0]["status"],"MISSING_PHASE")
if __name__=="__main__":unittest.main()
