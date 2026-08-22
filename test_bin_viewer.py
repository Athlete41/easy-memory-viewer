import sys
import struct
import random


from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton
)

from ui.bin_viewer import BinViewer
from common.types import DataType



class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BinViewer 高亮叠加测试 (PySide6)")
        self.setGeometry(100, 100, 1200, 500)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.viewer = BinViewer()
        layout.addWidget(self.viewer)

        btn_layout = QHBoxLayout()
        self.gen_btn = QPushButton("生成随机数据")
        self.gen_btn.clicked.connect(self.generate_data)
        self.modify_btn = QPushButton("模拟外部修改")
        self.modify_btn.clicked.connect(self.modify_data)
        btn_layout.addWidget(self.gen_btn)
        btn_layout.addWidget(self.modify_btn)
        layout.addLayout(btn_layout)

        self.viewer.modify_requested.connect(self.on_modify_requested)
        self.generate_data()

    def generate_data(self):
        data = bytearray(512)
        for i in range(512):
            data[i] = random.randint(0, 255)
        struct.pack_into('<f', data, 0x10, 3.1415)
        data[0x20:0x25] = b"Hello"
        struct.pack_into('<I', data, 0x30, 0x12345678)
        self.viewer.set_base_address(0x1000)
        self.viewer.set_data(bytes(data))

    def modify_data(self):
        if not self.viewer.get_data():
            return
        data = bytearray(self.viewer.get_data())
        # 修改几个位置，确保值改变
        if len(data) > 0x10:
            data[0x10] = 0xAA
        if len(data) > 0x20:
            data[0x20:0x25] = b"World"
        if len(data) > 0x30:
            struct.pack_into('<I', data, 0x30, 0xDEADBEEF)
        # 随机改几个
        for _ in range(3):
            idx = random.randint(0, len(data)-1)
            data[idx] = random.randint(0, 255)
        self.viewer.set_data(bytes(data))

    def on_modify_requested(self, address: int, value_str: str, type: DataType):
        print(f"修改请求: 地址 0x{address:X}, 新值 = '{value_str}' ({type})")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TestWindow()
    win.show()
    sys.exit(app.exec())