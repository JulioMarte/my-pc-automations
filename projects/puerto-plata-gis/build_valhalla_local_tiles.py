"""Build a local Valhalla tile archive from an existing OSM PBF, without HTTP.

Invokes pyvalhalla bundled C++ tooling; throws if any stage fails. Usage:
 python build_valhalla_local_tiles.py --osm-pbf ./dominican-republic-latest.osm.pbf
"""
import argparse,subprocess,sys,hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def sha256(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 return h.hexdigest()
def execute(pbf,output):
 pbf=Path(pbf).resolve();output=Path(output).resolve()
 if not pbf.is_file():raise FileNotFoundError(f"Missing PBF: {pbf}")
 output.mkdir(parents=True,exist_ok=True)
 config=output/"valhalla.json"
 tiles=output/"valhalla_tiles.tar"
 with config.open("w",encoding="utf-8") as stream:
  subprocess.run(["valhalla_build_config",
      "--mjolnir-tile-dir",str(output/"tiles"),
      "--mjolnir-tile-extract",str(tiles)],stdout=stream,check=True)
 subprocess.run([sys.executable,"-m","valhalla","valhalla_build_tiles",
      "-c",str(config),str(pbf)],check=True)
 subprocess.run(["valhalla_build_extract","-c",str(config),"--overwrite"],check=True)
 if not tiles.is_file() or tiles.stat().st_size==0:raise RuntimeError("No Valhalla tiles generated")
 report={"status":"BUILT_LOCALLY_NOT_BUS_APPROVED","pbf":str(pbf),
   "pbf_sha256":sha256(pbf),"tiles":str(tiles),"tiles_sha256":sha256(tiles),
   "note":"Tiles are local and routable; do not infer legal turns or swept-path clearance."}
 (output/"valhalla_build_manifest.json").write_text(json.dumps(report,indent=2))
 return report
def main():
 p=argparse.ArgumentParser();p.add_argument("--osm-pbf",type=Path,required=True)
 p.add_argument("--output-dir",type=Path,default=ROOT/"data/valhalla")
 a=p.parse_args();print(json.dumps(execute(a.osm_pbf,a.output_dir),indent=2))
if __name__=="__main__":main()
