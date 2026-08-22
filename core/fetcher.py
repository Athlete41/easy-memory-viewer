from typing import List, Tuple, Dict, Any
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, Slot

from core.memory_tool import MemoryTool


@dataclass
class ReadRequest:
    """读取请求，带 id 用于路由"""
    id: Any  # 可以是 str, int, tuple 等，用于标识返回结果
    address: int
    size: int


@dataclass
class MergedRange:
    start: int
    end: int  # 不包含

    @property
    def size(self) -> int:
        return self.end - self.start


class Fetcher(QObject):
    """
    内存读取合并器：将多个读取请求合并成尽可能少的 IO 操作。
    使用 dump() 安全读取，支持 chunk_size 控制分块。
    
    用法：
        fetcher = Fetcher(memory_tool, threshold=0x100, chunk_size=0x1000)
        fetcher.finished.connect(on_result)
        fetcher.request({
            "view": ReadRequest("view", 0x1000, 0x100),
            "search_0x1080": ReadRequest("search_0x1080", 0x1080, 0x50),
        })
    """
    finished = Signal(dict)   # { id: bytes, ... }
    error = Signal(str)

    def __init__(self, memory_tool: MemoryTool, merge_threshold: int = 0x100, chunk_size: int = 0x1000):
        super().__init__()
        self._memory_tool = memory_tool
        self._threshold = merge_threshold
        self._chunk_size = chunk_size

    @Slot(dict)
    def request(self, requests: Dict[Any, ReadRequest]):
        """
        执行一组读取请求，完成后发出 finished 信号。
        requests: { id: ReadRequest, ... }
        """
        if not requests:
            return
        try:
            results = self._fetch_sync(requests)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _fetch_sync(self, requests: Dict[Any, ReadRequest]) -> Dict[Any, bytes]:
        if not requests:
            return {}

        # 1. 从字典提取请求列表用于合并
        req_list = list(requests.values())

        # 2. 合并请求
        merged = self._merge_requests(req_list)

        # 3. 用 dump 安全读取每个合并区间
        range_data: Dict[Tuple[int, int], bytes] = {}
        for rng in merged:
            data, _ = self._memory_tool.dump(rng.start, rng.size, self._chunk_size)
            range_data[(rng.start, rng.end)] = data

        # 4. 按 id 切分结果
        results = {}
        for req_id, req in requests.items():
            found = False
            for (start, end), data in range_data.items():
                if start <= req.address < end:
                    offset = req.address - start
                    chunk = data[offset:offset + req.size]
                    if len(chunk) < req.size:
                        chunk = chunk + b'\x00' * (req.size - len(chunk))
                    results[req_id] = chunk
                    found = True
                    break
            if not found:
                results[req_id] = b'\x00' * req.size

        return results

    def _merge_requests(self, requests: List[ReadRequest]) -> List[MergedRange]:
        if not requests:
            return []

        sorted_reqs = sorted(requests, key=lambda r: r.address)
        merged = []
        cur_start = sorted_reqs[0].address
        cur_end = cur_start + sorted_reqs[0].size

        for req in sorted_reqs[1:]:
            if req.address <= cur_end + self._threshold:
                cur_end = max(cur_end, req.address + req.size)
            else:
                merged.append(MergedRange(cur_start, cur_end))
                cur_start = req.address
                cur_end = req.address + req.size

        merged.append(MergedRange(cur_start, cur_end))
        return merged