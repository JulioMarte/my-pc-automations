import unittest
from discover_transit_network import totals, rank_combos
class CompetitionTests(unittest.TestCase):
 def test_overlap_is_not_additive(self):
  cells=[(None,10),(None,20),(None,30)]
  a={0,1};b={1,2}
  self.assertEqual(totals(a|b,cells),60)
  self.assertEqual(totals(b-a,cells),30)
 def test_pairs(self):
  routes={"L1":{"pop_set":{0},"poi_set":{1}},"A":{"pop_set":{0,1},"poi_set":{1,2}},"B":{"pop_set":{0,2},"poi_set":{1,3}}}
  self.assertIn(("A","B"),rank_combos(routes))
if __name__=="__main__":unittest.main()
