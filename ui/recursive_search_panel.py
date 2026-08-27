from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.memory_engine import MemoryEngine
from core.recursive_search import RecursiveMatch, RecursiveSearchEngine, RecursiveSearchParams
from ui.log_panel import LogLevel


def format_path(entry_address: int, offsets: List[int]) -> str:
    """把偏移链格式化成 CE 风格表达式，例如 [入口 + 0xB] + 0xC。"""
    expr = f"0x{entry_address:X}"
    for offset in offsets[:-1]:
        expr = f"[{expr} + 0x{offset:X}]"
    if offsets:
        expr = f"{expr} + 0x{offsets[-1]:X}"
    return expr


class RecursiveSearchWorker(QObject):
    log_signal = Signal(LogLevel, str)
    finished_signal = Signal(int, int)  # found_count, visited_count

    _MAX_LOG_MATCHES = 5000

    def __init__(self, engine: MemoryEngine, params: RecursiveSearchParams):
        super().__init__()
        self._engine = engine
        self._params = params
        self._stop = False

    def request_stop(self):
        self._stop = True

    @Slot()
    def run(self):
        params = self._params

        def read_func(address, size):
            if not self._engine.isAttached():
                return None
            data, ok = self._engine.dump(address, size, chunk_size=0x1000)
            return data if ok else None

        engine = RecursiveSearchEngine(read_func, should_stop=lambda: self._stop)

        mode = "全量搜索" if params.full_search else "找到首个即返回"
        self.log_signal.emit(
            LogLevel.INFO,
            f"递归搜索开始: 目标 0x{params.target:X}, 入口 0x{params.entry_address:X}, "
            f"大小 0x{params.block_size:X}, 范围 0x{params.addr_min:X}-0x{params.addr_max:X}, "
            f"最大深度 {params.max_depth}, 模式: {mode}",
        )

        def node_count(depth, count):
            self.log_signal.emit(LogLevel.DEBUG, f"深度 {depth + 1}: 节点数 {count} 个")

        def match_found(match):
            self.log_signal.emit(
                LogLevel.INFO,
                f"发现目标 (深度 {match.depth + 1}): {format_path(params.entry_address, match.offsets)}",
            )

        if params.full_search:
            matches = engine.search(params, on_node_count=node_count)
        else:
            matches = engine.search(params, on_node_count=node_count, on_match=match_found)

        if params.full_search:
            self.log_signal.emit(LogLevel.INFO, f"全量搜索完成: 找到 {len(matches)} 个")
            for match in matches[:self._MAX_LOG_MATCHES]:
                self.log_signal.emit(LogLevel.INFO, format_path(params.entry_address, match.offsets))
            if len(matches) > self._MAX_LOG_MATCHES:
                self.log_signal.emit(
                    LogLevel.WARNING,
                    f"结果过多，仅打印前 {self._MAX_LOG_MATCHES} 条",
                )
        else:
            self.log_signal.emit(
                LogLevel.INFO,
                f"递归搜索完成: 找到 {len(matches)} 个, 访问节点 {engine.visited_count} 个",
            )

        if self._stop:
            self.log_signal.emit(LogLevel.WARNING, "递归搜索已停止")

        self.finished_signal.emit(len(matches), engine.visited_count)


class RecursiveSearchPanel(QWidget):
    log_signal = Signal(LogLevel, str)

    def __init__(self, engine: MemoryEngine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._thread: Optional[QThread] = None
        self._worker: Optional[RecursiveSearchWorker] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        group = QGroupBox("递归搜索参数")
        group_layout = QVBoxLayout(group)

        self.target_edit = QLineEdit("0x0")
        self.entry_edit = QLineEdit("0x0")
        self.size_edit = QLineEdit("0x100")
        self.range_min_edit = QLineEdit("0x0")
        self.range_max_edit = QLineEdit("0x7FFFFFFFFFFFFFFF")
        self.depth_edit = QLineEdit("3")
        self.full_search_check = QCheckBox("全量搜索")
        self.start_btn = QPushButton("开始")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)

        fields = [
            ("目标值:", self.target_edit),
            ("入口地址:", self.entry_edit),
            ("大小:", self.size_edit),
            ("地址范围最小:", self.range_min_edit),
            ("地址范围最大:", self.range_max_edit),
            ("递归深度:", self.depth_edit),
        ]
        for label_text, edit in fields:
            field_layout = QVBoxLayout()
            field_layout.setSpacing(2)
            field_layout.addWidget(QLabel(label_text))
            field_layout.addWidget(edit)
            group_layout.addLayout(field_layout)

        group_layout.addWidget(self.full_search_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_btn)
        button_row.addWidget(self.stop_btn)
        button_row.addStretch()
        group_layout.addLayout(button_row)

        layout.addWidget(group)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("状态:"))
        self.status_label = QLabel("就绪")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        layout.addLayout(status_row)
        layout.addStretch()

        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)

    # ================= 公共接口 =================

    @staticmethod
    def _parse_int(text: str, name: str) -> int:
        value = text.strip()
        try:
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        except ValueError:
            raise ValueError(f"{name} 格式错误: {value}")

    def _on_start(self):
        if self._thread is not None and self._thread.isRunning():
            return

        try:
            params = RecursiveSearchParams(
                target=self._parse_int(self.target_edit.text(), "目标值"),
                entry_address=self._parse_int(self.entry_edit.text(), "入口地址"),
                block_size=self._parse_int(self.size_edit.text(), "大小"),
                addr_min=self._parse_int(self.range_min_edit.text(), "地址范围最小"),
                addr_max=self._parse_int(self.range_max_edit.text(), "地址范围最大"),
                max_depth=self._parse_int(self.depth_edit.text(), "递归深度"),
                full_search=self.full_search_check.isChecked(),
            )
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            self.log_signal.emit(LogLevel.ERROR, str(e))
            return

        if params.block_size <= 0:
            QMessageBox.warning(self, "参数错误", "大小必须大于 0")
            self.log_signal.emit(LogLevel.ERROR, "大小必须大于 0")
            return
        if params.addr_max < params.addr_min:
            QMessageBox.warning(self, "参数错误", "地址范围最大值不能小于最小值")
            self.log_signal.emit(LogLevel.ERROR, "地址范围最大值不能小于最小值")
            return
        if params.max_depth < 0:
            QMessageBox.warning(self, "参数错误", "递归深度不能为负数")
            self.log_signal.emit(LogLevel.ERROR, "递归深度不能为负数")
            return

        if not self._engine.isAttached():
            QMessageBox.warning(self, "错误", "尚未附加进程")
            self.log_signal.emit(LogLevel.WARNING, "尚未附加进程，无法递归搜索")
            return

        self.status_label.setText("搜索中...")
        self._start_worker(params)

    def _start_worker(self, params: RecursiveSearchParams):
        self._thread = QThread(self)
        self._worker = RecursiveSearchWorker(self._engine, params)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log_signal.connect(self.log_signal)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.finished_signal.connect(self._thread.quit)
        self._worker.finished_signal.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._thread.start()

    def _on_stop(self):
        if self._worker is not None:
            self._worker.request_stop()
        self.stop_btn.setEnabled(False)

    def _on_finished(self, found_count: int, visited_count: int):
        self.status_label.setText(f"完成: 找到 {found_count} 个, 访问节点 {visited_count} 个")

    def _on_thread_finished(self):
        self._thread = None
        self._worker = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)