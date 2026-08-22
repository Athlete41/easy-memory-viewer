from enum import Enum
from datetime import datetime

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton, QComboBox, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

    @property
    def order(self) -> int:
        """等级顺序：DEBUG(0) < INFO(1) < WARNING(2) < ERROR(3)"""
        return {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}[self.value]


class LogPanel(QWidget):
    """日志显示面板，支持等级过滤和颜色标记"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level_colors = {
            LogLevel.DEBUG: "#4CAF50",    # 绿色
            LogLevel.INFO: "#2196F3",     # 蓝色
            LogLevel.WARNING: "#FF9800",  # 橙色
            LogLevel.ERROR: "#F44336",    # 红色
        }
        self._level_order = {LogLevel.DEBUG: 0, LogLevel.INFO: 1, LogLevel.WARNING: 2, LogLevel.ERROR: 3}
        self._current_level = LogLevel.DEBUG  # 默认显示所有
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---- 工具栏 ----
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("日志等级:"))

        self.level_combo = QComboBox()
        for level in LogLevel:
            self.level_combo.addItem(level.value, level)
        self.level_combo.setCurrentIndex(0)  # DEBUG
        self.level_combo.currentIndexChanged.connect(self._on_level_changed)
        toolbar.addWidget(self.level_combo)

        toolbar.addStretch()

        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self.clear)
        toolbar.addWidget(self.clear_btn)

        layout.addLayout(toolbar)

        # ---- 日志显示 ----
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(False)
        self.text_browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        layout.addWidget(self.text_browser)

    # ================= 日志输出 =================
    def log(self, level: LogLevel, message: str):
        """输出一条日志，带颜色标记，根据当前等级过滤"""
        if self._should_ignore(level):
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        color = self._level_colors.get(level, "#000000")
        level_name = level.value

        html = f'<span style="color:#888888;">[{timestamp}]</span> '
        html += f'<span style="color:{color}; font-weight:bold;">[{level_name}]</span> '
        html += f'<span style="color:#000000;">{self._escape_html(message)}</span>'

        self.text_browser.append(html)

    def debug(self, message: str):
        self.log(LogLevel.DEBUG, message)

    def info(self, message: str):
        self.log(LogLevel.INFO, message)

    def warning(self, message: str):
        self.log(LogLevel.WARNING, message)

    def error(self, message: str):
        self.log(LogLevel.ERROR, message)

    def clear(self):
        """清空所有日志"""
        self.text_browser.clear()

    def set_log_level(self, level: LogLevel):
        """设置最低显示等级（低于该等级的日志将被忽略）"""
        self._current_level = level
        # 同步下拉框
        index = self.level_combo.findData(level)
        if index >= 0:
            self.level_combo.setCurrentIndex(index)

    def get_log_level(self) -> LogLevel:
        """获取当前日志等级"""
        return self._current_level

    def _should_ignore(self, level: LogLevel) -> bool:
        """判断是否应忽略该等级的日志"""
        return self._level_order[level] < self._level_order[self._current_level]

    def _escape_html(self, text: str) -> str:
        """转义 HTML 特殊字符"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def append_raw(self, text: str):
        """直接追加纯文本（不做格式化）"""
        self.text_browser.append(text)

    # ================= 内部 =================
    def _on_level_changed(self, index: int):
        """下拉框改变时更新当前等级"""
        level = self.level_combo.itemData(index)
        if level is not None:
            self._current_level = level


# ================= 测试入口 =================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QPushButton, QWidget

    class TestWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("LogPanel 测试")
            self.setGeometry(100, 100, 600, 400)

            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)

            self.log_panel = LogPanel()
            layout.addWidget(self.log_panel)

            # 测试按钮
            btn_layout = QHBoxLayout()
            for level in LogLevel:
                btn = QPushButton(level.value)
                btn.clicked.connect(lambda checked, l=level: self.log_panel.log(l, f"这是一条 {l.value} 级别的测试消息"))
                btn_layout.addWidget(btn)
            layout.addLayout(btn_layout)

    app = QApplication(sys.argv)
    win = TestWindow()
    win.show()
    sys.exit(app.exec())