from enum import Enum
import struct


class Endian(Enum):
    LITTLE = "little"
    BIG = "big"


_STRUCTS = {}
_TYPE_SIZE = {}

class DataType(Enum):
    BYTE = "Byte"
    INT16 = "Int16"
    INT32 = "Int32"
    INT64 = "Int64"
    FLOAT = "Float"
    DOUBLE = "Double"
    STRING = "String"
    HEX32 = "4 Byte Hex"
    HEX64 = "8 Byte Hex"

    @classmethod
    def from_string(cls, name: str) -> "DataType":
        """从字符串获取对应的 DataType 枚举"""
        for dt in cls:
            if dt.value == name:
                return dt
        raise ValueError(f"Unknown DataType: {name}")


    def get_struct(self, default: struct.Struct = None) -> struct.Struct:
        """获取对应的 struct.Struct 对象"""
        global _STRUCTS
        return _STRUCTS.get(self, default)


    def get_size(self, default: int = 0) -> int:
        """获取对应的字节数"""
        global _TYPE_SIZE
        return _TYPE_SIZE.get(self, default)


_STRUCTS = {
    DataType.BYTE: struct.Struct("<B"),
    DataType.INT16: struct.Struct("<h"),
    DataType.INT32: struct.Struct("<i"),
    DataType.INT64: struct.Struct("<q"),
    DataType.FLOAT: struct.Struct("<f"),
    DataType.DOUBLE: struct.Struct("<d"),
    DataType.HEX32: struct.Struct("<I"),
    DataType.HEX64: struct.Struct("<Q"),
}
_TYPE_SIZE = {
    DataType.BYTE: 1,
    DataType.INT16: 2,
    DataType.INT32: 4,
    DataType.INT64: 8,
    DataType.FLOAT: 4,
    DataType.DOUBLE: 8,
    DataType.HEX32: 4,
    DataType.HEX64: 8,
}
    
class Encoding(Enum):
    ASCII = "ascii"
    UTF8 = "utf-8"
    GBK = "gbk"
    BIG5 = "big5"

class FormatConfig:
    def __init__(self, data_type: DataType, endian: Endian = Endian.LITTLE,
                 str_len: int = 16, encoding: str = 'utf-8'):
        self.data_type = data_type
        self.endian = endian
        self.str_len = str_len

        if isinstance(encoding, Encoding):
            encoding = encoding.value
        self.encoding = encoding

    def get_size(self) -> int:
        if self.data_type == DataType.STRING:
            return self.str_len
        return self.data_type.get_size(1)

    @staticmethod
    def format_value(chunk: bytes, fmt: "FormatConfig") -> str:
        try:
            if fmt.data_type == DataType.BYTE:
                return f"{chunk[0]:02X}"
            elif fmt.data_type == DataType.INT16:
                val = struct.unpack('<h' if fmt.endian == Endian.LITTLE else '>h', chunk[:2])[0]
                return f"{val}"
            elif fmt.data_type == DataType.INT32:
                val = struct.unpack('<i' if fmt.endian == Endian.LITTLE else '>i', chunk[:4])[0]
                return f"{val}"
            elif fmt.data_type == DataType.INT64:
                val = struct.unpack('<q' if fmt.endian == Endian.LITTLE else '>q', chunk[:8])[0]
                return f"{val}"
            elif fmt.data_type == DataType.FLOAT:
                val = struct.unpack('<f' if fmt.endian == Endian.LITTLE else '>f', chunk[:4])[0]
                return f"{val:.6f}"
            elif fmt.data_type == DataType.DOUBLE:
                val = struct.unpack('<d' if fmt.endian == Endian.LITTLE else '>d', chunk[:8])[0]
                return f"{val:.12f}"
            elif fmt.data_type == DataType.HEX32:
                if len(chunk) < 4:
                    return "??"
                if fmt.endian == Endian.LITTLE:
                    return f"0x{chunk[3]:02X}{chunk[2]:02X}{chunk[1]:02X}{chunk[0]:02X}"
                else:
                    return f"0x{chunk[0]:02X}{chunk[1]:02X}{chunk[2]:02X}{chunk[3]:02X}"
            elif fmt.data_type == DataType.HEX64:
                if len(chunk) < 8:
                    return "??"
                if fmt.endian == Endian.LITTLE:
                    return f"0x{chunk[7]:02X}{chunk[6]:02X}{chunk[5]:02X}{chunk[4]:02X}{chunk[3]:02X}{chunk[2]:02X}{chunk[1]:02X}{chunk[0]:02X}"
                else:
                    return f"0x{chunk[0]:02X}{chunk[1]:02X}{chunk[2]:02X}{chunk[3]:02X}{chunk[4]:02X}{chunk[5]:02X}{chunk[6]:02X}{chunk[7]:02X}"
            elif fmt.data_type == DataType.STRING:
                end = chunk.find(b'\x00')
                if end == -1:
                    end = len(chunk)
                try:
                    s = chunk[:end].decode(fmt.encoding, errors='replace')
                except LookupError:
                    s = chunk[:end].decode('utf-8', errors='replace')
                return s
        except Exception as e:
            print(e)
            return "??"
        return "??"



def parse_value_from_bytes(data: bytes, data_type: DataType) -> int | float | str:
    """
    从原始字节解析值（供外部调度器使用）
    
    Args:
        data: 原始字节
        data_type: 数据类型
    
    Returns:
        解析后的值，如果数据不足则返回 None
    """
    if not data:
        return None

    if data_type == DataType.STRING:
        raw = data
        if b"\x00" in raw:
            raw = raw.split(b"\x00", 1)[0]
        try:
            return raw.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")

    struct_obj = data_type.get_struct()
    byte_size = data_type.get_size(0)
    if struct_obj is None or len(data) < byte_size:
        return None
    return struct_obj.unpack_from(data, 0)[0]


