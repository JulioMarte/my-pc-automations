"""Extract preliminary drivable width from a *licensed, georeferenced binary road mask*.

Mask pixels: 1 road surface, 0 not-road. Requires a reviewed road segmentation.
Does not classify raw satellite imagery or approve Yutong turning clearance.
"""
import argparse, json, math
from pathlib import Path

def measure_mask(mask_path, transects_path, *, max_samples=1000, pixel_step=0.5):
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from shapely.geometry import shape
    if not mask_path.exists(): raise FileNotFoundError(mask_path)
    transects=json.loads(transects_path.read_text())["features"]
    results=[]
    with rasterio.open(mask_path) as ds:
        if ds.count!=1 or not ds.crs: raise ValueError("Mask must be 1 band and georeferenced")
        if ds.crs.is_geographic: raise ValueError("Mask must use a projected metric CRS")
        if ds.res[0]<=0 or ds.res[1]<=0:raise ValueError("Invalid raster resolution")
        transform=Transformer.from_crs("EPSG:4326",ds.crs,always_xy=True)
        pixels=ds.read(1,masked=True)
        cell_m=max(ds.res)
        for feature in transects[:max_samples]:
            line=shape(feature["geometry"])
            if len(line.coords)!=2:continue
            a=transform.transform(*line.coords[0]);b=transform.transform(*line.coords[1])
            span=math.dist(a,b)
            if span<1:continue
            unit=((b[0]-a[0])/span,(b[1]-a[1])/span)
            middle=((a[0]+b[0])/2,(a[1]+b[1])/2)
            step=min(pixel_step,cell_m/2)
            # Probe samples beginning at the center and moving in both directions.
            def probe(direction):
                distance=0.0
                while distance<=span/2:
                    x=middle[0]+unit[0]*distance*direction
                    y=middle[1]+unit[1]*distance*direction
                    row,col=ds.index(x,y)
                    if not (0<=row<ds.height and 0<=col<ds.width):return distance
                    value=pixels[row,col]
                    if np.ma.is_masked(value) or int(value)!=1:return distance
                    distance+=step
                return span/2
            center_row,center_col=ds.index(*middle)
            if not (0<=center_row<ds.height and 0<=center_col<ds.width):
                state="OUTSIDE_RASTER"; width=None
            elif np.ma.is_masked(pixels[center_row,center_col]) or int(pixels[center_row,center_col])!=1:
                state="CENTER_NOT_DRIVABLE";width=None
            else:
                left=probe(-1);right=probe(1)
                if left>=span/2 or right>=span/2:
                    state="EDGE_NOT_FOUND";width=None
                else:
                    width=round(left+right,2);state="PRELIMINARY_MASK_WIDTH"
            results.append({"segment_id":feature["properties"].get("segment_id"),
                "state":state,"width_m":width,"pixel_size_m":round(cell_m,3),
                "uncertainty_lower_bound_m":round(2*cell_m,3),
                "vehicle_approved":False})
    return {"status":"IMAGE_DERIVED_ONLY_NOT_FIELD_VERIFIED",
            "source_mask":str(mask_path),"results":results,"approved_turns":0,
            "limitations":["Road mask must be licensed and independently reviewed",
                           "Metadata spatial accuracy adds to displayed pixel-only uncertainty",
                           "Parking, sidewalks and median need independent labels",
                           "No bus swept-path geometry validated"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mask",type=Path,required=True)
    p.add_argument("--transects",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--max-samples",type=int,default=1000)
    a=p.parse_args()
    if a.max_samples<1:raise ValueError("invalid maximum")
    a.output.write_text(json.dumps(measure_mask(a.mask,a.transects,max_samples=a.max_samples),indent=2))
if __name__=="__main__":main()
