import unittest
from service_cycle_scenarios import compute
from valhalla_route_shape import encode_test_polyline6

def source(end=None):
    a=[-70.7,19.8]
    b=end or [-70.69,19.8]
    return {"routes":[{"id":"C00-09","waypoints":3,
        "complete_routable_sequence":True,"sum_segment_distance_km":3.7,
        "endpoints":{"start":a,"end":b}}]}
class Actor:
    def route(self,req):
        a=req["locations"][0];b=req["locations"][1]
        return {"trip":{"summary":{"length":1.5,"time":260},
                        "legs":[{"shape":encode_test_polyline6([[a["lon"],a["lat"]],[b["lon"],b["lat"]]])}]}}
class Broken:
    def route(self,req):raise RuntimeError("unreachable")
class Tests(unittest.TestCase):
    def test_connector_and_full_sensitivity(self):
        x=compute(source(),Actor())
        r=x["routes"][0]
        self.assertTrue(r["fully_routable_graph_loop"])
        self.assertEqual(len(r["scenarios"]),12)
        self.assertAlmostEqual(r["scenarios"][0]["service_distance_km"],5.2)
        self.assertEqual(x["approved_service_cycles"],0)
    def test_broken_connector_fails_closed(self):
        x=compute(source(),Broken())
        self.assertFalse(x["routes"][0]["fully_routable_graph_loop"])
        self.assertFalse(x["routes"][0]["scenarios"])
    def test_coincident_ends_still_not_approved(self):
        x=compute(source(end=[-70.7,19.8]),Broken())
        self.assertTrue(x["routes"][0]["fully_routable_graph_loop"])
        self.assertFalse(x["routes"][0]["terminal_turnaround_approved"])
    def test_missing_waypoint_legs_block(self):
        s=source()
        s["routes"][0]["complete_routable_sequence"]=False
        x=compute(s,Actor())
        self.assertEqual(x["routable_loops"],0)
if __name__=="__main__":unittest.main()
