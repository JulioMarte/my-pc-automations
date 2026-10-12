"""Synthetic raster test: regression for fully controlled segmentation width."""
import json
import tempfile
import unittest
from pathlib import Path

class RasterMaskTests(unittest.TestCase):
    def test_width_10m_synthetic_not_approved(self):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from pyproj import Transformer
        from road_mask_measure import measure_mask
        convert=Transformer.from_crs("EPSG:4326","EPSG:32619",always_xy=True)
        x,y=convert.transform(-70.7,19.8)
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);mask=base/"road.tif"; tran=base/"transects.json"
            data=np.zeros((200,200),dtype=np.uint8)
            data[90:110,:]=1
            with rasterio.open(mask,"w",driver="GTiff",height=200,width=200,count=1,
                              dtype="uint8",crs="EPSG:32619",
                              transform=from_origin(x-50,y+50,0.5,0.5)) as ds:
                ds.write(data,1)
            inverse=Transformer.from_crs("EPSG:32619","EPSG:4326",always_xy=True)
            a=inverse.transform(x,y-20);b=inverse.transform(x,y+20)
            feature={"type":"Feature","properties":{"segment_id":"road:1"},
                     "geometry":{"type":"LineString","coordinates":[a,b]}}
            tran.write_text(json.dumps({"type":"FeatureCollection","features":[feature]}))
            result=measure_mask(mask,tran,max_samples=10)
            first=result["results"][0]
            self.assertEqual(first["state"],"PRELIMINARY_MASK_WIDTH")
            self.assertAlmostEqual(first["width_m"],10,delta=1)
            self.assertFalse(first["vehicle_approved"])
    def test_missing_mask_raises(self):
        from road_mask_measure import measure_mask
        with self.assertRaises(FileNotFoundError):
            measure_mask(Path("/does-not-exist.tif"),Path("/also-absent.geojson"))

if __name__=="__main__":unittest.main()
