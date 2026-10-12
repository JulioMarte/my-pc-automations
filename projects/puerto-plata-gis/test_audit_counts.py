import unittest
from audit_counts import analyze
class CountTests(unittest.TestCase):
 def test_real_observation_is_normalized_not_forecast(self):
  r=analyze([{"count_point":"P1","route_id":"L1","period":"AM","boardings":"7","observation_minutes":"30","source":"survey-2026"}])
  self.assertEqual(r["observed_samples"][0]["observed_hourly_rate"],14)
  self.assertEqual(r["status"],"OBSERVED_COUNTS_AVAILABLE")
 def test_unprovenance_blocks(self):
  self.assertEqual(analyze([{"count_point":"P1","boardings":"10","observation_minutes":"60","source":""}])["status"],"BLOCKED")
 def test_empty_is_blocked(self):self.assertEqual(analyze([])["status"],"BLOCKED")
if __name__=="__main__":unittest.main()
