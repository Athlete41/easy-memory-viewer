"""统一内存层：驱动读写、表达式解析、指针缓存与批量请求合并。"""
import ctypes
import re
import struct
from dataclasses import dataclass
from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal

import core.cracker_client as ct
from common.types import DataType, pack_value


@dataclass
class ReadRequest:
    """读取请求，带 id 用于路由。"""
    id: Any
    address: int
    size: int


@dataclass
class MergedRange:
    start: int
    end: int  # 不包含

    @property
    def size(self) -> int:
        return self.end - self.start


class MemoryEngine(QObject):
    """UI 层唯一的内存访问入口：驱动、表达式、缓存、批量读取都在这里。"""

    attachStatusChanged = Signal(bool)
    fetch_finished = Signal(dict)
    fetch_error = Signal(str)

    def __init__(
        self,
        process_name: str = "",
        merge_threshold: int = 0x100,
        chunk_size: int = 0x1000,
        parent=None,
    ):
        super().__init__(parent)
        self.process_name = process_name
        self.pid = 0
        self.modules: dict[str, int] = {}
        self._handle = None
        self._merge_threshold = merge_threshold
        self._chunk_size = chunk_size
        self._pointer_cache: Dict[int, int] = {}

    # ================= 附加 / 分离 =================

    def isAttached(self) -> bool:
        return self._handle is not None and self.pid != 0

    def attach(self, process_name: str = None) -> None:
        if process_name:
            self.process_name = process_name
        if not self.process_name:
            raise RuntimeError("进程名为空")

        handle = ct.openDevice()
        try:
            _, pid = ct.getPidByName(handle, self.process_name)
            if pid == 0:
                raise RuntimeError(f"找不到进程: \"{self.process_name}\"")
            self.pid = pid
            self.modules.clear()
            self.attachStatusChanged.emit(True)
        except Exception:
            ct.closeDevice(handle)
            raise

        self._handle = handle
        self._pointer_cache.clear()

    def detach(self) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is not None:
            ct.closeDevice(self._handle)
            self._handle = None
        self.pid = 0
        self.modules.clear()
        self._pointer_cache.clear()
        self.attachStatusChanged.emit(False)

    def attachedStatusGuard(self) -> None:
        if not self.isAttached():
            return
        _, pid = ct.getPidByName(self._handle, self.process_name)
        if pid == 0:
            self.close()

    # ================= 驱动读写 =================

    def read(self, address: int, size: int) -> tuple:
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")
        buffer = ctypes.create_string_buffer(size)
        status, _ = ct.readWriteMemoryMdl(
            self._handle, self.pid, address, size,
            ctypes.addressof(buffer), ct.READ_FLAG,
        )
        if status != 0:
            return b"\x00" * size, False
        return buffer.raw[:size], True

    def _unpack(self, fmt: str, buffer: bytes):
        try:
            return struct.unpack_from(fmt, buffer)[0]
        except struct.error:
            return 0

    def readUInt8(self, address: int) -> int:
        return self._unpack("<B", self.read(address, 1)[0])

    def readUInt16(self, address: int) -> int:
        return self._unpack("<H", self.read(address, 2)[0])

    def readUInt32(self, address: int) -> int:
        return self._unpack("<I", self.read(address, 4)[0])

    def readUInt64(self, address: int) -> int:
        return self._unpack("<Q", self.read(address, 8)[0])

    def readInt32(self, address: int) -> int:
        return self._unpack("<i", self.read(address, 4)[0])

    def readFloat(self, address: int) -> float:
        return self._unpack("<f", self.read(address, 4)[0])

    def readDouble(self, address: int) -> float:
        return self._unpack("<d", self.read(address, 8)[0])

    def readString(self, address: int, size: int = 100, decode: str = "utf-8") -> str:
        buffer = self.read(address, size)[0]
        end = buffer.find(b"\x00")
        if end != -1:
            buffer = buffer[:end]
        return buffer.decode(decode, errors="ignore")

    def write(self, address: int, data: bytes) -> bool:
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")
        size = len(data)
        buffer = ctypes.create_string_buffer(data, size + 1)
        status, _ = ct.readWriteMemoryMdl(
            self._handle, self.pid, address, size,
            ctypes.addressof(buffer), ct.WRITE_FLAG,
        )
        return status == 0

    def dump(self, address: int, size: int, chunk_size: int = 0x100) -> tuple:
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")
        return ct.dumpMemory(self._handle, self.pid, address, size, chunk_size)

    def dumpCenter(self, address: int, size: int, chunk_size: int = 0x100) -> tuple:
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")
        start = max(0, address - size)
        end = address + size
        total = end - start
        if total <= 0:
            return b"", False
        return ct.dumpMemory(self._handle, self.pid, start, total, chunk_size)

    # ================= 模块基址与指针缓存 =================

    def getBaseAddress(self, module_name: str) -> int:
        """直读驱动获取模块基址，不使用缓存。"""
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")
        status, base = ct.getModuleBase(self._handle, self.pid, module_name)
        if status != 0 or base == 0:
            raise RuntimeError(f"未能找到 \"{module_name}\" 模块")
        self.modules[module_name] = base
        return base

    def getBaseAddressWithCache(self, module_name: str) -> int:
        if module_name in self.modules:
            return self.modules[module_name]
        return self.getBaseAddress(module_name)

    def readPointer64(self, address: int) -> int:
        """直读 64 位指针，不使用缓存。"""
        return self.readUInt64(address)

    def readPointer32(self, address: int) -> int:
        """直读 32 位指针，不使用缓存。"""
        return self.readUInt32(address)

    def readPointer64WithCache(self, address: int) -> int:
        if address in self._pointer_cache:
            return self._pointer_cache[address]
        value = self.readPointer64(address)
        self._pointer_cache[address] = value
        return value

    def readPointer32WithCache(self, address: int) -> int:
        if address in self._pointer_cache:
            return self._pointer_cache[address]
        value = self.readPointer32(address)
        self._pointer_cache[address] = value
        return value

    def clear_pointer_cache(self) -> None:
        self._pointer_cache.clear()

    # ================= 表达式解析 =================

    def getAddrByExpression(
        self,
        expression: str,
        is64bit: bool = True,
        use_cache: bool = True,
    ) -> int:
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")

        if is64bit:
            read_call = "self.readPointer64WithCache" if use_cache else "self.readPointer64"
        else:
            read_call = "self.readPointer32WithCache" if use_cache else "self.readPointer32"
        base_call = "self.getBaseAddressWithCache" if use_cache else "self.getBaseAddress"

        pycode = expression.replace("[", read_call + "(")
        pycode = pycode.replace("]", ")")
        pycode = re.sub(
            r"([^\s<>\"'\[\]\(\)]+)\.(dll|exe)",
            base_call + r"('\1.\2')",
            pycode,
        )
        result = eval(pycode, {"self": self})
        return result

    def resolve_expression(
        self,
        expression: str,
        is64bit: bool = True,
        use_cache: bool = True,
    ) -> int:
        return self.getAddrByExpression(expression, is64bit, use_cache)

    # ================= 高层修改 =================

    def modify(
        self,
        address_expr,
        value_expr: str,
        data_type: DataType,
        is64bit: bool = True,
    ) -> int:
        """解析地址表达式并写入内存，成功时返回解析后的绝对地址。"""
        if isinstance(address_expr, str):
            address = self.resolve_expression(address_expr, is64bit=is64bit, use_cache=False)
        else:
            address = address_expr

        if data_type == DataType.STRING:
            value = value_expr
        else:
            value = eval(value_expr, {}, {})
        data = pack_value(value, data_type)

        if not self.write(address, data):
            raise RuntimeError("写入失败")
        return address

    # ================= 批量读取 =================

    def fetch(self, requests: Dict[Any, ReadRequest]) -> None:
        if not requests:
            return
        try:
            results = self._fetch_sync(requests)
            self.fetch_finished.emit(results)
        except Exception as e:
            self.fetch_error.emit(str(e))

    def _fetch_sync(self, requests: Dict[Any, ReadRequest]) -> Dict[Any, bytes]:
        if not requests:
            return {}

        req_list = list(requests.values())
        merged = self._merge_requests(req_list)

        range_data = {}
        for rng in merged:
            data, _ = self.dump(rng.start, rng.size, self._chunk_size)
            range_data[(rng.start, rng.end)] = data

        results = {}
        for req_id, req in requests.items():
            found = False
            for (start, end), data in range_data.items():
                if start <= req.address < end:
                    offset = req.address - start
                    chunk = data[offset:offset + req.size]
                    if len(chunk) < req.size:
                        chunk = chunk + b"\x00" * (req.size - len(chunk))
                    results[req_id] = chunk
                    found = True
                    break
            if not found:
                results[req_id] = b"\x00" * req.size
        return results

    def _merge_requests(self, requests: List[ReadRequest]) -> List[MergedRange]:
        if not requests:
            return []

        sorted_reqs = sorted(requests, key=lambda r: r.address)
        merged = []
        cur_start = sorted_reqs[0].address
        cur_end = cur_start + sorted_reqs[0].size

        for req in sorted_reqs[1:]:
            if req.address <= cur_end + self._merge_threshold:
                cur_end = max(cur_end, req.address + req.size)
            else:
                merged.append(MergedRange(cur_start, cur_end))
                cur_start = req.address
                cur_end = req.address + req.size

        merged.append(MergedRange(cur_start, cur_end))
        return merged