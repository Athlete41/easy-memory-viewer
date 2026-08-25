from __future__ import annotations

import json

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QAbstractItemModel, QItemSelectionModel, QModelIndex, QMimeData, Signal
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
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from common.expression import compose_expression
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
    children: List["WatchEntry"] = field(default_factory=list)
    parent: Optional["WatchEntry"] = None   # 运行时指针，不参与序列化


class _WatchTreeModel(QAbstractItemModel):
    """支持父子结构的观察区树模型。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roots: List[WatchEntry] = []
        self._by_id: Dict[int, WatchEntry] = {}

    # ================= Qt Model API =================

    def rowCount(self, parent=QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._roots)
        entry = parent.internalPointer()
        return len(entry.children)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 4  # 名字 | 地址 | 类型 | 值

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            entry = self._roots[row]
        else:
            entry = parent.internalPointer().children[row]
        return self.createIndex(row, column, entry)

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        entry = index.internalPointer()
        if entry.parent is None:
            return QModelIndex()
        return self.index_for_entry(entry.parent, 0)

    def hasChildren(self, parent=QModelIndex()) -> bool:
        if not parent.isValid():
            return len(self._roots) > 0
        return len(parent.internalPointer().children) > 0

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        return (
            Qt.ItemIsEnabled
            | Qt.ItemIsSelectable
            | Qt.ItemIsDragEnabled
            | Qt.ItemIsDropEnabled
        )

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = index.internalPointer()
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
                return self._format_value(entry.value, entry.data_type)

        elif role == Qt.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None

    @staticmethod
    def _format_value(value: Any, data_type: DataType) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.6f}"
        if isinstance(value, str):
            return value
        if data_type in (DataType.BYTE, DataType.HEX32, DataType.HEX64):
            return f"0x{value:X}"
        return str(value)

    def headerData(self, section: int, orientation: int, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ["名字", "地址", "类型", "值"][section]

    # ================= 数据访问 =================

    def entry_at(self, index: QModelIndex) -> Optional[WatchEntry]:
        return index.internalPointer() if index.isValid() else None

    def index_for_entry(self, entry: WatchEntry, column: int = 0) -> QModelIndex:
        if entry.parent is None:
            row = self._roots.index(entry)
            return self.createIndex(row, column, entry)
        parent_index = self.index_for_entry(entry.parent, 0)
        row = entry.parent.children.index(entry)
        return self.createIndex(row, column, entry)

    def get_roots(self) -> List[WatchEntry]:
        return self._roots

    def get_entries(self) -> List[WatchEntry]:
        return self._flatten(self._roots)

    def _flatten(self, entries: List[WatchEntry]) -> List[WatchEntry]:
        result = []
        for entry in entries:
            result.append(entry)
            result.extend(self._flatten(entry.children))
        return result

    def get_entry_by_id(self, entry_id: int) -> Optional[WatchEntry]:
        return self._by_id.get(entry_id)

    # ================= 结构操作 =================

    def insert_entry(
        self,
        entry: WatchEntry,
        parent: Optional[WatchEntry] = None,
        row: Optional[int] = None,
    ) -> WatchEntry:
        entry.parent = parent
        if parent is None:
            if row is None:
                row = len(self._roots)
            self.beginInsertRows(QModelIndex(), row, row)
            self._roots.insert(row, entry)
            self.endInsertRows()
        else:
            if row is None:
                row = len(parent.children)
            parent_index = self.index_for_entry(parent, 0)
            self.beginInsertRows(parent_index, row, row)
            parent.children.insert(row, entry)
            self.endInsertRows()
        self._register_entry(entry)
        return entry

    def remove_entry(self, entry: WatchEntry) -> bool:
        self._unregister_entry(entry)
        if entry.parent is None:
            row = self._roots.index(entry)
            self.beginRemoveRows(QModelIndex(), row, row)
            self._roots.pop(row)
            self.endRemoveRows()
            return True
        parent = entry.parent
        row = parent.children.index(entry)
        parent_index = self.index_for_entry(parent, 0)
        self.beginRemoveRows(parent_index, row, row)
        parent.children.pop(row)
        self.endRemoveRows()
        return True

    def clear(self):
        self.beginResetModel()
        self._roots.clear()
        self._by_id.clear()
        self.endResetModel()

    def set_entries(self, entries: List[WatchEntry]):
        self.beginResetModel()
        self._roots = entries.copy()
        self._by_id.clear()
        for entry in self._roots:
            entry.parent = None
            self._register_entry(entry)
        self.endResetModel()

    # ================= 拖拽 =================

    _MIME_TYPE = "application/x-easy-memory-watch-entry-ids"

    def mimeTypes(self) -> List[str]:
        return [self._MIME_TYPE]

    def mimeData(self, indexes) -> QMimeData:
        mime = QMimeData()
        entries = [
            idx.internalPointer()
            for idx in indexes
            if idx.isValid() and idx.column() == 0 and idx.internalPointer() is not None
        ]
        if not entries:
            return mime
        selected_ids = {id(e) for e in entries}
        top = [e for e in entries if e.parent is None or id(e.parent) not in selected_ids]
        mime.setData(self._MIME_TYPE, json.dumps([e.id for e in top]).encode("utf-8"))
        return mime

    def supportedDropActions(self) -> Qt.DropActions:
        return Qt.MoveAction

    def dropMimeData(self, data, action, row, column, parent) -> bool:
        if action == Qt.IgnoreAction or not data.hasFormat(self._MIME_TYPE):
            return False
        try:
            ids = json.loads(bytes(data.data(self._MIME_TYPE)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return False
        entries = [self.get_entry_by_id(i) for i in ids]
        entries = [e for e in entries if e is not None]
        if not entries:
            return False

        target_parent = parent.internalPointer() if parent.isValid() else None
        if any(self._is_ancestor(e, target_parent) for e in entries):
            return False

        target_row = row if row >= 0 else None
        if target_parent is None:
            if target_row is None:
                target_row = len(self._roots)
        else:
            if target_row is None:
                target_row = len(target_parent.children)

        containers = {}
        for e in entries:
            containers.setdefault(id(e.parent), []).append(e)

        removed_before_target = 0
        for key, group in containers.items():
            container = group[0].parent
            group.sort(key=lambda e: (container.children if container else self._roots).index(e))
            for e in reversed(group):
                if container is target_parent:
                    current_row = (container.children if container else self._roots).index(e)
                    if current_row < target_row:
                        removed_before_target += 1
                self.remove_entry(e)

        final_row = max(0, target_row - removed_before_target)
        for e in entries:
            self.insert_entry(e, target_parent, final_row)
            final_row += 1
        return True

    @staticmethod
    def _is_ancestor(entry: WatchEntry, node: Optional[WatchEntry]) -> bool:
        current = node
        while current is not None:
            if current is entry:
                return True
            current = current.parent
        return False

    def _register_entry(self, entry: WatchEntry):
        self._by_id[entry.id] = entry
        for child in entry.children:
            self._register_entry(child)

    def _unregister_entry(self, entry: WatchEntry):
        self._by_id.pop(entry.id, None)
        for child in entry.children:
            self._unregister_entry(child)

    # ================= 值更新 =================

    def update_entry_value(self, entry_id: int, new_value: Any):
        entry = self.get_entry_by_id(entry_id)
        if entry is None or entry.value == new_value:
            return
        entry.value = new_value
        index = self.index_for_entry(entry, 3)
        self.dataChanged.emit(index, index, [Qt.DisplayRole])

    def update_entry_address(self, entry_id: int, new_address: Optional[int]):
        entry = self.get_entry_by_id(entry_id)
        if entry is None or entry.resolved_address == new_address:
            return
        entry.resolved_address = new_address
        index = self.index_for_entry(entry, 1)
        self.dataChanged.emit(index, index, [Qt.DisplayRole])


class WatchPanel(QWidget):
    modify_requested = Signal(str, str, DataType)  # expression, value_str, data_type
    log_signal = Signal(LogLevel, str)
    entry_added = Signal(int)
    entry_removed = Signal(int)
    context_menu_requested = Signal(QMenu, WatchEntry)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._next_id = 1
        self._model = _WatchTreeModel(self)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        toolbar = QHBoxLayout()
        self.add_btn = QPushButton("添加观察项")
        self.add_btn.clicked.connect(self._on_add_clicked)
        self.expand_all_btn = QPushButton("全部展开")
        self.expand_all_btn.clicked.connect(self._on_expand_all_clicked)
        self.collapse_all_btn = QPushButton("全部收起")
        self.collapse_all_btn.clicked.connect(self._on_collapse_all_clicked)
        self.clear_btn = QPushButton("清空所有")
        self.clear_btn.clicked.connect(self._on_clear_clicked)

        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.expand_all_btn)
        toolbar.addWidget(self.collapse_all_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.clear_btn)
        layout.addLayout(toolbar)

        self.table = QTreeView(self)
        self.table.setModel(self._model)
        self.table.setFont(QFont("Consolas", 9))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setRootIsDecorated(True)
        self.table.setAnimated(False)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDragDropMode(QAbstractItemView.DragDrop)
        self.table.setDefaultDropAction(Qt.MoveAction)
        self.table.setIndentation(16)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        header = self.table.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultSectionSize(140)
        header.resizeSection(0, 80)
        header.resizeSection(1, 120)
        header.resizeSection(2, 80)
        header.resizeSection(3, 160)

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
        select_all = QShortcut(QKeySequence("Ctrl+A"), self.table)
        select_all.setContext(Qt.WidgetShortcut)
        select_all.activated.connect(self.table.selectAll)
        self._copy_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.table)
        self._copy_shortcut.setContext(Qt.WidgetShortcut)
        self._copy_shortcut.activated.connect(self._copy_selected)

    # ================= 公共接口 =================

    def add_entry(
        self,
        name: str,
        expression: str,
        data_type: DataType,
        parent_id: Optional[int] = None,
    ) -> int:
        parent = self.get_entry_by_id(parent_id) if parent_id is not None else None
        if parent_id is not None and parent is None:
            raise ValueError(f"父项不存在: {parent_id}")

        entry_id = self._next_id
        self._next_id += 1

        entry = WatchEntry(
            id=entry_id,
            name=name,
            expression=expression,
            data_type=data_type,
        )
        self._model.insert_entry(entry, parent)
        self._update_count()

        parent_text = parent.name if parent is not None else "根节点"
        self.log_signal.emit(
            LogLevel.INFO,
            f"添加观察项: {name} = {expression} ({data_type.value}) -> {parent_text}",
        )
        self.entry_added.emit(entry_id)
        return entry_id

    def remove_entries(self, ids: List[int]):
        id_set = set(ids)
        entries = self.get_entries()
        targets = [
            e for e in entries
            if e.id in id_set and (e.parent is None or e.parent.id not in id_set)
        ]
        for entry in targets:
            self._remove_subtree(entry)

    def remove_entry(self, entry_id: int):
        self.remove_entries([entry_id])

    def _remove_subtree(self, entry: WatchEntry):
        removed = [entry] + self._model._flatten(entry.children)
        self._model.remove_entry(entry)
        for item in removed:
            self.entry_removed.emit(item.id)
        self._update_count()
        self.log_signal.emit(
            LogLevel.INFO,
            f"删除观察项: {entry.name}（含子树 {len(removed)} 个节点）",
        )

    def duplicate_entries(self, ids: List[int]):
        id_set = set(ids)
        entries = self.get_entries()
        targets = [
            e for e in entries
            if e.id in id_set and (e.parent is None or e.parent.id not in id_set)
        ]
        for entry in targets:
            self._duplicate_entry(entry)

    def _duplicate_entry(self, entry: WatchEntry):
        new_name = self._unique_name(entry.name, entry.parent)
        new_entry = self._deep_copy(entry, new_name)

        parent = entry.parent
        if parent is None:
            row = self._model._roots.index(entry) + 1
        else:
            row = parent.children.index(entry) + 1
        self._model.insert_entry(new_entry, parent, row)
        self._update_count()
        self.log_signal.emit(LogLevel.INFO, f"复制观察项: {entry.name} -> {new_name}")

    def _deep_copy(self, entry: WatchEntry, name: str) -> WatchEntry:
        new_entry = WatchEntry(
            id=self._next_id,
            name=name,
            expression=entry.expression,
            data_type=entry.data_type,
        )
        self._next_id += 1
        for child in entry.children:
            child_copy = self._deep_copy(child, child.name)
            child_copy.parent = new_entry
            new_entry.children.append(child_copy)
        return new_entry

    def _unique_name(self, name: str, parent: Optional[WatchEntry]) -> str:
        siblings = parent.children if parent is not None else self._model._roots
        existing = {s.name for s in siblings}
        candidate = f"{name} (副本)"
        if candidate not in existing:
            return candidate
        i = 1
        while f"{name} (副本{i})" in existing:
            i += 1
        return f"{name} (副本{i})"

    def clear(self):
        count = len(self._model.get_entries())
        self._model.clear()
        self._update_count()
        self.log_signal.emit(LogLevel.INFO, f"清空 {count} 个观察项")

    def get_entries(self) -> List[WatchEntry]:
        return self._model.get_entries()

    def get_entry_by_id(self, entry_id: int) -> Optional[WatchEntry]:
        return self._model.get_entry_by_id(entry_id)

    def get_effective_expression(self, entry: WatchEntry) -> str:
        if entry.parent is None:
            return entry.expression
        return compose_expression(self.get_effective_expression(entry.parent), entry.expression)

    def get_effective_expressions(self) -> Dict[int, str]:
        result = {}

        def visit(entry: WatchEntry, parent_expr: Optional[str]):
            expression = (
                entry.expression
                if parent_expr is None
                else compose_expression(parent_expr, entry.expression)
            )
            result[entry.id] = expression
            for child in entry.children:
                visit(child, expression)

        for root in self._model.get_roots():
            visit(root, None)
        return result

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

        entry = self._model.entry_at(index)
        if entry is None:
            return

        selected = [
            e for e in (
                self._model.entry_at(idx)
                for idx in self.table.selectionModel().selectedRows(0)
            )
            if e is not None
        ]
        if entry not in selected:
            selection = self.table.selectionModel()
            selection.clearSelection()
            selection.select(
                self._model.index_for_entry(entry, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
            selected = [entry]

        targets = self._top_level_selected(selected)

        menu = QMenu(self)

        add_child_action = menu.addAction("添加子项")
        menu.addSeparator()
        duplicate_text = f"复制选中项 ({len(targets)})" if len(targets) > 1 else "复制此项"
        self._duplicate_action = menu.addAction(duplicate_text)
        menu.addSeparator()
        delete_text = f"删除选中项 ({len(targets)})" if len(targets) > 1 else "删除此项"
        self._delete_action = menu.addAction(delete_text)
        menu.addSeparator()
        self._copy_expr_action = menu.addAction("复制表达式")
        self._copy_addr_action = menu.addAction("复制地址")
        self._copy_value_action = menu.addAction("复制值")

        self.context_menu_requested.emit(menu, entry)

        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == add_child_action:
            self._show_add_dialog(parent_entry=entry)
        elif action == self._duplicate_action:
            self.duplicate_entries([e.id for e in targets])
        elif action == self._delete_action:
            self.remove_entries([e.id for e in targets])
        elif action == self._copy_expr_action:
            QApplication.clipboard().setText("\n".join(e.expression for e in selected))
        elif action == self._copy_addr_action:
            QApplication.clipboard().setText(
                "\n".join(
                    f"0x{e.resolved_address:08X}" if e.resolved_address is not None else "??"
                    for e in selected
                )
            )
        elif action == self._copy_value_action:
            QApplication.clipboard().setText(
                "\n".join("" if e.value is None else str(e.value) for e in selected)
            )

    @staticmethod
    def _top_level_selected(entries: List[WatchEntry]) -> List[WatchEntry]:
        selected_ids = {id(e) for e in entries}
        return [e for e in entries if e.parent is None or id(e.parent) not in selected_ids]

    def _copy_selected(self):
        selected = [
            e for e in (
                self._model.entry_at(idx)
                for idx in self.table.selectionModel().selectedRows(0)
            )
            if e is not None
        ]
        if not selected:
            return

        lines = []
        for entry in selected:
            cells = []
            for col in range(self._model.columnCount()):
                value = self._model.data(self._model.index_for_entry(entry, col), Qt.DisplayRole)
                cells.append("" if value is None else str(value))
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def _on_expand_all_clicked(self):
        self.table.expandAll()

    def _on_collapse_all_clicked(self):
        self.table.collapseAll()

    def _on_add_clicked(self):
        self._show_add_dialog()

    def _show_add_dialog(self, parent_entry: Optional[WatchEntry] = None):
        dialog = QDialog(self)
        dialog.setWindowTitle("添加子项" if parent_entry is not None else "添加观察项")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel("名字:"))
        name_edit = QLineEdit()
        name_edit.setText("子项" if parent_entry is not None else "新观察项")
        layout.addWidget(name_edit)

        layout.addWidget(QLabel("表达式:"))
        expr_edit = QLineEdit()
        expr_edit.setText("+ 0x0" if parent_entry is not None else "0x1000")
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

            self.add_entry(
                name,
                expression,
                data_type,
                parent_id=parent_entry.id if parent_entry is not None else None,
            )

    def _on_cell_double_clicked(self, index):
        if not index.isValid():
            return

        entry = self._model.entry_at(index)
        if entry is None:
            return
        col = index.column()

        if col == 0:  # 名字列
            dialog = NameEditDialog(entry.name, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                entry.name = dialog.get_new_name()
                self._emit_row_changed(entry)
                self.log_signal.emit(LogLevel.DEBUG, f"重命名: {entry.name}")

        elif col == 1:  # 地址列：双击编辑表达式
            dialog = ExpressionEditDialog(entry.expression, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_expr = dialog.get_new_expression()
                if new_expr:
                    entry.expression = new_expr
                    self._invalidate_addresses(entry)
                    self._emit_row_changed(entry)
                    self.log_signal.emit(LogLevel.DEBUG, f"表达式更新: {new_expr}")

        elif col == 2:  # 类型列
            dialog = TypeSelectDialog(entry.data_type, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_type = dialog.get_selected_type()
                if new_type != entry.data_type:
                    old_type = entry.data_type.value
                    entry.data_type = new_type
                    entry.value = None
                    self._emit_row_changed(entry)
                    self.log_signal.emit(
                        LogLevel.INFO,
                        f"类型切换: {entry.name} {old_type} -> {new_type.value}",
                    )

        elif col == 3:  # 值列
            current_value_str = self._model.data(index, Qt.DisplayRole)
            if current_value_str is None:
                current_value_str = ""
            dialog = EditValueDialog(current_value_str, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.modify_requested.emit(
                    self.get_effective_expression(entry),
                    dialog.get_value(),
                    entry.data_type,
                )

    def _emit_row_changed(self, entry: WatchEntry):
        start = self._model.index_for_entry(entry, 0)
        end = self._model.index_for_entry(entry, self._model.columnCount() - 1)
        self._model.dataChanged.emit(start, end, [Qt.DisplayRole])

    def _invalidate_addresses(self, entry: WatchEntry):
        for item in [entry] + self._model._flatten(entry.children):
            self._model.update_entry_address(item.id, None)

    def _on_clear_clicked(self):
        entries = self._model.get_entries()
        if not entries:
            return
        reply = QMessageBox.question(
            self,
            "确认清空",
            f"确定要清空所有 {len(entries)} 个观察项吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.clear()

    # ================= 序列化 =================

    def serialize(self) -> dict:
        return {
            "entries": [self._serialize_entry(e) for e in self._model.get_roots()],
        }

    @staticmethod
    def _serialize_entry(entry: WatchEntry) -> dict:
        return {
            "name": entry.name,
            "expression": entry.expression,
            "data_type": entry.data_type.value,
            "children": [WatchPanel._serialize_entry(child) for child in entry.children],
        }

    def deserialize(self, data: dict):
        self.clear()
        if "entries" not in data:
            return
        for item in data["entries"]:
            self._deserialize_item(item, None)

    def _deserialize_item(self, item: dict, parent: Optional[WatchEntry]):
        data_type = DataType.from_string(item["data_type"])
        entry_id = self.add_entry(
            item["name"],
            item["expression"],
            data_type,
            parent_id=parent.id if parent is not None else None,
        )
        entry = self.get_entry_by_id(entry_id)
        for child in item.get("children", []):
            self._deserialize_item(child, entry)