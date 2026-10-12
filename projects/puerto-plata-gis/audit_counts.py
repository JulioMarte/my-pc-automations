"""Aforos: classify observed counts separately from illustrative capture scenarios.

Never presents low/medium/high capture rates as ridership forecasts.
CSV: count_point,route_id,period,boardings,observation_minutes,source.
"""
import csv,json,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def analyze(rows):
 out=[];errors=[]
 for i,row in enumerate(rows):
  try:
   boardings=float(row["boardings"]);minutes=float(row["observation_minutes"])
   if boardings<0 or minutes<=0:raise ValueError("negative count or duration")
   if not row.get("count_point") or not row.get("source"):raise ValueError("missing provenance")
   out.append({"count_point":row["count_point"],"route_id":row.get("route_id"),
     "period":row.get("period"),"observed_boardings":boardings,
     "observed_hourly_rate":round(boardings*60/minutes,2),
     "observation_minutes":minutes,"source":row["source"]})
  except (KeyError,ValueError,TypeError) as e:errors.append({"row":i+1,"error":str(e)})
 return {"status":"OBSERVED_COUNTS_AVAILABLE" if out and not errors else "BLOCKED",
   "observed_samples":out,"errors":errors,
   "limitations":["Point observations are not a citywide OD matrix",
     "Hourly normalization is arithmetic, not a calibrated full-day ridership projection",
     "Sample representativeness and direction/season effects must be evaluated"]}
def main():
 p=argparse.ArgumentParser();p.add_argument("--csv",type=Path,required=True)
 p.add_argument("--output",type=Path,default=ROOT/"observed_counts_audit.json")
 a=p.parse_args()
 with a.csv.open(newline="",encoding="utf-8") as f:rows=list(csv.DictReader(f))
 result=analyze(rows);a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False))
 if result["status"]=="BLOCKED":raise SystemExit("Missing or invalid verified observational data")
 print("Aforos parsed:",len(result["observed_samples"]))
if __name__=="__main__":main()
