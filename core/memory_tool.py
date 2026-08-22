from PySide6.QtCore import Signal, QObject


class MemoryTool(QObject):
    attachStatusChanged = Signal(bool)

    def __init__(self, process_name: str = "") -> None:
        super().__init__()
        self.process_name = process_name

    def setProcessName(self, process_name: str) -> None:
        self.process_name = process_name

    def isAttached(self) -> bool:
        """判断是否已附加。"""
        raise NotImplementedError("isAttached() 方法未实现")

    def attach(self) -> None:
        """获取进程 PID 和模块基址。"""
        raise NotImplementedError("attach() 方法未实现")

    def read(self, address: int, size: int) -> tuple[bytes, bool]:
        """读取内存。"""
        raise NotImplementedError("read() 方法未实现")

    def getBaseAddress(self, module_name: str) -> int:
        """获取模块基址。"""
        raise NotImplementedError("getBaseAddress() 方法未实现")

    def readUInt8(self, address: int) -> int:
        """读取无符号 8 位整数。"""
        raise NotImplementedError("readUInt8() 方法未实现")

    def readUInt16(self, address: int) -> int:
        """读取无符号 16 位整数。"""
        raise NotImplementedError("readUInt16() 方法未实现")

    def readUInt32(self, address: int) -> int:
        """读取无符号 32 位整数。"""
        raise NotImplementedError("readUInt32() 方法未实现")

    def readUInt64(self, address: int) -> int:
        """读取无符号 64 位整数。"""
        raise NotImplementedError("readUInt64() 方法未实现")

    def readInt32(self, address: int) -> int:
        """读取有符号 32 位整数。"""
        raise NotImplementedError("readInt32() 方法未实现")

    def readFloat(self, address: int) -> float:
        """读取单精度浮点数。"""
        raise NotImplementedError("readFloat() 方法未实现")

    def readDouble(self, address: int) -> float:
        """读取双精度浮点数。"""
        raise NotImplementedError("readDouble() 方法未实现")

    def readString(self, address: int, size: int = 100, decode: str = "utf-8") -> str:
        """读取字符串。"""
        raise NotImplementedError("readString() 方法未实现")

    def dump(self, address: int, size: int, chunk_size: int = 0x100) -> tuple[bytes, bool]:
        """用驱动的循环读取整段内存。"""
        raise NotImplementedError("dump() 方法未实现")
    
    def dumpCenter(self, address: int, size: int, chunk_size: int = 0x100) -> tuple[bytes, bool]:
        """以 address 为中心，读取 [address - size, address + size] 范围内的内存。"""
        raise NotImplementedError("dumpCenter() 方法未实现")

    def write(self, address: int, data: bytes) -> bool:
        """写入目标进程内存"""
        raise NotImplementedError("write() 方法未实现")

    def close(self) -> None:
        """关闭目标进程连接。"""
        raise NotImplementedError("close() 方法未实现")

    def getAddrByExpression(self, expression: str, is64bit: bool = True) -> int:
        """根据表达式获取地址。"""
        raise NotImplementedError("getAddrByExpression() 方法未实现")

    def attachedStatusGuard(self) -> None:
        """检查附加状态， 若进程已死亡则自动关闭连接"""
        raise NotImplementedError("attachedStatusGuard() 方法未实现")


import re
import struct
import ctypes
import core.cracker_client as ct



class CrackerMemTool(MemoryTool):
    def __init__(self, process_name: str = "") -> None:
        super().__init__(process_name)
        self.pid = 0
        self.modules: dict[str, int] = {}
        self._handle = None

    def isAttached(self) -> bool:
        """判断是否已附加。"""
        return self._handle is not None and self.pid != 0

    def attach(self) -> None:
        """打开驱动，获取进程 PID 和模块基址。"""

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


    def read(self, address: int, size: int) -> tuple[bytes, bool]:
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")
        
        buffer = ctypes.create_string_buffer(size)
        status, _ = ct.readWriteMemoryMdl(self._handle, self.pid, address, size, ctypes.addressof(buffer), ct.READ_FLAG)

        if status != 0:
            return b"\x00" * size, False
        return buffer.raw[:size], True

    def getBaseAddress(self, module_name: str) -> int:
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()") 
        
        if module_name in self.modules:
            return self.modules[module_name]
        else:
            status, base = ct.getModuleBase(self._handle, self.pid, module_name)
            if status != 0 or base == 0:
                raise RuntimeError(f"未能找到 \"{module_name}\" 模块") 

            self.modules[module_name] = base
            return base

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
        """读取字符串。"""
        buffer = self.read(address, size)[0]
        end = buffer.find(b"\x00")
        if end != -1:
            buffer = buffer[:end]
        return buffer.decode(decode, errors="ignore")

    def dump(self, address: int, size: int, chunk_size: int = 0x100) -> tuple[bytes, bool]:
        """用驱动的循环读取整段内存。"""
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")

        return ct.dumpMemory(self._handle, self.pid, address, size, chunk_size)
    
    def dumpCenter(self, address: int, size: int, chunk_size: int = 0x100) -> tuple[bytes, bool]:
        """
        以 address 为中心，读取 [address - size, address + size] 范围内的内存。
        若 address - size < 0，起始地址截断为 0。
        内部使用 dumpMemory 循环读取，失败块自动填 0。
        """
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")

        start = max(0, address - size)
        end = address + size
        total = end - start
        if total <= 0:
            return b''

        return ct.dumpMemory(self._handle, self.pid, start, total, chunk_size)


    def write(self, address: int, data: bytes) -> bool:
        """写入目标进程内存"""
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")
        size = len(data)
        buffer = ctypes.create_string_buffer(data, size + 1)
        status, _ = ct.readWriteMemoryMdl(self._handle, self.pid, address, size, ctypes.addressof(buffer), ct.WRITE_FLAG)
        return status == 0

    def close(self) -> None:
        if self._handle is not None:
            ct.closeDevice(self._handle)
            self._handle = None
 
        self.pid = 0
        self.modules.clear()
        self.attachStatusChanged.emit(False)

    def getAddrByExpression(self, expression: str, is64bit: bool = True) -> int:
        if not self.isAttached():
            raise RuntimeError("尚未连接进程，请先调用 attach()")

        pycode = expression.replace("[", "self.readUInt64(" if is64bit else "self.readUInt32(")
        pycode = pycode.replace("]", ")")
        pycode = re.sub(r"([^\s<>\"'\[\]\(\)]+)\.(dll|exe)", r"self.getBaseAddress('\1.\2')", pycode)

        result = eval(pycode, {"self": self})
        return result

    def attachedStatusGuard(self) -> None:
        """检查附加状态， 若进程已死亡则自动关闭连接"""
        if not self.isAttached():
            return

        _, pid = ct.getPidByName(self._handle, self.process_name)
        if pid == 0:
            self.close()
            return

