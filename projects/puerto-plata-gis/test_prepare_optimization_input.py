import unittest,tempfile,pathlib
from prepare_optimization_input import load_cycles
class Inputs(unittest.TestCase):
 def write(self,rows):
  t=tempfile.TemporaryDirectory()
  p=pathlib.Path(t.name)/"cycles.csv"
  p.write_text("route_id,cycle_minutes,cycle_source,operational_geometry_approved\n"+rows)
  self.addCleanup(t.cleanup)
  return p
 def test_reject_missing_time(self):
  with self.assertRaises(ValueError):load_cycles(self.write("L1,,measured,false\n"))
 def test_reject_undocumented_source(self):
  with self.assertRaises(ValueError):load_cycles(self.write("L1,120,unknown,false\n"))
 def test_allow_explicit_uncalibrated_but_flag_it(self):
  d=load_cycles(self.write("L1,120,uncalibrated_simulation,false\n"))
  self.assertEqual(d["L1"]["cycle_source"],"uncalibrated_simulation")
  self.assertFalse(d["L1"]["operational_geometry_approved"])
if __name__=="__main__":unittest.main()
