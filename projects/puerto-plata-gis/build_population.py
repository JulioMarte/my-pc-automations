from pathlib import Path
import json, urllib.request
import rasterio
from rasterio.windows import from_bounds, transform as wintransform
URL="https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/DOM/v1/100m/constrained/dom_pop_2025_CN_100m_R2025A_v1.tif"
ROOT=Path(__file__).resolve().parent
raw=ROOT/"worldpop_dom_2025.tif"
if not raw.exists(): urllib.request.urlretrieve(URL,raw)
with rasterio.open(raw) as ds:
    win=from_bounds(-70.84,19.68,-70.55,19.88,ds.transform).round_offsets().round_lengths()
    arr=ds.read(1,window=win,masked=True)
    tf=wintransform(win,ds.transform)
    values=[]
    for iy in range(arr.shape[0]):
      for ix in range(arr.shape[1]):
        p=arr[iy,ix]
        if not bool(getattr(p,"mask",False)):
          v=float(p)
          if v>0 and v<100000:
            lon,lat=tf*(ix+.5,iy+.5)
            values.append([round(lat,6),round(lon,6),round(v,3)])
res={"metadata":{"name":"WorldPop constrained 2025 alpha R2025A","source":URL,"unit":"estimated residents per raster cell, not census headcount","cellWidthDegrees":abs(tf.a),"cellHeightDegrees":abs(tf.e),"coverage":"Puerto Plata bounding box (not municipal boundary)","year":2025},"cells":values}
(ROOT/"population.json").write_text(json.dumps(res,separators=(",",":")))
print("population cells",len(values),"file KB",(ROOT/"population.json").stat().st_size//1024)
