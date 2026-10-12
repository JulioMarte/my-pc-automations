"""Regression tests for unbiased transit corridor baseline; no external datasets."""
import json,unittest
from pathlib import Path
import networkx as nx
from zones_od import build,demand
from generate_candidates import generate,road_graph,numeric_limit
from vehicle_screen import inspect

CFG=json.loads((Path(__file__).resolve().parent/"config.json").read_text())
class BaselineTests(unittest.TestCase):
 def test_h3_scenarios_and_external_uncertainty(self):
  import h3
  lat,lon=19.788,-70.68
  pop={"cells":[[lat,lon,900],[lat+.015,lon+.015,500]]}
  poi={"features":[{"geometry":{"type":"Point","coordinates":[lon+.002,lat+.002]},
                   "properties":{"type":"retail"}},
                   {"geometry":{"type":"Point","coordinates":[lon+.019,lat+.015]},
                   "properties":{"type":"jobs"}}]}
  z=build(pop,poi,CFG,8)
  self.assertTrue(z["zones"])
  d,lines=demand(z,CFG,limit=20)
  self.assertEqual(len(d["scenarios"]),9)
  self.assertTrue(all("RELATIVE" in item["mode"] for s in d["scenarios"] for item in s["od"]))
  self.assertTrue(any(item["external_origin_assumed"] for s in d["scenarios"] for item in s["od"]))
  self.assertEqual(lines["type"],"FeatureCollection")
 def test_candidate_geometry_not_legacy(self):
  g=nx.MultiDiGraph()
  for i in range(12):g.add_node(i,x=-70.7+i*.001,y=19.8)
  for i in range(11):
   g.add_edge(i,i+1,length=110,highway="residential")
   g.add_edge(i+1,i,length=110,highway="residential")
  cfg=json.loads(json.dumps(CFG))
  cfg["generation"].update(target_min=1,target_max=50,min_route_km=.1,seed_top_od=2)
  od={"scenarios":[{"level":"medium","exponent":1,
         "od":[{"origin":"x","destination":"y","origin_lonlat":[-70.7,19.8],
                "destination_lonlat":[-70.69,19.8],"relative_flow_units":10}]}]}
  result=generate(g,od,cfg)
  self.assertGreater(result["generated_unique"],0)
  self.assertTrue(all(not f["properties"]["physical_approval"] for f in result["features"]))
  self.assertTrue(all(f["properties"]["candidate_id"].startswith("AUTO-") for f in result["features"]))
 def test_explicit_osm_bus_clearance_blocks_graph_edge(self):
  g=nx.MultiDiGraph()
  g.add_node(1,x=-70.7,y=19.8);g.add_node(2,x=-70.699,y=19.8)
  g.add_edge(1,2,length=110,maxwidth="2.4",highway="residential")
  self.assertEqual(numeric_limit("2.4 m"),2.4)
  self.assertEqual(road_graph(g,CFG["vehicle"]).number_of_edges(),0)
 def test_vehicle_envelope_fails_closed(self):
  shape={"geometry":{"coordinates":[[-70.7,19.8],[-70.699,19.8],[-70.699,19.801]]}}
  out=inspect(shape,CFG)
  self.assertEqual(out["status"],"DUDOSO")
  self.assertFalse(out["physically_approved"])
  self.assertEqual(out["turning_diameter_reference_m"],[20.5,21.5])
  self.assertEqual(len(out["turning_sensitivity"]),2)
if __name__=="__main__":unittest.main()
