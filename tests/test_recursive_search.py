import struct
import unittest

from core.recursive_search import RecursiveSearchEngine, RecursiveSearchParams


class RecursiveSearchEngineTests(unittest.TestCase):
    def _memory(self):
        mem = {
            0x1000: struct.pack("<4Q", 0x2000, 0x2008, 123, 456),
            0x2000: struct.pack("<2Q", 0xDEAD, 0x3000),
            0x3000: struct.pack("<2Q", 0xCAFE, 999),
        }

        def read_func(address, size):
            data = mem.get(address)
            if data is None:
                return None
            return data[:size]

        return read_func

    def test_root_match(self):
        engine = RecursiveSearchEngine(self._memory())
        params = RecursiveSearchParams(123, 0x1000, 32, 0, 0xFFFFFFFF, 2, True)
        matches = engine.search(params)
        self.assertEqual([m.address for m in matches], [0x1010])
        self.assertEqual(matches[0].offsets, [16])

    def test_full_search_follows_pointers(self):
        engine = RecursiveSearchEngine(self._memory())
        params = RecursiveSearchParams(0xDEAD, 0x1000, 32, 0, 0xFFFFFFFF, 2, True)
        matches = engine.search(params)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].address, 0x2000)
        self.assertEqual(matches[0].offsets, [0, 0])

    def test_first_match_stops(self):
        engine = RecursiveSearchEngine(self._memory())
        params = RecursiveSearchParams(0xDEAD, 0x1000, 32, 0, 0xFFFFFFFF, 2, False)
        matches = engine.search(params)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].address, 0x2000)

    def test_depth_limit(self):
        engine = RecursiveSearchEngine(self._memory())
        params = RecursiveSearchParams(0xCAFE, 0x1000, 32, 0, 0xFFFFFFFF, 1, True)
        matches = engine.search(params)
        self.assertEqual(matches, [])

    def test_circular_reference_guard(self):
        mem = {
            0x1000: struct.pack("<Q", 0x2000),
            0x2000: struct.pack("<Q", 0x1000),
        }

        def read_func(address, size):
            data = mem.get(address)
            return data[:size] if data is not None else None

        engine = RecursiveSearchEngine(read_func)
        params = RecursiveSearchParams(0xDEAD, 0x1000, 8, 0, 0xFFFFFFFF, 10, True)
        matches = engine.search(params)
        self.assertEqual(matches, [])
        self.assertEqual(engine.visited_count, 2)


if __name__ == "__main__":
    unittest.main()