from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton, QGroupBox, QMessageBox, QCheckBox
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSizePolicy


from common.types import DataType
from ui.bin_viewer import BinViewer
from ui.log_panel import LogLevel
from core.memory_tool import MemoryTool
import struct

class MemoryToolPanel(QWidget):
    """
    MemoryTool 的图形界面控制面板。
    只负责进程名输入、附加/分离控制。
    错误直接弹窗，同时发出日志信号。
    """
    
    log_signal = Signal(LogLevel, str)  # (level, message)

    def __init__(self, memory_tool: MemoryTool, parent=None):
        super().__init__(parent)
        self._memory_tool = memory_tool
        self._is_attached = False

        self._build_ui()
        self._connect_signals()
        self._memory_tool.attachStatusChanged.connect(self._on_attach_status_changed)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        group = QGroupBox("进程控制")
        group_layout = QHBoxLayout(group)

        self.process_edit = QLineEdit()
        self.process_edit.setPlaceholderText("进程名 (如 notepad.exe)")
        self.process_edit.setMinimumWidth(100)

        self.attach_btn = QPushButton("附加")
        self.detach_btn = QPushButton("分离")
        self.detach_btn.setEnabled(False)

        group_layout.addWidget(QLabel("进程名:"))
        group_layout.addWidget(self.process_edit)
        group_layout.addWidget(self.attach_btn)
        group_layout.addWidget(self.detach_btn)

        layout.addWidget(group)

    def _connect_signals(self):
        self.attach_btn.clicked.connect(self._on_attach_clicked)
        self.detach_btn.clicked.connect(self._on_detach_clicked)
        self.process_edit.returnPressed.connect(self._on_attach_clicked)

    # ================= 公共接口 =================
    def attach(self):
        process_name = self.process_edit.text().strip()
        if not process_name:
            self.log_signal.emit(LogLevel.WARNING, "进程名为空")
            QMessageBox.warning(self, "错误", "进程名不能为空")
            return

        try:
            self._memory_tool.setProcessName(process_name)
            self._memory_tool.attach()
            self.log_signal.emit(LogLevel.INFO, f"正在附加到进程: {process_name}")
        except Exception as e:
            self.log_signal.emit(LogLevel.ERROR, f"附加失败: {e}")
            QMessageBox.warning(self, "附加失败", str(e))

    def detach(self):
        if self._memory_tool:
            try:
                self._memory_tool.close()
                self.log_signal.emit(LogLevel.INFO, "已分离进程")
            except Exception as e:
                self.log_signal.emit(LogLevel.ERROR, f"分离失败: {e}")
                QMessageBox.warning(self, "分离失败", str(e))

    @property
    def memory_tool(self) -> MemoryTool:
        return self._memory_tool

    @memory_tool.setter
    def memory_tool(self, memory_tool: MemoryTool):
        self._memory_tool = memory_tool

    @property
    def is_attached(self) -> bool:
        return self._is_attached

    # ================= 内部 =================
    def _on_attach_clicked(self):
        self.attach()

    def _on_detach_clicked(self):
        self.detach()

    def _on_attach_status_changed(self, attached: bool):
        self._is_attached = attached
        self.detach_btn.setEnabled(attached)
        self.attach_btn.setEnabled(not attached)
        self.process_edit.setEnabled(not attached)
        if attached:
            self.log_signal.emit(LogLevel.INFO, "附加成功")
        else:
            self.log_signal.emit(LogLevel.INFO, "已分离")

    def get_process_name(self) -> str:
        """获取当前输入的进程名"""
        return self.process_edit.text()

    def set_process_name(self, name: str):
        """设置进程名输入框"""
        self.process_edit.setText(name)

class MemoryViewer(QWidget):
    """
    内存查看器。
    组装 MemoryToolPanel + BinViewer，只负责显示。
    """
    
    viewport_changed = Signal('long long', 'long long')
    log_signal = Signal(LogLevel, str)  # (level, message) 日志信号
    jump_clicked_signal = Signal(str, int)  # (address, size) 跳转信号

    def __init__(self, memory_tool: MemoryTool, parent=None):
        super().__init__(parent)
        self._memory_tool = memory_tool
        self._view_address = 0x0
        self._view_range = 0x100

        # 子控件
        self._panel = MemoryToolPanel(memory_tool)
        self._bin_viewer = BinViewer()

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---- 顶部：面板 + 跳转 ----
        top_bar = QHBoxLayout()
        top_bar.addWidget(self.panel, 1)  # panel 占 2 份

        jump_group = QGroupBox("跳转")
        jump_layout = QVBoxLayout(jump_group)

        # 地址行
        addr_row = QHBoxLayout()
        self.addr_edit = QLineEdit()
        self.addr_edit.setPlaceholderText("地址")
        self.addr_edit.setText("0x0")
        self.addr_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.is_64bit_checkbox = QCheckBox("64位地址")
        self.is_64bit_checkbox.setChecked(True)

        addr_row.addWidget(QLabel("地址:"))
        addr_row.addWidget(self.addr_edit, 1)  # ← 拉伸因子 1，占满剩余空间
        addr_row.addWidget(self.is_64bit_checkbox)

        # 大小行
        size_row = QHBoxLayout()
        self.size_edit = QLineEdit()
        self.size_edit.setPlaceholderText("大小")
        self.size_edit.setText("0x100")
        self.size_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.jump_btn = QPushButton("跳转")

        size_row.addWidget(QLabel("大小:"))
        size_row.addWidget(self.size_edit, 1)  # ← 拉伸因子 1
        size_row.addWidget(self.jump_btn)

        # 信息行
        hex_row = QHBoxLayout()
        self.hex_label = QLabel("当前: 0x00000000 (0x100 字)")
        hex_row.addWidget(self.hex_label)
        hex_row.addStretch()

        jump_layout.addLayout(addr_row)
        jump_layout.addLayout(size_row)
        jump_layout.addLayout(hex_row)

        top_bar.addWidget(jump_group, 1)  # jump 占 1 份
        layout.addLayout(top_bar)

        # ---- BinViewer ----
        layout.addWidget(self.bin_viewer, 1)

    def _connect_signals(self):
        self.jump_btn.clicked.connect(self._on_jump_clicked)
        self.addr_edit.returnPressed.connect(self._on_jump_clicked)
        self.panel.memory_tool.attachStatusChanged.connect(self._on_attach_status_changed)
        self._bin_viewer.modify_requested.connect(self._on_modify_requested)

    # ================= 公共接口 =================
    def set_data(self, data: bytes):
        """外部喂数据"""
        self.bin_viewer.set_data(data)
        self.bin_viewer.set_base_address(self._view_address)

    def get_data(self) -> bytes:
        """获取当前视口内的数据"""
        return self.bin_viewer.get_data()

    def getAddrByExpression(self, expression: str) -> int:
        return self._memory_tool.getAddrByExpression(expression, self.is_64bit_checkbox.isChecked())

    def jump_to(self, addrExpression: str | int, size: int):
        """跳转到新地址，发出信号"""
        if size <= 0:
            return

        address = addrExpression
        if isinstance(address, str):
            try:
                address = self._memory_tool.getAddrByExpression(
                    addrExpression, 
                    self.is_64bit_checkbox.isChecked()
                )
            except Exception as e:
                error_msg = f"地址: {addrExpression}, 错误: {str(e)}"
                QMessageBox.warning(self, "跳转失败", error_msg)
                self.log_signal.emit(LogLevel.ERROR, f"跳转失败: {error_msg}")
                return

        self._view_address = address
        self._view_range = size
        self.hex_label.setText(f"当前: 0x{address:X} (0x{size:X} 字)")
        self.log_signal.emit(LogLevel.INFO, f"跳转到 0x{address:X} (0x{size:X} 字)")
        self.viewport_changed.emit(address, size)
        self.jump_clicked_signal.emit(addrExpression if isinstance(addrExpression, str) else f"0x{addrExpression:X}", size)

        self.addr_edit.setText(addrExpression if isinstance(addrExpression, str) else f"0x{addrExpression:X}")
        self.size_edit.setText(f"0x{size:X}")

    @property
    def bin_viewer(self) -> BinViewer:
        return self._bin_viewer

    @property
    def panel(self) -> MemoryToolPanel:
        return self._panel

    def get_viewport(self):
        return (self._view_address, self._view_range)


    # ================= 内部 =================
    def _on_jump_clicked(self):
        addr_text = self.addr_edit.text().strip()
        size_text = self.size_edit.text().strip()
        try:
            size = int(size_text, 16) if 'x' in size_text.lower() else int(size_text)
            self.jump_to(addr_text, size)
        except ValueError as e:
            self.log_signal.emit(LogLevel.ERROR, f"无效输入: {e}")

    def _on_attach_status_changed(self, attached: bool):
        status = "已附加" if attached else "已分离"
        self.log_signal.emit(LogLevel.INFO, status)

    def _on_modify_requested(self, address: int | str, expression: str, type: DataType):
        """处理修改请求：解析表达式 → 打包 → 写入 → 刷新"""

        if isinstance(address, str):
            try:
                address = self.getAddrByExpression(address)
            except Exception as e:
                self.log_signal.emit(LogLevel.ERROR, f"解析失败: 地址 {address} 错误 {str(e)}")
                return

        try:
            if type == DataType.STRING:
                data = expression.encode('utf-8')
            else:
                # 数值类型：eval 表达式
                val = eval(expression, {}, {})  # 安全 eval，禁止访问内置函数
                if type == DataType.BYTE:
                    data = struct.pack('b', val)       # 有符号 byte
                elif type == DataType.INT16:
                    data = struct.pack('<h', val)      # 小端 16 位
                elif type in (DataType.INT32, DataType.HEX32):
                    data = struct.pack('<i', val)      # 小端 32 位
                elif type == DataType.INT64:
                    data = struct.pack('<q', val)      # 小端 64 位
                elif type == DataType.FLOAT:
                    data = struct.pack('<f', val)      # 小端 float
                elif type == DataType.DOUBLE:
                    data = struct.pack('<d', val)      # 小端 double
                else:
                    raise ValueError(f"不支持的数据类型: {type}")

            # 写入内存
            self._memory_tool.write(address, data)
            self.log_signal.emit(LogLevel.INFO, f"修改成功: 0x{address:X} <- {expression}")
            # self.viewport_changed.emit(self._view_address, self._view_range)
        except Exception as e:
            self.log_signal.emit(LogLevel.ERROR, f"地址 0x{address:X}, 表达式 {expression}, 数据类型 {type}, 修改失败: {e}")

    def serialize(self) -> dict:
        return {
            "process_name": self.panel.get_process_name(),
            "address": self.addr_edit.text(),
            "size": self.size_edit.text(),
            "is_64bit": self.is_64bit_checkbox.isChecked()
        }

    def deserialize(self, data: dict):
        if "process_name" in data:
            self.panel.set_process_name(data["process_name"])
        if "address" in data:
            self.addr_edit.setText(data["address"])
        if "size" in data:
            self.size_edit.setText(data["size"])
        if "is_64bit" in data:
            self.is_64bit_checkbox.setChecked(data["is_64bit"])
