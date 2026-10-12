import unittest
from rank_network_proposals import rank

def p(status="DESKTOP_SCREEN_PASS_UNVALIDATED"):
 return {"budget":10,"scenario":"with_l1","assumed_speed_kmh":18,
         "desktop_status":status,"desktop_checks":{"has_mapped_destination_access":True},
         "selected_routes":[{"route":"C00-09"}],"resident_coverage_proxy":2000,
         "destinations":{"pois_reached_proxy":3},"transfer_links":[],
         "isolated_routes":[],"peak_sensitivity":[{"peak_headway_over_target":False}],
         "operational_gate":"REJECTED_PENDING_CRITICAL_EVIDENCE"}
class RankTests(unittest.TestCase):
 def test_rank_never_approves_vehicles(self):
  x=rank({"proposals":[p()]})
  self.assertEqual(x["operationally_approved"],0)
  self.assertEqual(len(x["comparisons"][0]["desktop_survivors"]),1)
 def test_failed_desktop_candidate_is_not_survivor(self):
  x=rank({"proposals":[p("DESKTOP_SCREEN_REVIEW_OR_REJECT")]})
  self.assertEqual(len(x["comparisons"][0]["desktop_survivors"]),0)
 def test_missing_status_rejected(self):
  bad=p();bad.pop("desktop_status")
  with self.assertRaises(ValueError):rank({"proposals":[bad]})
if __name__=="__main__":unittest.main()
