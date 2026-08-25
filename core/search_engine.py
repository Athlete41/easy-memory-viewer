# core/search_engine.py
from __future__ import annotations

from enum import Enum
from typing import List, Union, Optional, Tuple
from dataclasses import dataclass

from common.types import DataType


@dataclass
class SearchResult:
    """搜索结果条目"""
    address: int          # 绝对地址（由 SearchEngine 根据 base_address 计算）
    value: Union[int, float, str]
    data_type: DataType


class SearchState(Enum):
    IDLE = "idle"
    HAS_RESULTS = "has_results"


# 首次搜索操作符
FIRST_OPS_NUMERIC = ["=", ">", "<", "between", "未知"]
FIRST_OPS_STRING = [
    "包含(忽略大小写)",
    "包含(精确大小写)",
    "开头是(忽略大小写)",
    "开头是(精确大小写)",
    "结尾是(忽略大小写)",
    "结尾是(精确大小写)",
]

# 再次搜索操作符
NEXT_OPS_NUMERIC = ["=", ">", "<", "between", "增加", "减少", "变化", "不变"]
NEXT_OPS_STRING = [
    "包含(忽略大小写)",
    "包含(精确大小写)",
    "开头是(忽略大小写)",
    "开头是(精确大小写)",
    "结尾是(忽略大小写)",
    "结尾是(精确大小写)",
    "变化",
    "不变",
]


class SearchEngine:
    """
    搜索引擎（状态机版本）
    
    状态: IDLE → 首次扫描 → HAS_RESULTS → 再次扫描 → HAS_RESULTS → 清空 → IDLE
    
    内部存储地址为偏移量，对外返回绝对地址（base_address + 偏移量）。
    
    支持类型: Byte, Int16, Int32, Int64, Float, Double, HEX32, HEX64, String
    支持操作符: =, >, <, between, 增加, 减少, 变化, 不变
    """

    def __init__(self) -> None:
        self._state = SearchState.IDLE
        self._last_results: List[SearchResult] = []  # 存储偏移量
        self._string_len = 0

    # ================= 状态查询 =================

    @property
    def state(self) -> SearchState:
        return self._state

    @property
    def has_results(self) -> bool:
        return self._state == SearchState.HAS_RESULTS

    def get_results(self) -> List[SearchResult]:
        """获取当前搜索结果（偏移量，仅供内部/测试使用）"""
        return self._last_results.copy()

    # ================= 首次扫描 =================

    def initial_scan(
        self,
        data: bytes,
        value: Union[int, float, str],
        data_type: DataType,
        op: str,
        alignment: int = 1,
        base_address: int = 0,
    ) -> List[SearchResult]:
        """
        首次扫描
        
        Args:
            data: 要搜索的二进制数据
            value: 搜索目标值
            data_type: 数据类型
            op: 操作符
            alignment: 对齐字节数
            base_address: 数据基址（用于将偏移量转换为绝对地址）
        
        Returns:
            List[SearchResult]: 搜索结果，address 为绝对地址
        """
        if not self._is_valid_first_op(data_type, op):
            raise ValueError(f"首次扫描不支持操作符: {op} (类型: {data_type.value})")

        if data_type == DataType.STRING:
            raw_results = self._scan_string_initial(data, str(value), op, alignment)
        else:
            raw_results = self._scan_numeric_initial(data, value, data_type, op, alignment)

        self._last_results = raw_results
        self._state = SearchState.HAS_RESULTS
        return self._to_absolute(raw_results, base_address)

    # ================= 再次扫描 =================

    def next_scan(
        self,
        data: bytes,
        value: Union[int, float, str],
        data_type: DataType,
        op: str,
        base_address: int = 0,
    ) -> List[SearchResult]:
        """
        再次扫描（在已有结果上过滤）
        
        Args:
            data: 当前最新的二进制数据
            value: 搜索目标值
            data_type: 数据类型
            op: 操作符
            base_address: 数据基址（用于将偏移量转换为绝对地址）
        
        Returns:
            List[SearchResult]: 过滤后的结果，address 为绝对地址
        """
        if self._state != SearchState.HAS_RESULTS:
            raise RuntimeError("请先进行首次扫描")

        if not self._last_results:
            return []

        if not self._is_valid_next_op(data_type, op):
            raise ValueError(f"再次扫描不支持操作符: {op} (类型: {data_type.value})")

        if op in ("增加", "减少", "变化", "不变"):
            raw_results = self._scan_change(data, data_type, op)
        elif data_type == DataType.STRING:
            raw_results = self._scan_string_next(data, str(value), op)
        else:
            raw_results = self._scan_numeric_next(data, value, data_type, op)

        self._last_results = raw_results
        return self._to_absolute(raw_results, base_address)

    # ================= 清空 =================

    def clear(self) -> None:
        """清空所有结果，重置状态"""
        self._last_results.clear()
        self._string_len = 0
        self._state = SearchState.IDLE

    # ================= 操作符查询 =================

    @staticmethod
    def get_first_ops(data_type: DataType) -> List[str]:
        """获取首次扫描操作符列表"""
        if data_type == DataType.STRING:
            return FIRST_OPS_STRING.copy()
        return FIRST_OPS_NUMERIC.copy()

    @staticmethod
    def get_next_ops(data_type: DataType) -> List[str]:
        """获取再次扫描操作符列表"""
        if data_type == DataType.STRING:
            return NEXT_OPS_STRING.copy()
        return NEXT_OPS_NUMERIC.copy()

    # ================= 内部工具方法 =================

    @staticmethod
    def _to_absolute(results: List[SearchResult], base_address: int) -> List[SearchResult]:
        """将偏移量转换为绝对地址"""
        if base_address == 0:
            return results
        return [
            SearchResult(r.address + base_address, r.value, r.data_type)
            for r in results
        ]

    @staticmethod
    def _is_valid_first_op(data_type: DataType, op: str) -> bool:
        if data_type == DataType.STRING:
            return op in FIRST_OPS_STRING
        return op in FIRST_OPS_NUMERIC

    @staticmethod
    def _is_valid_next_op(data_type: DataType, op: str) -> bool:
        if data_type == DataType.STRING:
            return op in NEXT_OPS_STRING
        return op in NEXT_OPS_NUMERIC

    @staticmethod
    def _parse_value(value: Union[int, float, str], data_type: DataType) -> Union[int, float]:
        """将输入解析为数值"""
        if isinstance(value, (int, float)):
            return value
        s = str(value).strip()
        if s.startswith("0x") or s.startswith("0X"):
            return int(s, 16)
        try:
            if data_type in (DataType.FLOAT, DataType.DOUBLE):
                return float(s)
            return int(s)
        except ValueError:
            raise ValueError(f"无法解析数值: {s}")

    @staticmethod
    def _parse_range(value: Union[int, float, str]) -> Tuple[Union[int, float], Union[int, float]]:
        """解析范围字符串，如 '10-20' 或 '10,20'"""
        s = str(value).strip()
        if '-' in s:
            parts = s.split('-', 1)
        elif ',' in s:
            parts = s.split(',', 1)
        else:
            raise ValueError(f"范围格式错误，需要包含 '-' 或 ',' : {s}")

        if len(parts) != 2:
            raise ValueError(f"范围格式错误: {s}")

        def parse_num(x: str) -> Union[int, float]:
            x = x.strip()
            if x.startswith("0x") or x.startswith("0X"):
                return int(x, 16)
            try:
                return int(x)
            except ValueError:
                return float(x)

        return parse_num(parts[0]), parse_num(parts[1])

    @staticmethod
    def _find_all(data: bytes, pattern: bytes) -> List[int]:
        """在 bytes 中查找所有 pattern 出现的位置"""
        if not pattern:
            return []
        positions = []
        size = len(data)
        limit = size - len(pattern) + 1
        start = 0
        while start < limit:
            pos = data.find(pattern, start, size)
            if pos < 0:
                break
            positions.append(pos)
            start = pos + 1
        return positions

    @staticmethod
    def _matches_numeric(current: Union[int, float], target: Union[int, float], op: str) -> bool:
        if op == "=":
            if isinstance(current, float) or isinstance(target, float):
                diff = abs(current - target)
                scale = max(1.0, abs(current), abs(target))
                return diff <= 1e-6 * scale
            return current == target
        if op == ">":
            return current > target
        if op == "<":
            return current < target
        return False

    # ================= 内部扫描实现（返回偏移量） =================

    def _scan_numeric_initial(
        self,
        data: bytes,
        value: Union[int, float, str],
        data_type: DataType,
        op: str,
        alignment: int,
    ) -> List[SearchResult]:
        """数值首次扫描（返回偏移量）"""
        byte_size = data_type.get_size()
        unpack = data_type.get_struct().unpack_from
        results = []
        step = max(1, alignment)
        limit = len(data) - byte_size + 1

        if op == "between":
            min_val, max_val = self._parse_range(value)
            for off in range(0, max(limit, 0), step):
                raw = unpack(data, off)[0]
                if min_val <= raw <= max_val:
                    results.append(SearchResult(off, raw, data_type))
        elif op == "未知":
            for off in range(0, max(limit, 0), step):
                raw = unpack(data, off)[0]
                results.append(SearchResult(off, raw, data_type))
        else:
            target = self._parse_value(value, data_type)
            for off in range(0, max(limit, 0), step):
                raw = unpack(data, off)[0]
                if self._matches_numeric(raw, target, op):
                    results.append(SearchResult(off, raw, data_type))
        return results

    def _scan_numeric_next(
        self,
        data: bytes,
        value: Union[int, float, str],
        data_type: DataType,
        op: str,
    ) -> List[SearchResult]:
        """数值再次扫描（返回偏移量）"""
        byte_size = data_type.get_size()
        unpack = data_type.get_struct().unpack_from
        results = []

        if op == "between":
            min_val, max_val = self._parse_range(value)
            for result in self._last_results:
                off = result.address
                if off + byte_size > len(data):
                    continue
                raw = unpack(data, off)[0]
                if min_val <= raw <= max_val:
                    results.append(SearchResult(off, raw, data_type))
        else:
            target = self._parse_value(value, data_type)
            for result in self._last_results:
                off = result.address
                if off + byte_size > len(data):
                    continue
                raw = unpack(data, off)[0]
                if self._matches_numeric(raw, target, op):
                    results.append(SearchResult(off, raw, data_type))
        return results

    def _scan_string_initial(
        self,
        data: bytes,
        value: str,
        op: str,
        alignment: int,
    ) -> List[SearchResult]:
        """字符串首次扫描（返回偏移量）"""
        pattern = value.encode("utf-8")
        self._string_len = len(pattern)
        base_op = op.split("(", 1)[0]
        case_sensitive = "忽略大小写" not in op

        haystack = data if case_sensitive else data.lower()
        needle = pattern if case_sensitive else pattern.lower()

        results = []
        step = max(1, alignment)
        for pos in self._find_all(haystack, needle):
            if pos % step != 0:
                continue
            if base_op == "结尾是":
                result_off = pos + len(needle) - 1
            else:
                result_off = pos
            raw = data[result_off:result_off + self._string_len]
            if b"\x00" in raw:
                raw = raw.split(b"\x00", 1)[0]
            val = raw.decode("utf-8", errors="replace")
            results.append(SearchResult(result_off, val, DataType.STRING))
        return results

    def _scan_string_next(
        self,
        data: bytes,
        value: str,
        op: str,
    ) -> List[SearchResult]:
        """字符串再次扫描（返回偏移量）"""
        base_op = op.split("(", 1)[0]
        case_sensitive = "忽略大小写" not in op
        target = value if case_sensitive else value.lower()
        results = []

        for result in self._last_results:
            off = result.address
            raw = data[off:off + self._string_len]
            if b"\x00" in raw:
                raw = raw.split(b"\x00", 1)[0]
            try:
                current = raw.decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                current = raw.decode("latin-1", errors="replace")

            compare = current if case_sensitive else current.lower()
            if base_op == "包含" and target in compare:
                results.append(SearchResult(off, current, DataType.STRING))
            elif base_op == "开头是" and compare.startswith(target):
                results.append(SearchResult(off, current, DataType.STRING))
            elif base_op == "结尾是" and compare.endswith(target):
                results.append(SearchResult(off, current, DataType.STRING))
        return results

    def _scan_change(
        self,
        data: bytes,
        data_type: DataType,
        op: str,
    ) -> List[SearchResult]:
        """变化/不变/增加/减少 扫描（返回偏移量）"""
        results = []

        for result in self._last_results:
            off = result.address
            old_value = result.value

            current = self._read_value(data, off, data_type)
            if current is None:
                continue

            if op == "增加" and current > old_value:
                results.append(SearchResult(off, current, data_type))
            elif op == "减少" and current < old_value:
                results.append(SearchResult(off, current, data_type))
            elif op == "变化" and current != old_value:
                results.append(SearchResult(off, current, data_type))
            elif op == "不变" and current == old_value:
                results.append(SearchResult(off, current, data_type))
        return results

    def _read_value(
        self,
        data: bytes,
        offset: int,
        data_type: DataType,
    ) -> Optional[Union[int, float, str]]:
        """读取指定偏移的值（内部使用，offset 为偏移量）"""
        if data_type == DataType.STRING:
            raw = data[offset:offset + self._string_len]
            if b"\x00" in raw:
                raw = raw.split(b"\x00", 1)[0]
            try:
                return raw.decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")

        struct_obj = data_type.get_struct()
        byte_size = data_type.get_size(0)
        if struct_obj is None or offset + byte_size > len(data):
            return None
        return struct_obj.unpack_from(data, offset)[0]