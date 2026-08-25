import unittest

from core.memory_engine import MemoryEngine, ReadRequest


class MergeRequestTests(unittest.TestCase):
    def test_merge_close_requests(self):
        engine = MemoryEngine()
        requests = [
            ReadRequest("a", 0x1000, 0x20),
            ReadRequest("b", 0x1030, 0x10),
            ReadRequest("c", 0x2000, 0x10),
        ]
        merged = engine._merge_requests(requests)
        self.assertEqual(
            [(rng.start, rng.end) for rng in merged],
            [(0x1000, 0x1040), (0x2000, 0x2010)],
        )

    def test_merge_keeps_far_requests_separate(self):
        engine = MemoryEngine()
        requests = [
            ReadRequest("a", 0x1000, 0x10),
            ReadRequest("b", 0x2000, 0x10),
        ]
        merged = engine._merge_requests(requests)
        self.assertEqual(
            [(rng.start, rng.end) for rng in merged],
            [(0x1000, 0x1010), (0x2000, 0x2010)],
        )


if __name__ == "__main__":
    unittest.main()