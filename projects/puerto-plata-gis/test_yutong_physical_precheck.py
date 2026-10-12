import unittest
from yutong_physical_precheck import assess,body_polygon,envelope
CONFIG={"vehicle":{"length_m":12.17,"width_m":2.55,"wheelbase_m":6.0,"front_overhang_m":2.74,
"rear_overhang_m":3.43,"turning_circle_diameters_sensitivity_m":[20.5,21.5]}}
class PrecheckTests(unittest.TestCase):
 def test_vehicle_dimensions_and_envelope(self):
  self.assertAlmostEqual(body_polygon(0,0,0).area,12.17*2.55)
  a=envelope([[-70.7,19.8],[-70.699,19.8]],dict(length=12.17,width=2.55,wheelbase=6,front=2.74,rear=3.43))
  self.assertGreater(a.area,12.17*2.55)
 def test_doubtful_not_approved(self):
  c={"candidates":[{"id":"OD-a","geometry":{"coordinates":[[-70.7,19.8],[-70.699,19.8]]}}]}
  x=assess(c,CONFIG)
  self.assertEqual(x["DUDOSO"],1)
  self.assertEqual(x["VIABLE"],0)
  self.assertFalse(x["physical_approval"])
 def test_degenerate_marked_inviable(self):
  c={"candidates":[{"id":"OD-z","geometry":{"coordinates":[[-70.7,19.8]]}}]}
  x=assess(c,CONFIG)
  self.assertEqual(x["INVIABLE"],1)
if __name__=="__main__":unittest.main()
