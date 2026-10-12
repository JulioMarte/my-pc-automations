import unittest
from unittest.mock import patch
from discover_open_aerial import parse_stac,retrieve

class AerialDiscoveryTests(unittest.TestCase):
    def test_empty_stac_is_no_data(self):
        self.assertEqual(parse_stac({"type":"FeatureCollection","features":[]}),[])
    def test_discovered_image_is_not_automatically_licensed(self):
        data={"features":[{"id":"tile-1","bbox":[-70.71,19.77,-70.70,19.78],
              "properties":{"gsd":0.15,"license":"CC-BY-4.0"},
              "assets":{"visual":{"href":"https://example.org/test.tif"}}}]}
        result=parse_stac(data)
        self.assertEqual(result[0]["gsd_m_reported"],0.15)
        self.assertFalse(result[0]["eligible_for_measurement"])
        self.assertFalse(result[0]["verified_puerto_plata_coverage"])
    def test_malformed_api_response_raises(self):
        with self.assertRaises(ValueError):parse_stac({"results":[]})
    def test_network_failure_captured_as_evidence(self):
        with patch("discover_open_aerial.urllib.request.urlopen",side_effect=OSError("network disabled")):
            result=retrieve()
        self.assertEqual(result["status"],"BLOCKED_DISCOVERY_ERROR")
        self.assertIn("network disabled",result["failure"])
if __name__=="__main__":unittest.main()
