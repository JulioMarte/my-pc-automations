import unittest
from zero_budget_roadmap import assess

def samples():
    road={"roads":{"road_features":8096,"tag_counts":{"width":0,"lanes":430}},"measurements_count":0}
    image={"assessed_turns":1,"turns":[{"width_measurement_status":"BLOCKED"}],"turns_with_catalog_bbox_overlap":1,"fit_for_precision_measurements":0}
    turn={"total_tasks":1,"maneuvers_approved":0,"risks":[{"physical_turn_status":"NOT_ASSESSED"}]}
    return road,image,turn

class RoadmapTests(unittest.TestCase):
    def test_no_budget_no_false_pass(self):
        result=assess(*samples())
        self.assertTrue(result["no_fieldwork"])
        self.assertEqual(result["operationally_approved_routes"],0)
        self.assertEqual(result["next_milestone"],"REAL_ROUTED_PATH_GEOMETRY")
    def test_rejects_mismatched_inputs(self):
        r,i,t=samples()
        i["assessed_turns"]=2
        with self.assertRaises(ValueError):assess(r,i,t)
    def test_rejects_claimed_turn_certification(self):
        r,i,t=samples()
        t["maneuvers_approved"]=1
        with self.assertRaises(ValueError):assess(r,i,t)
    def test_missing_road_inventory(self):
        r,i,t=samples()
        del r["roads"]
        with self.assertRaises(ValueError):assess(r,i,t)
if __name__=="__main__":unittest.main()
