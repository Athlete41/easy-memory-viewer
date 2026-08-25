import unittest

from core.search_engine import SearchEngine
from common.types import DataType


class SearchEngineTests(unittest.TestCase):
    def test_unknown_first_scan_includes_all(self):
        engine = SearchEngine()
        data = bytes(range(16))
        results = engine.initial_scan(data, 0, DataType.BYTE, "未知", alignment=1)
        self.assertEqual(len(results), 16)

    def test_string_first_scan_has_no_unknown(self):
        engine = SearchEngine()
        self.assertNotIn("未知", engine.get_first_ops(DataType.STRING))


if __name__ == "__main__":
    unittest.main()