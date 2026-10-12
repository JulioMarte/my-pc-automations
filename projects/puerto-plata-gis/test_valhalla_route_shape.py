import unittest
from valhalla_route_shape import decode_polyline6,extract_shape,encode_test_polyline6

class ShapeTests(unittest.TestCase):
 def test_roundtrip_real_coordinates(self):
  path=[[-70.700001,19.800001],[-70.698001,19.800001],[-70.698001,19.798001]]
  shape=encode_test_polyline6(path)
  self.assertEqual(decode_polyline6(shape),path)
  evidence=extract_shape({"trip":{"legs":[{"shape":shape}]}})
  self.assertEqual(evidence["status"],"ROAD_GRAPH_SHAPE_NOT_SWEPT_PATH")
  self.assertEqual(evidence["vertex_count"],3)
  self.assertFalse(evidence["turn_approved"])
 def test_missing_shape_explicit(self):
  evidence=extract_shape({"trip":{"summary":{"length":2.5}}})
  self.assertEqual(evidence["status"],"NO_SHAPE_IN_BACKEND_RESPONSE")
  self.assertIsNone(evidence["geometry"])
 def test_truncated_polyline_rejected(self):
  with self.assertRaises(ValueError):decode_polyline6("~")
 def test_invalid_char_rejected(self):
  with self.assertRaises(ValueError):decode_polyline6("!@@")
if __name__=="__main__":unittest.main()
