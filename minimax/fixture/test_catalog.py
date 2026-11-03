import unittest
from catalog import list_items

class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'id':1,'category':'books'},{'id':2,'category':'tools'},
                   {'id':3,'category':''},{'id':4},{'id':5,'category':'books'}]
    def test_filter(self):
        self.assertEqual([x['id'] for x in list_items(self.rows,'books')],[1,5])
    def test_empty_category(self):
        self.assertEqual([x['id'] for x in list_items(self.rows,'')],[3])
    def test_unknown_and_case(self):
        self.assertEqual(list_items(self.rows,'Books'),[])
        self.assertEqual(list_items(self.rows,'unknown'),[])
    def test_regression_no_filter(self):
        self.assertEqual(list_items(self.rows),self.rows)
        self.assertIsNot(list_items(self.rows),self.rows)
    def test_input_not_mutated(self):
        original=[dict(x) for x in self.rows]
        list_items(self.rows,'books')
        self.assertEqual(self.rows,original)

if __name__=='__main__': unittest.main(verbosity=2)
