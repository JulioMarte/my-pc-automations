import unittest
from h3_od_zones import build
from h3_gravity_od import model,desire_geojson

C={"urban_extent_bbox_lonlat":[-70.752,19.740,-70.620,19.836],
"h3_resolutions":[8,9],"primary_resolution":8,"urban_boundary":"BBOX_PROXY",
"poi_category_weights":{"other":1,"commercial":4},
"gravity":{"exponents":[1,1.5,2],"distance_offset_km":.7,
"demand_scenarios":{"low":{"trips_per_resident_day_assumed":.2},
"medium":{"trips_per_resident_day_assumed":.5},"high":{"trips_per_resident_day_assumed":.9}},
"max_destination_cells_per_origin":5,"top_desire_lines":100},
"gateway_zones":[{"name":"Sosua","lat":19.755,"lon":-70.517,"external_trip_weight_assumed":25}],
"sources":{"production":"WorldPop hypothetical","attraction":"Overture hypothetical"}}
P={"cells":[[19.8,-70.7,200],[19.801,-70.68,100],[19.79,-70.69,50]]}
D={"features":[{"geometry":{"type":"Point","coordinates":[-70.68,19.801]},"properties":{"type":"commercial"}},
               {"geometry":{"type":"Point","coordinates":[-70.69,19.79]},"properties":{"type":"other"}}]}
class Tests(unittest.TestCase):
 def test_h3_cell_population_mass_and_provenance(self):
  z=build(P,D,C)
  self.assertEqual(z["status"],"H3_POPULATION_POI_PROXIES_UNCALIBRATED")
  self.assertAlmostEqual(sum(c["worldpop_residents_estimated"] for c in z["h3_cells"]["8"]),350,places=2)
  self.assertEqual(sum(c["poi_count"] for c in z["h3_cells"]["9"]),2)
  self.assertTrue(z["no_prior_corridors_used"])
 def test_9_od_scenarios_and_gateways(self):
  z=build(P,D,C);r=model(z,C)
  self.assertEqual(len(r["experiments"]),9)
  self.assertFalse(r["observed_trips"])
  self.assertTrue(any(x["external_gateway_assumption"] for x in r["experiments"][0]["all_od_flows"]))
  self.assertTrue(desire_geojson(r)["features"])
 def test_no_poi_blocks_not_fabricates(self):
  z=build(P,{"features":[]},C)
  with self.assertRaises(ValueError):model(z,C)
if __name__=="__main__":unittest.main()
