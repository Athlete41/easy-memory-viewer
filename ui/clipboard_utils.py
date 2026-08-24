"""表格复制工具：把选中区域/选中行转成 TSV 写入剪贴板。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _cell_text(model, index) -> str:
    value = model.data(index, Qt.DisplayRole)
    return "" if value is None else str(value)


def copy_selected_cells(view) -> bool:
    """复制选中单元格区域，按行合并为 TSV。"""
    selection = view.selectionModel()
    if selection is None:
        return False
    indexes = selection.selectedIndexes()
    if not indexes:
        return False
    model = view.model()
    rows = {}
    for idx in indexes:
        rows.setdefault(idx.row(), {})[idx.column()] = _cell_text(model, idx)
    lines = []
    for row in sorted(rows):
        cols = sorted(rows[row])
        lines.append("\t".join(rows[row][c] for c in cols))
    if not lines:
        return False
    QApplication.clipboard().setText("\n".join(lines))
    return True


def copy_selected_rows(view) -> bool:
    """复制完整选中行（所有列），行内制表符分隔。"""
    selection = view.selectionModel()
    if selection is None:
        return False
    model = view.model()
    if model is None:
        return False
    rows = sorted({idx.row() for idx in selection.selectedRows(0)})
    if not rows:
        return False
    lines = []
    for row in rows:
        cells = [_cell_text(model, model.index(row, col)) for col in range(model.columnCount())]
        lines.append("\t".join(cells))
    QApplication.clipboard().setText("\n".join(lines))
    return True