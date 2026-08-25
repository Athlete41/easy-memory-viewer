import unittest

from common.types import DataType, Endian, FormatConfig, pack_value


class DataTypeTests(unittest.TestCase):
    def test_unsigned_sizes(self):
        self.assertEqual(DataType.UINT16.get_size(), 2)
        self.assertEqual(DataType.UINT32.get_size(), 4)
        self.assertEqual(DataType.UINT64.get_size(), 8)

    def test_format_unsigned(self):
        fmt = FormatConfig(DataType.UINT16, Endian.LITTLE)
        self.assertEqual(fmt.format_value(b"\x34\x12", fmt), "4660")
        fmt32 = FormatConfig(DataType.UINT32, Endian.LITTLE)
        self.assertEqual(fmt32.format_value(b"\x00\x00\x00\x80", fmt32), "2147483648")

    def test_pack_value(self):
        self.assertEqual(pack_value(4660, DataType.UINT16), b"\x34\x12")
        self.assertEqual(pack_value(0xFFFFFFFF, DataType.UINT32), b"\xff\xff\xff\xff")
        self.assertEqual(pack_value(123, DataType.HEX64), (123).to_bytes(8, "little"))
        self.assertEqual(pack_value("abc", DataType.STRING), b"abc")


if __name__ == "__main__":
    unittest.main()