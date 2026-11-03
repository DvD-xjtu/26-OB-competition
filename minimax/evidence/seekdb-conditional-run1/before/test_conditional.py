import unittest
from unittest_module_check import iter_active_includes

class ConditionalIncludes(unittest.TestCase):
    def check(self,source,expected):
        self.assertEqual(expected,list(iter_active_includes(source)))
    def test_false_elif(self):
        self.check('#if 0\n#include "a.h"\n#elif 0\n#include "b.h"\n#else\n#include "c.h"\n#endif',[(6,'c.h')])
    def test_taken_elif(self):
        self.check('#if 0\n#elif 1\n#include "a.h"\n#else\n#include "b.h"\n#endif',[(3,'a.h')])
    def test_nested_disabled(self):
        self.check('#if 0\n#if 0\n#elif 1\n#include "a.h"\n#else\n#include "b.h"\n#endif\n#endif',[])
    def test_unknown_remains_conservative(self):
        self.check('#if FLAG\n#include "a.h"\n#else\n#include "b.h"\n#endif',[(2,'a.h'),(4,'b.h')])
    def test_repeated_literal_elif(self):
        self.check('#if 0\n#elif 0\n#include "a.h"\n#elif 1\n#include "b.h"\n#elif 1\n#include "c.h"\n#else\n#include "d.h"\n#endif',[(5,'b.h')])

if __name__=='__main__': unittest.main()
