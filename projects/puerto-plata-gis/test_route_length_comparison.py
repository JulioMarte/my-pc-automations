import unittest
from route_length_comparison import compare
class Comparisons(unittest.TestCase):
 def test_distances_not_approvals(self):
  direct={"routes":[{"id":"C","outbound":{"distance_km":2.5},"inbound":{"distance_km":2.6}}]}
  via={"routes":[{"id":"C","complete_routable_sequence":True,"failed_segments":0,"sum_segment_distance_km":5.4}]}
  row=compare(direct,via)["routes"][0]
  self.assertEqual(row["difference_km"],.3)
  self.assertFalse(row["stop_order_verified"])
  self.assertFalse(row["operational_approval"])
 def test_failure_not_guessed(self):
  direct={"routes":[{"id":"C","outbound":{"distance_km":2.5},"inbound":{"distance_km":2.6}}]}
  via={"routes":[{"id":"C","complete_routable_sequence":False,"failed_segments":1,"sum_segment_distance_km":None}]}
  self.assertIsNone(compare(direct,via)["routes"][0]["difference_km"])
if __name__=="__main__":unittest.main()
