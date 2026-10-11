import unittest
import build_od_synthetic as od
class TestSyntheticOD(unittest.TestCase):
 def test_spatial_filter_and_periods(self):
  stops=[[19.8,-70.7],[19.8,-70.69]]
  pop=[[19.8,-70.7,10],[19.8,-70.69,20],[19.81,-70.7,100]]
  poi=[{"geometry":{"type":"Point","coordinates":[-70.69,19.8]},"properties":{"type":"health"}}]
  data=od.calc(pop,poi,stops)
  self.assertEqual(data["resident_coverage_estimate"],30)
  self.assertEqual(len(data["periods"]),6)
  morning=next(p for p in data["periods"] if p["period"]=="06:30-09:00")
  self.assertTrue(morning["top_od_pairs"])
  self.assertEqual(morning["top_od_pairs"][0]["origin_stop"],1)
  self.assertEqual(morning["top_od_pairs"][0]["destination_stop"],2)
 def test_no_double_count(self):
  stops=[[19.8,-70.7],[19.8,-70.7005]]
  self.assertEqual(od.calc([[19.8,-70.7,17]],[],stops)["resident_coverage_estimate"],17)
 def test_non_factual_units(self):
  d=od.calc([[19.8,-70.7,1]],[],[[19.8,-70.7]])
  self.assertIn("NOT interpret as trips",d["metadata"]["units"])
if __name__=="__main__":unittest.main()
