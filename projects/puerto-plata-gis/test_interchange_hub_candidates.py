import unittest
from interchange_hub_candidates import hubs
class HubTests(unittest.TestCase):
 def test_two_transfer_links_cluster(self):
  p={"budget":10,"scenario":"with_l1","assumed_speed_kmh":18,
    "transfer_links":[
    {"route_a":"L1","route_b":"A","lonlat_a":[-70.7,19.8],"lonlat_b":[-70.6999,19.8],
     "transfer_walk_m_straight_line":11,"expected_wait_minutes_if_random_arrival":5},
    {"route_a":"L1","route_b":"B","lonlat_a":[-70.7,19.8],"lonlat_b":[-70.6998,19.8],
     "transfer_walk_m_straight_line":22,"expected_wait_minutes_if_random_arrival":7.5}]}
  x=hubs({"proposals":[p]})
  self.assertEqual(x["networks"][0]["interchange_candidates"][0]["connecting_route_count"],3)
  self.assertEqual(x["approved_hubs"],0)
 def test_no_links_no_fabricated_hubs(self):
  x=hubs({"proposals":[{"budget":10,"scenario":"with_l1","assumed_speed_kmh":18,"transfer_links":[]}]})
  self.assertEqual(x["networks"][0]["interchange_candidates"],[])
if __name__=="__main__":unittest.main()
