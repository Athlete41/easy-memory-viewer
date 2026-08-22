from PySide6.QtWidgets import (
    QVBoxLayout, QLabel,
    QLineEdit, QDialog, QDialogButtonBox, QComboBox, QPushButton
)
from common.types import DataType

class EditValueDialog(QDialog):
    def __init__(self, current_value: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("修改数值")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("输入新值（支持表达式，如 0x100+20）："))
        self.line_edit = QLineEdit()
        self.line_edit.setText(current_value)
        self.line_edit.selectAll()
        layout.addWidget(self.line_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_value(self) -> str:
        return self.line_edit.text()



class TypeSelectDialog(QDialog):
    """选择数据类型的对话框"""
    def __init__(self, current_type: DataType, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择数据类型")
        self.setModal(True)

        layout = QVBoxLayout(self)

        self.combo = QComboBox()
        for dt in DataType:
            self.combo.addItem(dt.value, dt)
        self.combo.setCurrentIndex(self.combo.findData(current_type))

        layout.addWidget(QLabel("选择新类型:"))
        layout.addWidget(self.combo)

        buttons = QPushButton("确定")
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)

    def get_selected_type(self) -> DataType:
        return self.combo.currentData()



class NameEditDialog(QDialog):
    """编辑名字的对话框"""
    def __init__(self, current_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑名字")
        self.setModal(True)

        layout = QVBoxLayout(self)

        self.line_edit = QLineEdit()
        self.line_edit.setText(current_name)
        self.line_edit.selectAll()

        layout.addWidget(QLabel("输入新名字:"))
        layout.addWidget(self.line_edit)

        buttons = QPushButton("确定")
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)

    def get_new_name(self) -> str:
        return self.line_edit.text().strip() or "未命名"



class ExpressionEditDialog(QDialog):
    """编辑表达式的对话框"""
    def __init__(self, current_expr: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑表达式")
        self.setModal(True)

        layout = QVBoxLayout(self)

        self.line_edit = QLineEdit()
        self.line_edit.setText(current_expr)
        self.line_edit.selectAll()

        layout.addWidget(QLabel("输入新表达式:"))
        layout.addWidget(self.line_edit)

        buttons = QPushButton("确定")
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)

    def get_new_expression(self) -> str:
        return self.line_edit.text().strip()