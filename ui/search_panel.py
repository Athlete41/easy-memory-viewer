from __future__ import annotations

from typing import List, Optional, Dict

from PySide6.QtCore import Qt, QAbstractTableModel, QItemSelectionModel, QModelIndex, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
    QDialog
)

from common.types import DataType, parse_value_from_bytes
from core.search_engine import SearchEngine, SearchState, SearchResult
from ui.dialog import EditValueDialog
from ui.clipboard_utils import copy_selected_cells, copy_rows_from_selected_cells
from ui.log_panel import LogLevel

# 从 DataType 枚举生成类型列表
TYPE_ITEMS = [dt.value for dt in DataType]
ALIGN_OPTIONS = ["自动", "1", "2", "4", "8", "16"]

_DEFAULT_ALIGN = {
    DataType.BYTE.value: "1",
    DataType.INT16.value: "2",
    DataType.INT32.value: "4",
    DataType.INT64.value: "8",
    DataType.UINT16.value: "2",
    DataType.UINT32.value: "4",
    DataType.UINT64.value: "8",
    DataType.FLOAT.value: "4",
    DataType.DOUBLE.value: "8",
    DataType.STRING.value: "1",
    DataType.HEX32.value: "4",
    DataType.HEX64.value: "8",
}


# ================= 内部模型 =================
class _CandidateTableModel(QAbstractTableModel):
    """搜索结果表格模型 - 三列: 地址, 初始值, 当前值"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._initial_results: List[Optional[SearchResult]] = []
        self._current_results: List[Optional[SearchResult]] = []

    def set_initial_results(self, results: List[SearchResult]):
        """首次扫描：设置初始值和当前值"""
        self.beginResetModel()
        self._initial_results = results.copy()
        self._current_results = results.copy()
        self.endResetModel()

    def set_current_results(self, results: List[SearchResult]):
        """
        再次扫描：过滤掉不匹配的行
        只保留 results 中地址对应的行，初始值从旧 initial 中继承
        """
        if not results:
            self.clear()
            return

        kept_addresses = {r.address for r in results}

        # 过滤 initial_results，只保留匹配的地址
        filtered_initial = [
            r for r in self._initial_results
            if r is not None and r.address in kept_addresses
        ]

        self.beginResetModel()
        self._initial_results = filtered_initial
        self._current_results = results.copy()

        # 对齐长度
        while len(self._initial_results) < len(self._current_results):
            self._initial_results.append(None)
        while len(self._current_results) < len(self._initial_results):
            self._current_results.append(None)

        self.endResetModel()

    def _sync_row_count(self):
        row_count = max(len(self._initial_results), len(self._current_results))
        self.beginResetModel()
        while len(self._initial_results) < row_count:
            self._initial_results.append(None)
        while len(self._current_results) < row_count:
            self._current_results.append(None)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._current_results)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 3


    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row, column = index.row(), index.column()
        initial = self._initial_results[row] if row < len(self._initial_results) else None
        current = self._current_results[row] if row < len(self._current_results) else None

        if column == 0:
            result = current or initial
            return f"0x{result.address:08X}" if result else ""
        elif column == 1:
            return self._format_value(initial)
        else:
            return self._format_value(current)

    def _format_value(self, result: Optional[SearchResult]) -> str:
        if result is None:
            return ""
        value = result.value
        if isinstance(value, float):
            return f"{value:.6f}"
        if isinstance(value, str):
            return value
        if result.data_type in (DataType.BYTE, DataType.HEX32, DataType.HEX64):
            return f"0x{value:X}"
        return str(value)

    def headerData(self, section: int, orientation: int, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ["地址", "初始值", "当前值"][section]

    def offset_at(self, row: int) -> int:
        result = self._current_results[row] if row < len(self._current_results) else None
        if result is None:
            result = self._initial_results[row] if row < len(self._initial_results) else None
        return result.address if result else 0

    def clear(self):
        self.beginResetModel()
        self._initial_results.clear()
        self._current_results.clear()
        self.endResetModel()

    def get_current_results(self) -> List[SearchResult]:
        return [r for r in self._current_results if r is not None]

    def get_addresses(self) -> List[int]:
        return [r.address for r in self.get_current_results()]

    def get_result_at(self, row: int) -> Optional[SearchResult]:
        if row < len(self._current_results):
            return self._current_results[row]
        if row < len(self._initial_results):
            return self._initial_results[row]
        return None

    def update_current_value(self, row: int, new_value: Any):
        """只更新单行当前值"""
        if row < len(self._current_results):
            old = self._current_results[row]
            if old is not None and old.value != new_value:
                self._current_results[row] = SearchResult(old.address, new_value, old.data_type)
                index = self.index(row, 2)  # 第 2 列是当前值
                self.dataChanged.emit(index, index, [Qt.DisplayRole])


# ================= SearchPanel 主类 =================
class SearchPanel(QWidget):
    """
    搜索面板（自包含组件）。
    内部持有 SearchEngine，外部只需：
    1. set_search_data(data, base_address) 喂数据
    2. get_addresses() 取地址列表供调度器读取
    3. update_current_values(results) 更新当前值
    4. clear() 清空
    """

    modify_requested = Signal("long long", str, DataType)
    item_activated = Signal("long long", DataType, object)
    log_signal = Signal(LogLevel, str)
    next_scan_requested = Signal()
    context_menu_requested = Signal(QMenu, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = SearchEngine()
        self._current_data: Optional[bytes] = None
        self._base_address: int = 0
        self.refresh_before_next_scan = False

        self._model = _CandidateTableModel(self)

        self._build_ui()
        self._connect_signals()
        self._update_ui_state(SearchState.IDLE)

    # ================= 公共接口 =================

    def set_search_data(self, data: bytes, base_address: int):
        self._current_data = data
        self._base_address = base_address

    def get_addresses(self) -> List[int]:
        return self._model.get_addresses()

    def get_current_results(self) -> List[SearchResult]:
        return self._model.get_current_results()

    def get_selected_results(self) -> List[SearchResult]:
        rows = sorted({idx.row() for idx in self.candidate_view.selectionModel().selectedIndexes()})
        results = []
        for row in rows:
            result = self._model.get_result_at(row)
            if result is not None:
                results.append(result)
        return results

    def update_current_values(self, results: Dict[str, bytes]):
        current_results = self._model.get_current_results()
        if not current_results:
            return

        for i, result in enumerate(current_results):
            key = f"search_{result.address:X}"
            if key in results:
                value = parse_value_from_bytes(results[key], result.data_type)
                if value is not None and value != result.value:
                    self._model.update_current_value(i, value)

    def clear(self):
        self._engine.clear()
        self._model.clear()
        self._update_ui_state(SearchState.IDLE)
        self.count_label.setText("候选地址: 0 个")

    # ================= 内部 UI 更新 =================

    def _update_ui_state(self, state: SearchState):
        data_type = self._get_current_type()

        if state == SearchState.IDLE:
            ops = SearchEngine.get_first_ops(data_type)
            self.first_scan_btn.setEnabled(True)
            self.next_scan_btn.setEnabled(False)
            self.align_combo.setEnabled(True)
            self.clear_btn.setEnabled(False)
        else:
            ops = SearchEngine.get_next_ops(data_type)
            self.first_scan_btn.setEnabled(False)
            self.next_scan_btn.setEnabled(True)
            self.align_combo.setEnabled(False)
            self.clear_btn.setEnabled(True)

        self.op_combo.blockSignals(True)
        self.op_combo.clear()
        self.op_combo.addItems(ops)
        self.op_combo.setCurrentText(ops[0] if ops else "")
        self.op_combo.blockSignals(False)

        self._update_value_inputs(ops[0] if ops else "")

    def _get_current_type(self) -> DataType:
        return DataType.from_string(self.type_combo.currentText())

    # ================= 内部逻辑 =================

    def _do_first_scan(self):
        if self._current_data is None:
            self.log_signal.emit(LogLevel.WARNING, "没有数据可供搜索")
            return

        data_type = self._get_current_type()
        op = self.op_combo.currentText()
        value_str = self._get_current_value()
        align = self._get_current_align()

        if not value_str and op != "未知":
            self.log_signal.emit(LogLevel.WARNING, "请输入搜索值")
            return

        try:
            results = self._engine.initial_scan(
                self._current_data,
                value_str,
                data_type,
                op,
                align,
                self._base_address,
            )
            self._model.set_initial_results(results)
            self._model.set_current_results(results)
            self.count_label.setText(f"候选地址: {len(results)} 个")
            self._update_ui_state(SearchState.HAS_RESULTS)
            self.log_signal.emit(LogLevel.INFO, f"首次扫描完成，找到 {len(results)} 个结果")
        except Exception as e:
            self.log_signal.emit(LogLevel.ERROR, f"首次扫描失败: {e}")

    def _do_next_scan(self):
        """再次扫描：默认直接用当前数据；开启刷新模式时先请求外部刷新。"""
        if self.refresh_before_next_scan:
            self.next_scan_requested.emit()
            return
        self.continue_next_scan()

    def continue_next_scan(self):
        """数据刷新完成后执行再次扫描。"""
        if self._current_data is None:
            self.log_signal.emit(LogLevel.WARNING, "没有数据可供搜索")
            return

        data_type = self._get_current_type()
        op = self.op_combo.currentText()
        value_str = self._get_current_value()

        if not value_str and op not in ("增加", "减少", "变化", "不变"):
            self.log_signal.emit(LogLevel.WARNING, "请输入搜索值")
            return

        try:
            results = self._engine.next_scan(
                self._current_data,
                value_str,
                data_type,
                op,
                self._base_address,
            )
            self._model.set_current_results(results)  # 空列表自动清空
            self.count_label.setText(f"候选地址: {len(results)} 个")
            self.log_signal.emit(LogLevel.INFO, f"再次扫描完成，剩余 {len(results)} 个结果")
        except Exception as e:
            self.log_signal.emit(LogLevel.ERROR, f"再次扫描失败: {e}")
    def _do_clear(self):
        self.clear()
        self.log_signal.emit(LogLevel.INFO, "搜索已清空")

    def _get_current_value(self) -> str:
        op = self.op_combo.currentText()
        if op == "between":
            min_val = self.value_edit.text().strip()
            max_val = self.max_edit.text().strip()
            if not min_val or not max_val:
                return ""
            return f"{min_val}-{max_val}"
        return self.value_edit.text().strip()

    def _get_current_align(self) -> int:
        text = self.align_combo.currentText()
        if text == "自动":
            return int(_DEFAULT_ALIGN.get(self.type_combo.currentText(), "1"))
        return int(text)

    def _update_value_inputs(self, op: str):
        is_between = (op == "between")
        self.between_label.setVisible(is_between)
        self.max_edit.setVisible(is_between)
        if not is_between:
            self.value_edit.setEnabled(op not in ("增加", "减少", "变化", "不变", "未知"))
        else:
            self.value_edit.setEnabled(True)

    # ================= UI 构建 =================

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        form = QGroupBox("搜索条件", self)
        grid = QGridLayout(form)

        self.type_combo = QComboBox()
        self.type_combo.addItems(TYPE_ITEMS)

        self.op_combo = QComboBox()

        self.align_combo = QComboBox()
        self.align_combo.addItems(ALIGN_OPTIONS)
        self.align_combo.setCurrentText("自动")

        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("输入数值 (0x 前缀表示十六进制)")
        self.value_edit.setFixedWidth(150)

        self.between_label = QLabel("到")
        self.between_label.setVisible(False)

        self.max_edit = QLineEdit()
        self.max_edit.setPlaceholderText("最大值")
        self.max_edit.setFixedWidth(150)
        self.max_edit.setVisible(False)

        self.first_scan_btn = QPushButton("首次扫描")
        self.next_scan_btn = QPushButton("再次扫描")
        self.clear_btn = QPushButton("清空结果")
        self.clear_btn.setEnabled(False)

        self.count_label = QLabel("候选地址: 0 个")

        value_layout = QHBoxLayout()
        value_layout.setSpacing(5)
        value_layout.addWidget(QLabel("值:"))
        value_layout.addWidget(self.value_edit)
        value_layout.addWidget(self.between_label)
        value_layout.addWidget(self.max_edit)
        value_layout.addStretch()

        grid.addWidget(self.first_scan_btn, 1, 0)
        grid.addWidget(self.next_scan_btn, 1, 1)
        grid.addWidget(self.clear_btn, 1, 2)

        grid.addWidget(QLabel("数据类型:"), 2, 0)
        grid.addWidget(self.type_combo, 2, 1)
        grid.addWidget(QLabel("操作符:"), 2, 2)
        grid.addWidget(self.op_combo, 2, 3)

        grid.addLayout(value_layout, 3, 0, 1, 5)

        grid.addWidget(QLabel("对齐:"), 4, 0)
        grid.addWidget(self.align_combo, 4, 1)
        grid.addWidget(self.count_label, 5, 0, 1, 3)
        grid.setColumnStretch(4, 1)

        layout.addWidget(form)

        self.candidate_view = QTableView(self)
        self.candidate_view.setFont(QFont("Consolas", 9))
        self.candidate_view.setModel(self._model)
        self.candidate_view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.candidate_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.candidate_view.verticalHeader().setVisible(False)
        header = self.candidate_view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultSectionSize(120)
        header.resizeSection(0, 150)
        self.candidate_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._install_table_actions(self.candidate_view)

        layout.addWidget(self.candidate_view, 1)

    def _connect_signals(self):
        self.first_scan_btn.clicked.connect(self._do_first_scan)
        self.next_scan_btn.clicked.connect(self._do_next_scan)
        self.clear_btn.clicked.connect(self._do_clear)
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        self.op_combo.currentTextChanged.connect(self._on_op_changed)
        self.candidate_view.doubleClicked.connect(self._on_candidate_double_clicked)

    # ================= 表格操作（右键菜单） =================

    def _install_table_actions(self, view):
        view.setContextMenuPolicy(Qt.CustomContextMenu)
        view.customContextMenuRequested.connect(lambda pos: self._show_table_menu(view, pos))
        shortcut = QShortcut(QKeySequence("Ctrl+A"), view)
        shortcut.setContext(Qt.WidgetShortcut)
        copy_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), view)
        copy_shortcut.setContext(Qt.WidgetShortcut)
        copy_shortcut.activated.connect(lambda: copy_selected_cells(view))
        shortcut.activated.connect(view.selectAll)

    def _show_table_menu(self, view, pos):
        """显示右键菜单（支持外部扩展）"""
        index = view.indexAt(pos)
        if not index.isValid():
            return

        row, col = index.row(), index.column()
        result = self._model.get_result_at(row)
        if not result:
            return

        selection = view.selectionModel()
        if index not in selection.selectedIndexes():
            selection.clearSelection()
            selection.select(
                index,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )

        results = self.get_selected_results() or [result]

        menu = QMenu(self)

        self._add_builtin_menu_items(menu)
        self.context_menu_requested.emit(menu, result, results)
        action = menu.exec(view.viewport().mapToGlobal(pos))
        self._handle_menu_action(action, view, index, result)


    def _add_builtin_menu_items(self, menu):
        """内部默认菜单项"""
        self._copy_selected_action = menu.addAction("复制整行")
        self._modify_action = menu.addAction("修改值")


    def _handle_menu_action(self, action, view, index, result):
        """处理默认菜单项（外部插入的由外部自己处理）"""
        if action == self._copy_selected_action:
            copy_rows_from_selected_cells(view)
        elif action == self._modify_action:
            current_value_str = self._model.data(index, Qt.DisplayRole)
            if not current_value_str or current_value_str == "":
                return
            dialog = EditValueDialog(current_value_str, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_value_str = dialog.get_value()
                self.modify_requested.emit(result.address, new_value_str, result.data_type)


    # ================= 槽函数 =================

    def _on_type_changed(self, text: str):
        try:
            data_type = DataType.from_string(text)
            self.align_combo.blockSignals(True)
            self.align_combo.setCurrentText(_DEFAULT_ALIGN.get(text, "1"))
            self.align_combo.blockSignals(False)
            self.clear()
        except ValueError:
            pass

    def _on_op_changed(self, text: str):
        self._update_value_inputs(text)

    def _on_candidate_double_clicked(self, index):
        if not index.isValid():
            return
        row, col = index.row(), index.column()
        result = self._model.get_result_at(row)
        if not result:
            return

        if col == 2:  # 当前值列 -> 弹出修改对话框
            current_value_str = self._model.data(index, Qt.DisplayRole)
            if not current_value_str or current_value_str == "":
                return
            dialog = EditValueDialog(current_value_str, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_value_str = dialog.get_value()
                self.modify_requested.emit(result.address, new_value_str, result.data_type)
        elif col == 0:  # 地址列 -> 激活跳转
            self.item_activated.emit(result.address, result.data_type, result.value)
        # 其他列（初始值列）忽略

    def serialize(self) -> dict:
        """序列化搜索面板配置（仅 UI 配置，不保存列表）"""
        return {
            "data_type": self.type_combo.currentText(),
            "align": self.align_combo.currentText(),
        }

    def deserialize(self, data: dict):
        """反序列化搜索配置（只恢复配置，不清除搜索结果）"""
        if "data_type" in data:
            idx = self.type_combo.findText(data["data_type"])
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)

        if "align" in data:
            idx = self.align_combo.findText(data["align"])
            if idx >= 0:
                self.align_combo.setCurrentIndex(idx)