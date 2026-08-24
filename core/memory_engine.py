"""内存交互门面：统一封装驱动读写、表达式解析与批量读取请求。"""
import struct
from typing import Any, Dict

from PySide6.QtCore import QObject, Signal

from common.types import DataType
from core.fetcher import Fetcher, ReadRequest
from core.memory_tool import CrackerMemTool, MemoryTool


class MemoryEngine(QObject):
    """组合 MemoryTool 与 Fetcher，作为 UI 层唯一的内存访问入口。"""

    attachStatusChanged = Signal(bool)
    fetch_finished = Signal(dict)
    fetch_error = Signal(str)

    def __init__(
        self,
        backend: MemoryTool = None,
        merge_threshold: int = 0x100,
        chunk_size: int = 0x1000,
        parent=None,
    ):
        super().__init__(parent)
        self._backend = backend or CrackerMemTool()
        self._fetcher = Fetcher(self._backend, merge_threshold, chunk_size)
        self._fetcher.finished.connect(self.fetch_finished)
        self._fetcher.error.connect(self.fetch_error)
        self._backend.attachStatusChanged.connect(self.attachStatusChanged)

    @property
    def backend(self) -> MemoryTool:
        return self._backend

    @property
    def fetcher(self) -> Fetcher:
        return self._fetcher

    # ---------- 附加 / 分离 ----------

    def isAttached(self) -> bool:
        return self._backend.isAttached()

    def attach(self, process_name: str) -> None:
        self._backend.setProcessName(process_name)
        self._backend.attach()

    def detach(self) -> None:
        self._backend.close()

    def close(self) -> None:
        self._backend.close()

    def attachedStatusGuard(self) -> None:
        self._backend.attachedStatusGuard()

    # ---------- 表达式与底层内存 ----------

    def resolve_expression(self, expression: str, is64bit: bool = True) -> int:
        return self._backend.getAddrByExpression(expression, is64bit)

    def getBaseAddress(self, module_name: str) -> int:
        return self._backend.getBaseAddress(module_name)

    def read(self, address: int, size: int) -> tuple:
        return self._backend.read(address, size)

    def write(self, address: int, data: bytes) -> bool:
        if not self._backend.write(address, data):
            raise RuntimeError("写入失败")
        return address

    def dump(self, address: int, size: int, chunk_size: int = 0x100) -> tuple:
        return self._backend.dump(address, size, chunk_size)

    def dumpCenter(self, address: int, size: int, chunk_size: int = 0x100) -> tuple:
        return self._backend.dumpCenter(address, size, chunk_size)

    # ---------- 批量读取 ----------

    def fetch(self, requests: Dict[Any, ReadRequest]) -> None:
        self._fetcher.request(requests)

    # ---------- 高层修改 ----------

    def modify(self, address_expr, value_expr: str, data_type: DataType) -> int:
        """解析地址表达式并写入内存，成功时返回解析后的绝对地址。"""
        address = self.resolve_expression(address_expr) if isinstance(address_expr, str) else address_expr

        if data_type == DataType.STRING:
            data = value_expr.encode("utf-8")
        else:
            val = eval(value_expr, {}, {})
            if data_type == DataType.BYTE:
                data = struct.pack("b", val)
            elif data_type == DataType.INT16:
                data = struct.pack("<h", val)
            elif data_type in (DataType.INT32, DataType.HEX32):
                data = struct.pack("<i", val)
            elif data_type == DataType.INT64:
                data = struct.pack("<q", val)
            elif data_type == DataType.HEX64:
                data = struct.pack("<Q", val)
            elif data_type == DataType.FLOAT:
                data = struct.pack("<f", val)
            elif data_type == DataType.DOUBLE:
                data = struct.pack("<d", val)
            else:
                raise ValueError(f"不支持的数据类型: {data_type}")

        if not self._backend.write(address, data):
            raise RuntimeError("写入失败")
        return address