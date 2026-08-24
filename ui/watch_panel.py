from __future__ import annotations

from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from common.types import DataType, parse_value_from_bytes
from ui.dialog import EditValueDialog, NameEditDialog, TypeSelectDialog, ExpressionEditDialog
from ui.log_panel import LogLevel


@dataclass
class WatchEntry:
    id: int
    name: str
    expression: str          # 实际存储：表达式字符串
    data_type: DataType
    value: Any = None
    resolved_address: Optional[int] = None  # 显示用：解析后的绝对地址


class _WatchTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[WatchEntry] = []

    def set_entries(self, entries: List[WatchEntry]):
        self.beginResetModel()
        self._entries = entries.copy()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 4  # 名字 | 地址 | 类型 | 值

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return entry.name
            elif col == 1:  # 地址列：显示解析后的地址
                if entry.resolved_address is not None:
                    return f"0x{entry.resolved_address:08X}"
                return "??"
            elif col == 2:
                return entry.data_type.value
            else:
                return self._format_value(entry.value)

        elif role == Qt.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None

    def _format_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.6f}"
        elif isinstance(value, str):
            return value
        else:
            return f"{value} (0x{value:X})"

    def headerData(self, section: int, orientation: int, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ["名字", "地址", "类型", "值"][section]

    def get_entry_at(self, row: int) -> Optional[WatchEntry]:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def get_entries(self) -> List[WatchEntry]:
        return self._entries.copy()

    def get_entry_by_id(self, entry_id: int) -> Optional[WatchEntry]:
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        return None

    def update_entry_value(self, entry_id: int, new_value: Any):
        for row, entry in enumerate(self._entries):
            if entry.id == entry_id:
                if entry.value != new_value:
                    entry.value = new_value
                    index = self.index(row, 3)
                    self.dataChanged.emit(index, index, [Qt.DisplayRole])
                return

    def update_entry_address(self, entry_id: int, new_address: Optional[int]):
        for row, entry in enumerate(self._entries):
            if entry.id == entry_id:
                if entry.resolved_address != new_address:
                    entry.resolved_address = new_address
                    index = self.index(row, 1)
                    self.dataChanged.emit(index, index, [Qt.DisplayRole])
                return


class WatchPanel(QWidget):
    modify_requested = Signal(str, str, DataType)  # expression, value_str, data_type
    log_signal = Signal(LogLevel, str)
    entry_added = Signal(int)
    entry_removed = Signal(int)
    context_menu_requested = Signal(QMenu, int, WatchEntry)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._next_id = 1
        self._model = _WatchTableModel(self)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        toolbar = QHBoxLayout()
        self.add_btn = QPushButton("添加观察项")
        self.add_btn.clicked.connect(self._on_add_clicked)
        self.clear_btn = QPushButton("清空所有")
        self.clear_btn.clicked.connect(self._on_clear_clicked)

        toolbar.addWidget(self.add_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.clear_btn)
        layout.addLayout(toolbar)

        self.table = QTableView(self)
        self.table.setModel(self._model)
        self.table.setFont(QFont("Consolas", 9))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._install_table_actions()

        layout.addWidget(self.table, 1)

        self.count_label = QLabel("观察项: 0 个")
        layout.addWidget(self.count_label)
        self._update_count()

    def _connect_signals(self):
        self.table.doubleClicked.connect(self._on_cell_double_clicked)

    def _install_table_actions(self):
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        shortcut = QShortcut(QKeySequence("Ctrl+A"), self.table)
        shortcut.setContext(Qt.WidgetShortcut)
        shortcut.activated.connect(self.table.selectAll)

    # ================= 公共接口 =================

    def add_entry(self, name: str, expression: str, data_type: DataType) -> int:
        entry_id = self._next_id
        self._next_id += 1

        entry = WatchEntry(
            id=entry_id,
            name=name,
            expression=expression,
            data_type=data_type,
            value=None,
            resolved_address=None
        )

        entries = self._model.get_entries()
        entries.append(entry)
        self._model.set_entries(entries)
        self._update_count()

        self.log_signal.emit(LogLevel.INFO, f"添加观察项: {name} = {expression} ({data_type.value})")
        self.entry_added.emit(entry_id)

        return entry_id

    def remove_entry(self, entry_id: int):
        entries = self._model.get_entries()
        removed = None
        for entry in entries:
            if entry.id == entry_id:
                removed = entry
                break
        if removed:
            entries.remove(removed)
            self._model.set_entries(entries)
            self._update_count()
            self.log_signal.emit(LogLevel.INFO, f"删除观察项: {removed.name}")
            self.entry_removed.emit(entry_id)

    def clear(self):
        count = len(self._model.get_entries())
        self._model.set_entries([])
        self._update_count()
        self.log_signal.emit(LogLevel.INFO, f"清空 {count} 个观察项")

    def get_entries(self) -> List[WatchEntry]:
        return self._model.get_entries()

    def get_entry_by_id(self, entry_id: int) -> Optional[WatchEntry]:
        return self._model.get_entry_by_id(entry_id)

    def update_values(self, results: Dict[str, bytes]):
        for entry in self._model.get_entries():
            key = f"watch_{entry.id}"
            if key in results:
                value = parse_value_from_bytes(results[key], entry.data_type)
                if value is not None:
                    self._model.update_entry_value(entry.id, value)

    def update_addresses(self, address_map: Dict[int, int]):
        """外部传入 {entry_id: resolved_address}"""
        if not address_map:
            return
        for entry_id, addr in address_map.items():
            self._model.update_entry_address(entry_id, addr)

    # ================= 内部 =================

    def _update_count(self):
        self.count_label.setText(f"观察项: {len(self._model.get_entries())} 个")

    def _show_table_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        entry = self._model.get_entry_at(row)
        if not entry:
            return

        menu = QMenu(self)

        self._duplicate_action = menu.addAction("复制此项")
        menu.addSeparator()
        self._delete_action = menu.addAction("删除此项")
        menu.addSeparator()
        self._copy_expr_action = menu.addAction("复制表达式")   # 复制底层表达式
        self._copy_addr_action = menu.addAction("复制地址")      # 复制解析后的地址
        self._copy_value_action = menu.addAction("复制值")

        self.context_menu_requested.emit(menu, row, entry)

        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == self._duplicate_action:
            self._duplicate_entry(entry)
        elif action == self._delete_action:
            self.remove_entry(entry.id)
        elif action == self._copy_expr_action:
            QApplication.clipboard().setText(entry.expression)
        elif action == self._copy_addr_action:
            if entry.resolved_address is not None:
                QApplication.clipboard().setText(f"0x{entry.resolved_address:08X}")
            else:
                QApplication.clipboard().setText("??")
        elif action == self._copy_value_action:
            if entry.value is not None:
                QApplication.clipboard().setText(str(entry.value))

    def _duplicate_entry(self, entry):
        new_name = f"{entry.name} (副本)"
        existing_names = [e.name for e in self._model.get_entries()]
        if new_name in existing_names:
            i = 1
            while f"{entry.name} (副本{i})" in existing_names:
                i += 1
            new_name = f"{entry.name} (副本{i})"

        self.add_entry(new_name, entry.expression, entry.data_type)
        self.log_signal.emit(LogLevel.INFO, f"复制观察项: {entry.name} → {new_name}")

    def _on_cell_double_clicked(self, index):
        if not index.isValid():
            return

        row, col = index.row(), index.column()
        entry = self._model.get_entry_at(row)
        if not entry:
            return

        if col == 0:  # 名字列
            dialog = NameEditDialog(entry.name, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                entry.name = dialog.get_new_name()
                self._model.set_entries(self._model.get_entries())
                self.log_signal.emit(LogLevel.DEBUG, f"重命名: {entry.name}")

        elif col == 1:  # 地址列：双击编辑表达式（因为底层存的是表达式）
            dialog = ExpressionEditDialog(entry.expression, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_expr = dialog.get_new_expression()
                if new_expr:
                    entry.expression = new_expr
                    entry.resolved_address = None  # 表达式变了，地址失效
                    entry.value = None
                    self._model.set_entries(self._model.get_entries())
                    self.log_signal.emit(LogLevel.DEBUG, f"表达式更新: {new_expr}")

        elif col == 2:  # 类型列
            dialog = TypeSelectDialog(entry.data_type, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_type = dialog.get_selected_type()
                if new_type != entry.data_type:
                    old_type = entry.data_type.value
                    entry.data_type = new_type
                    entry.value = None
                    self._model.set_entries(self._model.get_entries())
                    self.log_signal.emit(LogLevel.INFO, f"类型切换: {entry.name} {old_type} → {new_type.value}")

        elif col == 3:  # 值列
            current_value_str = self._model.data(index, Qt.DisplayRole)
            if current_value_str is None:
                current_value_str = ""
            dialog = EditValueDialog(current_value_str, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.modify_requested.emit(entry.expression, dialog.get_value(), entry.data_type)

    def _on_add_clicked(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("添加观察项")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel("名字:"))
        name_edit = QLineEdit()
        name_edit.setText("新观察项")
        layout.addWidget(name_edit)

        layout.addWidget(QLabel("表达式:"))
        expr_edit = QLineEdit()
        expr_edit.setText("0x1000")
        layout.addWidget(expr_edit)

        layout.addWidget(QLabel("类型:"))
        type_combo = QComboBox()
        for dt in DataType:
            type_combo.addItem(dt.value, dt)
        layout.addWidget(type_combo)

        buttons = QPushButton("确定")
        buttons.clicked.connect(dialog.accept)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = name_edit.text().strip() or "未命名"
            expression = expr_edit.text().strip()
            data_type = type_combo.currentData()

            if not expression:
                QMessageBox.warning(self, "错误", "表达式不能为空")
                return

            self.add_entry(name, expression, data_type)

    def _on_clear_clicked(self):
        entries = self._model.get_entries()
        if not entries:
            return
        reply = QMessageBox.question(
            self,
            "确认清空",
            f"确定要清空所有 {len(entries)} 个观察项吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.clear()

    def serialize(self) -> dict:
        return {
            "entries": [
                {
                    "name": entry.name,
                    "expression": entry.expression,
                    "data_type": entry.data_type.value,
                }
                for entry in self._model.get_entries()
            ]
        }

    def deserialize(self, data: dict):
        self.clear()
        if "entries" not in data:
            return
        for item in data["entries"]:
            data_type = DataType.from_string(item["data_type"])
            self.add_entry(item["name"], item["expression"], data_type)