"""HEX64 递归搜索：以入口内存为根，按地址范围展开子节点。"""
import struct
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class RecursiveSearchParams:
    target: int
    entry_address: int
    block_size: int
    addr_min: int
    addr_max: int
    max_depth: int
    full_search: bool


@dataclass
class RecursiveMatch:
    address: int
    depth: int
    offsets: List[int] = field(default_factory=list)  # 指针偏移链 + 命中偏移


class RecursiveSearchEngine:
    """BFS 递归扫描，read_func(address, size) -> bytes，失败返回 None。"""

    def __init__(
        self,
        read_func: Callable[[int, int], Optional[bytes]],
        should_stop: Optional[Callable[[], bool]] = None,
    ):
        self._read_func = read_func
        self._should_stop = should_stop or (lambda: False)
        self.visited_count = 0

    def search(
        self,
        params: RecursiveSearchParams,
        on_node_count: Optional[Callable[[int, int], None]] = None,
        on_match: Optional[Callable[[RecursiveMatch], None]] = None,
    ) -> List[RecursiveMatch]:
        matches: List[RecursiveMatch] = []
        visited = set()
        current = [(params.entry_address, [])]
        depth = 0

        while current and depth <= params.max_depth and not self._should_stop():
            if on_node_count is not None:
                on_node_count(depth, len(current))

            next_layer = []
            next_seen = set()

            for node_address, offsets in current:
                if self._should_stop():
                    break
                if node_address in visited:
                    continue
                visited.add(node_address)
                self.visited_count = len(visited)

                data = self._read_func(node_address, params.block_size)
                if not data:
                    continue

                for offset in range(0, len(data), 8):
                    if self._should_stop():
                        break
                    if offset + 8 > len(data):
                        break
                    value = struct.unpack_from("<Q", data, offset)[0]
                    found_address = node_address + offset

                    if value == params.target:
                        match = RecursiveMatch(found_address, depth, offsets + [offset])
                        matches.append(match)
                        if on_match is not None:
                            on_match(match)
                        if not params.full_search:
                            break

                    if (
                        depth < params.max_depth
                        and params.addr_min <= value <= params.addr_max
                        and value not in visited
                        and value not in next_seen
                    ):
                        next_seen.add(value)
                        next_layer.append((value, offsets + [offset]))

                if not params.full_search and matches:
                    break

            if not params.full_search and matches:
                break

            current = next_layer
            depth += 1

        return matches