import sys
import os
import zipfile
import json
from typing import Dict

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QPushButton, QWidget, QDockWidget
from PySide6.QtCore import QTimer, Qt

from ui.memory_viewer import MemoryViewer
from ui.log_panel import LogPanel, LogLevel
from core.memory_tool import CrackerMemTool
from core.fetcher import Fetcher, ReadRequest
from core.cracker_installer import install, uninstall


# ---- 驱动 ----
current_dir = os.path.dirname(os.path.abspath(__file__))
cracker_path = os.path.join(current_dir, "driver", "cracker.sys")
if not os.path.exists(cracker_path):
    cracker_zip_path = os.path.join(current_dir, "driver", "cracker.zip")
    if os.path.exists(cracker_zip_path):
        with zipfile.ZipFile(cracker_zip_path, 'r') as zf:
            zf.extractall(os.path.join(current_dir, "driver"))
    else:
        print("驱动不存在")
        sys.exit(1)

uninstall(cracker_path)
if not install(cracker_path, "测试"):
    print("安装失败")
    sys.exit(1)

# ---- 测试窗口 ----
class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MemoryViewer 测试 - 外部调度")
        self.setGeometry(100, 100, 1000, 600)
        self._setup_dock_log()

        # 1. 创建依赖
        self.tool = CrackerMemTool()     
        
        # 2. 创建 MemoryViewer
        self.viewer = MemoryViewer(self.tool)
        self.viewer.viewport_changed.connect(self._on_viewport_changed)

        # 3. 创建 Fetcher（外部管理）
        self.fetcher = Fetcher(self.tool, merge_threshold=0x100, chunk_size=0x1000)
        self.fetcher.finished.connect(self._on_fetch_finished)
        self.fetcher.error.connect(self._on_fetch_error)
        self.viewer.log_signal.connect(self.log_panel.log)

        # 4. 定时器（外部管理）
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start(500)

        # 5. UI
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(self.viewer)

        btn = QPushButton("手动刷新")
        btn.clicked.connect(self._on_timer)
        layout.addWidget(btn)

        # 记录上次请求的地址，避免重复
        self._last_addr = None
        self._last_size = None

        self._load_config()

    def _setup_dock_log(self):
        """创建日志面板 Dock"""
        self.log_panel = LogPanel()
        dock = QDockWidget("📋 日志")
        dock.setWidget(self.log_panel)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def _on_viewport_changed(self, address: int, size: int):
        """视图范围变化 → 立即读取"""
        self._last_addr = address
        self._last_size = size
        self._do_fetch()

    def _on_timer(self):
        """定时器触发 → 读取当前视图"""
        if not self.tool.isAttached():
            return
        addr, size = self.viewer.get_viewport()
        self._last_addr = addr
        self._last_size = size
        self._do_fetch()

    def _do_fetch(self):
        if self._last_addr is None:
            return
        # 使用字典，带 id
        requests = {
            "view": ReadRequest("view", self._last_addr, self._last_size)
        }
        self.fetcher.request(requests)

    def _on_fetch_finished(self, results: Dict[str, bytes]):
        """处理读取结果"""
        if "view" in results:
            self.viewer.set_data(results["view"])

    def _on_fetch_error(self, err: str):
        self.viewer.log_signal.emit(LogLevel.ERROR, f"读取错误: {err}")

    def _load_config(self):
        """加载配置文件 TestWindowMVCfg.json"""
        config_path = "TestWindowMVCfg.json"
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.viewer.deserialize(config)
                print("配置已加载")
        except Exception as e:
            print(f"加载配置失败: {e}")

    def closeEvent(self, event):
        """窗口关闭时保存配置"""
        try:
            config = self.viewer.serialize()
            with open("TestWindowMVCfg.json", 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            print("配置已保存")
        except Exception as e:
            print(f"保存配置失败: {e}")
        super().closeEvent(event)


app = QApplication(sys.argv)
win = TestWindow()
win.show()
app.exec()

uninstall(cracker_path)
sys.exit(0)