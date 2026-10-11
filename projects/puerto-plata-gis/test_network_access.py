import unittest
import networkx as nx
from network_access import coverage

def graph(two_way=True):
 g=nx.MultiDiGraph()
 g.add_node(1,x=-70.7,y=19.8);g.add_node(2,x=-70.69,y=19.8)
 g.add_edge(1,2,length=1050)
 if two_way:g.add_edge(2,1,length=1050)
 return g

class TestEdgeAccess(unittest.TestCase):
 def test_short_same_edge(self):
  g=graph()
  # nearby points on the same ~1050m physical segment, far from graph nodes
  a=[19.8,-70.696]
  b=[19.8,-70.695]
  report=coverage(g,[a],[[*b,12]],radius=250,max_snap=30)
  self.assertEqual(report["residents"],12)
 def test_far_on_same_edge(self):
  g=graph()
  report=coverage(g,[[19.8,-70.699]],[[19.8,-70.691,12]],radius=250,max_snap=30)
  self.assertEqual(report["residents"],0)
 def test_no_double_count_multiple_stops(self):
  g=graph()
  report=coverage(g,[[19.8,-70.699],[19.8,-70.698]],[[19.8,-70.699,12]],radius=500,max_snap=30)
  self.assertEqual(report["residents"],12)
 def test_reject_unsnapped_stop(self):
  with self.assertRaises(ValueError):coverage(graph(),[[19.9,-70.6]],[[19.8,-70.7,1]],500,30)

if __name__=="__main__":unittest.main()
