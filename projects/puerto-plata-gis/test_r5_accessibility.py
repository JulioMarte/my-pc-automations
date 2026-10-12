import unittest
from r5_accessibility import summarize_matrix,points_from_worldpop

class R5PipelineTests(unittest.TestCase):
 def test_reachability_per_origin_no_double_count(self):
  origins=[{"id":"O0","population":8},{"id":"O1","population":12},{"id":"O2","population":20}]
  matrix=[
   {"from_id":"O0","to_id":"D0","travel_time":12},
   {"from_id":"O0","to_id":"D1","travel_time":14},
   {"from_id":"O1","to_id":"D0","travel_time":34},
   {"from_id":"O2","to_id":"D0","travel_time":None}]
  a=summarize_matrix(matrix,origins)["thresholds_minutes"]
  self.assertEqual(a["15"]["population_with_at_least_one_destination"],8)
  self.assertEqual(a["30"]["population_with_at_least_one_destination"],8)
  self.assertEqual(a["45"]["population_with_at_least_one_destination"],20)
 def test_empty_matrix_does_not_claim_coverage(self):
  a=summarize_matrix([], [{"id":"O1","population":12}])
  self.assertEqual(a["thresholds_minutes"]["15"]["share_of_modelled_origin_population"],0)
  self.assertEqual(a["unreachable_origin_count"],1)
 def test_null_travel_time_not_reachable(self):
  a=summarize_matrix([{"from_id":"O1","to_id":"D1","travel_time":None}],[{"id":"O1","population":9}])
  self.assertEqual(a["thresholds_minutes"]["45"]["population_with_at_least_one_destination"],0)
if __name__=="__main__":unittest.main()
