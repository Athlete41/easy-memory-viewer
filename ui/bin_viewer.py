import struct
from typing import List, Tuple, Set, Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QComboBox, QPushButton,
    QHeaderView, QDialog, QMessageBox, QMenu, QApplication
)
from PySide6.QtCore import Qt, QTimer, QItemSelectionModel, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut


# ================= 格式配置 =================
from common.types import FormatConfig, DataType, Endian, Encoding
from ui.dialog import EditValueDialog
from ui.clipboard_utils import copy_selected_cells

WIDTH_MAP: Dict[DataType, int] = {
    DataType.BYTE: (50, 25),
    DataType.INT16: (70, 70),
    DataType.INT32: (90, 90),
    DataType.INT64: (110, 110),
    DataType.FLOAT: (100, 100),
    DataType.DOUBLE: (120, 120),
    DataType.STRING: (200, 200),
    DataType.HEX32: (100, 100),
    DataType.HEX64: (150, 150),
}

# ================= BinViewer 主控件 =================
class BinViewer(QWidget):
    modify_requested = Signal("long long", str, DataType)
    context_menu_requested = Signal(QMenu, int, int, "long long", object, DataType)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: bytes = b''
        self._prev_data: bytes = b''
        self._base_address = 0
        self._row_byte_size = 16
        self._format_groups: List[FormatConfig] = []
        self._group_column_ranges: List[Tuple[int, int]] = []
        self._column_to_group: Dict[int, int] = {}
        self._group_combos: List[Dict[str, QComboBox]] = []

        # 高亮状态：存储每个单元格的透明度 (0-255)
        self._cell_alpha: Dict[Tuple[int, int], int] = {}
        self._changed_cells: Set[Tuple[int, int]] = set()

        # 淡出定时器
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_highlight)
        self._fade_timer.setInterval(150)

        self._setup_ui()
        self._connect_signals()

        # 默认两个格式组
        self.add_format_group(FormatConfig(DataType.BYTE, Endian.LITTLE))
        self.add_format_group(FormatConfig(DataType.INT32, Endian.LITTLE))

        self._relative_mode = False
        self._relative_row = 0
        # 注册快捷键 Ctrl+Enter
        self._toggle_relative_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._toggle_relative_shortcut.activated.connect(self._toggle_relative_mode)

    def _toggle_relative_mode(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            return
        self._relative_mode = not self._relative_mode
        if self._relative_mode:
            self._relative_row = current_row
        self._refresh_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        tool_bar = QHBoxLayout()
        self.add_btn = QPushButton("添加格式组")
        self.remove_btn = QPushButton("移除最后格式组")
        tool_bar.addWidget(self.add_btn)
        tool_bar.addWidget(self.remove_btn)
        tool_bar.addStretch()
        layout.addLayout(tool_bar)

        self.format_row = QWidget()
        self.format_layout = QVBoxLayout(self.format_row)
        self.format_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.format_row)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        layout.addWidget(self.table)

    def _connect_signals(self):
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._copy_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.table)
        self._copy_shortcut.setContext(Qt.WidgetShortcut)
        self._copy_shortcut.activated.connect(self._copy_selection)
        self.add_btn.clicked.connect(self._on_add_format)
        self.remove_btn.clicked.connect(self._on_remove_format)

    def _copy_selection(self):
        copy_selected_cells(self.table)

    def _on_add_format(self):
        self.add_format_group(FormatConfig(DataType.INT32, Endian.LITTLE, encoding='utf-8'))

    def _on_remove_format(self):
        if len(self._format_groups) <= 1:
            QMessageBox.information(self, "提示", "至少保留一个格式组")
            return
        self.remove_last_format_group()

    # ================= 公共接口 =================
    def set_base_address(self, addr: int):
        self._base_address = addr
        self._refresh_table()

    def set_data(self, data: bytes):
        """设置新数据，检测变化，叠加高亮"""
        self._prev_data = self._data
        self._data = data

        new_cells = set()
        if self._prev_data is not None:
            min_len = min(len(self._prev_data), len(data))
            for i in range(min_len):
                if self._prev_data[i] != data[i]:
                    row = i // 16
                    for g_idx, fmt in enumerate(self._format_groups):
                        byte_width = fmt.get_size()
                        offset_in_row = i % 16
                        col_in_group = offset_in_row // byte_width
                        start_col, _ = self._group_column_ranges[g_idx]
                        col = start_col + col_in_group
                        new_cells.add((row, col))
            for i in range(min_len, len(data)):
                row = i // 16
                for g_idx, fmt in enumerate(self._format_groups):
                    byte_width = fmt.get_size()
                    offset_in_row = i % 16
                    col_in_group = offset_in_row // byte_width
                    start_col, _ = self._group_column_ranges[g_idx]
                    col = start_col + col_in_group
                    new_cells.add((row, col))

        if new_cells:
            # 追加新变化单元格，透明度设为255（全红）
            self._changed_cells.update(new_cells)
            for cell in new_cells:
                self._cell_alpha[cell] = 255

        # 刷新表格（保留高亮状态）
        self._refresh_table()

        # 如果有变化且定时器未运行，启动淡出
        if self._changed_cells and not self._fade_timer.isActive():
            self._fade_timer.start()

    def get_data(self) -> bytes:
        return self._data

    def add_format_group(self, fmt: FormatConfig):
        self._format_groups.append(fmt)
        # 列结构变化（新增列），旧坐标可能有效，但为了安全，我们保留高亮，因为新增列在右侧，不影响旧列索引
        self._rebuild_ui()
        self._refresh_table()

    def remove_last_format_group(self):
        if len(self._format_groups) <= 1:
            return
        self._format_groups.pop()
        # 列结构变化，清空高亮状态
        self._clear_highlight()
        self._rebuild_ui()
        self._refresh_table()

    def _clear_highlight(self):
        """清空所有高亮状态"""
        self._changed_cells.clear()
        self._cell_alpha.clear()
        if self._fade_timer.isActive():
            self._fade_timer.stop()

    # ================= UI 重建 =================
    def _clear_layout(self, layout):
        """递归清空布局及其所有子控件"""
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self._clear_layout(child.layout())

    def _rebuild_ui(self):
        # 清理旧布局（递归删除所有子控件和子布局）
        self._clear_layout(self.format_layout)
        self._group_combos.clear()

        for idx, fmt in enumerate(self._format_groups):
            group_layout = QHBoxLayout()
            group_layout.setContentsMargins(0, 0, 10, 0)

            # 数据类型下拉框
            dataTypeCombo = QComboBox()
            for dt in DataType:
                dataTypeCombo.addItem(dt.value, dt)
            dataTypeCombo.setCurrentIndex(dataTypeCombo.findData(fmt.data_type))
            dataTypeCombo.currentIndexChanged.connect(
                lambda _, group_idx=idx: self._on_group_format_changed(group_idx)
            )

            # 字节序下拉框
            endianCombo = QComboBox()
            for e in Endian:
                endianCombo.addItem(e.value, e)
            endianCombo.setCurrentIndex(endianCombo.findData(fmt.endian))
            endianCombo.currentIndexChanged.connect(
                lambda _, group_idx=idx: self._on_group_format_changed(group_idx)
            )
            # TODO: 字节序下拉框默认隐藏
            endianCombo.setVisible(False)

            # 编码下拉框
            encodingCombo = QComboBox()
            for e in Encoding:
                encodingCombo.addItem(e.value, e.value)
            encodingCombo.setCurrentIndex(encodingCombo.findData(fmt.encoding))
            encodingCombo.currentIndexChanged.connect(
                lambda _, group_idx=idx: self._on_group_format_changed(group_idx)
            )

            group_layout.addWidget(dataTypeCombo)
            group_layout.addWidget(endianCombo)
            group_layout.addWidget(encodingCombo)

            self.format_layout.addLayout(group_layout)

            self._group_combos.append({
                "dataType": dataTypeCombo,
                "endian": endianCombo,
                "encoding": encodingCombo
            })


        # 计算列布局（以下保持不变）
        total_cols = 1
        self._group_column_ranges.clear()
        self._column_to_group.clear()
        current_col = 1
        for g_idx, fmt in enumerate(self._format_groups):
            col_count = 16 // fmt.get_size()
            start = current_col
            end = current_col + col_count - 1
            self._group_column_ranges.append((start, end))
            for col in range(start, end + 1):
                self._column_to_group[col] = g_idx
            current_col = end + 1
        self.table.setColumnCount(current_col)

        # 设置列标题（带分组名）
        self.table.setHorizontalHeaderItem(0, QTableWidgetItem("地址"))
        colors = [QColor(200, 230, 255), QColor(255, 230, 200),
                QColor(230, 255, 200), QColor(255, 200, 230)]
        for g_idx, fmt in enumerate(self._format_groups):
            start, end = self._group_column_ranges[g_idx]
            byte_width = fmt.get_size()
            group_name = fmt.data_type.value
            for col in range(start, end + 1):
                if col == start:
                    header_text = f"[{group_name}]"
                else:
                    offset = (col - start) * byte_width
                    header_text = f"+{offset:X}"
                item = QTableWidgetItem(header_text)
                color = colors[g_idx % len(colors)]
                item.setBackground(QBrush(color))
                self.table.setHorizontalHeaderItem(col, item)

        # 设置列宽
        self.table.setColumnWidth(0, 150)
        for g_idx, fmt in enumerate(self._format_groups):
            start, end = self._group_column_ranges[g_idx]
            headWidth, width = WIDTH_MAP.get(fmt.data_type, 80)
            for col in range(start, end + 1):
                if col == start:
                    self.table.setColumnWidth(col, headWidth)
                else:
                    self.table.setColumnWidth(col, width)

    def _on_group_format_changed(self, group_idx: int):
        combos = self._group_combos[group_idx]
        data_type_combo, endian_combo, encoding_combo = combos["dataType"], combos["endian"], combos["encoding"]

        data_type = data_type_combo.currentData()
        endian = endian_combo.currentData()
        encoding = encoding_combo.currentData()
        
        old_fmt = self._format_groups[group_idx]
        new_fmt = FormatConfig(data_type, endian, old_fmt.str_len, encoding)
        self._format_groups[group_idx] = new_fmt
        # 格式变化可能改变列数，清空高亮
        self._clear_highlight()
        self._rebuild_ui()
        self._refresh_table()

    # ================= 数据渲染 =================
    def _refresh_table(self):
        data = self._data
        if not data:
            data = b''
        if len(data) % 16 != 0:
            padded = data + b'\x00' * (16 - len(data) % 16)
        else:
            padded = data

        total_rows = len(padded) // 16
        self.table.setRowCount(total_rows)

        # 地址列
        for row in range(total_rows):
            if self._relative_mode:
                offset = (row - self._relative_row) * 16
                if offset >= 0:
                    addr_text = f"+0x{offset:X}"
                else:
                    addr_text = f"-0x{-offset:X}"
            else:
                addr = self._base_address + row * 16
                addr_text = f"0x{addr:08X}"
            item = QTableWidgetItem(addr_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 0, item)

        # 数据列
        for g_idx, fmt in enumerate(self._format_groups):
            byte_width = fmt.get_size()
            start, end = self._group_column_ranges[g_idx]
            for col in range(start, end + 1):
                offset_in_group = (col - start) * byte_width
                for row in range(total_rows):
                    cell_offset = row * 16 + offset_in_group
                    if cell_offset + byte_width > len(padded):
                        value = ""
                    else:
                        chunk = padded[cell_offset:cell_offset+byte_width]
                        value = FormatConfig.format_value(chunk, fmt)
                    item = QTableWidgetItem(value)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, col, item)

        # 应用高亮（根据存储的透明度）
        self._apply_highlight()

    # ================= 高亮管理 =================
    def _apply_highlight(self):
        """根据 _cell_alpha 字典设置每个单元格的背景"""
        # 先清除所有背景
        for row in range(self.table.rowCount()):
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(QBrush())

        # 对每个变化的单元格设置背景
        for (row, col), alpha in self._cell_alpha.items():
            if alpha <= 0:
                continue
            item = self.table.item(row, col)
            if item:
                item.setBackground(QBrush(QColor(255, 50, 50, alpha)))

    def _fade_highlight(self):
        """定时器事件：逐步降低所有变化单元格的透明度"""
        if not self._changed_cells:
            self._fade_timer.stop()
            return

        cells_to_remove = []
        for cell in list(self._changed_cells):
            alpha = self._cell_alpha.get(cell, 255)
            if alpha > 0:
                new_alpha = max(0, alpha - 25)   # 每步减少25，共10步消失（150ms*10=1.5s）
                self._cell_alpha[cell] = new_alpha
                if new_alpha == 0:
                    cells_to_remove.append(cell)
            else:
                cells_to_remove.append(cell)

        # 移除透明度为0的单元格
        for cell in cells_to_remove:
            self._changed_cells.discard(cell)
            self._cell_alpha.pop(cell, None)

        # 刷新背景（只更新背景，不重建整个表格）
        self._apply_highlight()

        # 如果所有变化消失，停止定时器
        if not self._changed_cells:
            self._fade_timer.stop()

    # ================= 双击编辑 =================
    def _on_cell_double_clicked(self, row: int, col: int):
        if col == 0:
            self._toggle_relative_mode()
            return
        group_idx = self._column_to_group.get(col)
        if group_idx is None:
            return
        fmt = self._format_groups[group_idx]
        item = self.table.item(row, col)
        if not item:
            return
        current_text = item.text()
        if current_text == "??" or current_text == "":
            return
        start_col, _ = self._group_column_ranges[group_idx]
        byte_width = fmt.get_size()
        offset = row * 16 + (col - start_col) * byte_width
        address = self._base_address + offset

        dialog = EditValueDialog(current_text, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_value_str = dialog.get_value()
            self.modify_requested.emit(address, new_value_str, fmt.data_type)


    def _on_context_menu(self, pos):
        """右键触发 → 收集信息 → 发出信号"""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return

        row, col = index.row(), index.column()

        selection = self.table.selectionModel()
        if index not in selection.selectedIndexes():
            selection.clearSelection()
            selection.select(
                index,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.SelectCurrent,
            )

        # 1. 计算地址
        group_idx = self._column_to_group.get(col)
        if group_idx is None:
            return

        fmt = self._format_groups[group_idx]
        start_col, _ = self._group_column_ranges[group_idx]
        byte_width = fmt.get_size()
        offset = row * 16 + (col - start_col) * byte_width
        address = self._base_address + offset

        # 2. 获取当前值
        item = self.table.item(row, col)
        value_text = item.text() if item else ""
        # 注意：这里 value_text 是显示字符串，如需原生值可以额外解析
        # 简化：把当前显示文本传出去，外界自行解析
        menu = QMenu(self)

        self._add_builtin_menu_items(menu)

        self.context_menu_requested.emit(
            menu,
            row,
            col,
            address,
            value_text,
            fmt.data_type
        )

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        self._handle_menu_action(action, address, value_text, fmt.data_type)


    def _add_builtin_menu_items(self, menu):
        """内部默认菜单项"""
        self._modify_action = menu.addAction("修改值...")
        self._copy_addr_action = menu.addAction("复制地址")
        self._copy_value_action = menu.addAction("复制值")

    def get_selected_entries(self):
        """返回选中数据单元格对应的 (address, value_text, data_type) 列表。"""
        entries = []
        indexes = sorted(
            self.table.selectionModel().selectedIndexes(),
            key=lambda idx: (idx.row(), idx.column()),
        )
        for index in indexes:
            col = index.column()
            if col == 0:
                continue
            group_idx = self._column_to_group.get(col)
            if group_idx is None:
                continue
            fmt = self._format_groups[group_idx]
            start_col, _ = self._group_column_ranges[group_idx]
            byte_width = fmt.get_size()
            offset = index.row() * 16 + (col - start_col) * byte_width
            address = self._base_address + offset
            item = self.table.item(index.row(), col)
            value_text = item.text() if item else ""
            entries.append((address, value_text, fmt.data_type))
        return entries

    def _handle_menu_action(self, action, address, value, data_type):
        """处理默认菜单项（外部插入的由外部自己处理）"""
        if action == self._modify_action:
            # 发出修改信号
            dialog = EditValueDialog(str(value), self)
            if dialog.exec():
                self.modify_requested.emit(address, dialog.get_value(), data_type)
        elif action == self._copy_addr_action:
            QApplication.clipboard().setText(f"0x{address:08X}")
        elif action == self._copy_value_action:
            QApplication.clipboard().setText(str(value))
