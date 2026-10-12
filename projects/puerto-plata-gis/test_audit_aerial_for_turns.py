import unittest
from audit_aerial_for_turns import evaluate,bbox_contains

def queue():
    return {"status":"UNVERIFIED_FIELD_SURVEY_QUEUE","risks":[{"candidate":"C00-10","longitude":-70.69,"latitude":19.79,"heading_change_deg":72}]}

class AerialTurnAuditTests(unittest.TestCase):
    def test_inexact_old_image_not_approved(self):
        image={"id":"test","bbox":[-70.7,19.78,-70.68,19.8],"gsd_m_reported":.49,"datetime":"2017-09-08T00:00:00Z","license_reported":"CC-BY-NC-4.0"}
        result=evaluate([image],queue())
        self.assertEqual(result["turns_with_catalog_bbox_overlap"],1)
        self.assertEqual(result["fit_for_precision_measurements"],0)
        m=result["turns"][0]["matches"][0]
        self.assertIn("HISTORICAL_IMAGE",m["blockers"])
        self.assertIn("GSD_NOT_SUFFICIENT_FOR_PRECISION_PILOT",m["blockers"])
        self.assertIn("LICENSE_NOT_VERIFIED_FOR_UNRESTRICTED_USE",m["blockers"])

    def test_new_high_resolution_remains_unverified(self):
        image={"id":"new","bbox":[-70.7,19.78,-70.68,19.8],"gsd_m_reported":.05,"datetime":"2026-09-01T00:00:00Z","license_reported":"CC-BY-4.0"}
        m=evaluate([image],queue())["turns"][0]["matches"][0]
        self.assertFalse(m["fit_for_width_measurement"])
        self.assertIn("HORIZONTAL_ACCURACY_UNVERIFIED",m["blockers"])

    def test_bbox_missing_is_no_coverage(self):
        self.assertFalse(bbox_contains(None,-70.69,19.79))
        self.assertEqual(evaluate([],queue())["turns_with_catalog_bbox_overlap"],0)

    def test_rejects_approved_queue(self):
        with self.assertRaises(ValueError):evaluate([],{"status":"APPROVED","risks":[]})
if __name__=="__main__":unittest.main()
