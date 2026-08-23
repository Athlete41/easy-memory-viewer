import os
import json
from typing import Dict

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QLabel, QComboBox, QPushButton, QCheckBox,
    QDockWidget, QFrame, QGroupBox, QMessageBox
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction

from ui.memory_viewer import MemoryViewer
from ui.log_panel import LogPanel
from ui.search_panel import SearchPanel
from ui.watch_panel import WatchPanel
from core.memory_tool import CrackerMemTool
from core.fetcher import Fetcher, ReadRequest
from common.types import DataType


class EasyMemoryViewerWindow(QMainWindow):
    """主窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Easy Memory Viewer")
        self.setGeometry(50, 50, 1400, 800)

        # ---- 核心依赖 ----
        self.tool = CrackerMemTool()
        self.fetcher = Fetcher(self.tool, merge_threshold=0x100, chunk_size=0x1000)
        self.fetcher.finished.connect(self._on_fetch_finished)
        self.fetcher.error.connect(self._on_fetch_error)

        # ---- 定时器 ----
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_timeout)
        self.timer_interval = 500
        self.timer_enabled = True

        # ---- 构建 UI ----
        self._setup_ui()
        self._setup_menu()
        self._setup_signals()

        # ---- 加载配置 ----
        self._load_config()

        # 启动定时器
        self._update_timer()

        # 记录上次请求
        self._last_addr = None
        self._last_size = None

        # 立即读取一次
        self._on_timer_timeout()

    # ================= UI 构建 =================
    def _setup_ui(self):
        """创建主布局"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # ========== 调度器面板 ==========
        scheduler_group = QGroupBox("调度器")
        scheduler_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #aaa;
                border-radius: 4px;
                margin-top: 0.5ex;
                padding-top: 0.5ex;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        scheduler_layout = QHBoxLayout(scheduler_group)
        scheduler_layout.setContentsMargins(10, 8, 10, 8)
        scheduler_layout.setSpacing(10)

        # 定时器开关
        self.timer_check = QCheckBox("定时刷新")
        self.timer_check.setChecked(True)
        self.timer_check.toggled.connect(self._toggle_timer)
        scheduler_layout.addWidget(self.timer_check)

        # 间隔下拉
        scheduler_layout.addWidget(QLabel("间隔:"))
        intervals = [100, 200, 500, 1000, 2000, 5000]
        self.interval_combo = QComboBox()
        for ms in intervals:
            self.interval_combo.addItem(f"{ms}ms", ms)
        self.interval_combo.setCurrentIndex(intervals.index(500))
        self.interval_combo.currentIndexChanged.connect(self._on_interval_changed)
        scheduler_layout.addWidget(self.interval_combo)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        scheduler_layout.addWidget(line)

        # 手动刷新按钮
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._manual_refresh)
        scheduler_layout.addWidget(refresh_btn)

        # 状态标签
        scheduler_layout.addStretch()
        self.scheduler_status = QLabel("就绪")
        scheduler_layout.addWidget(self.scheduler_status)

        main_layout.addWidget(scheduler_group, 0)

        # ========== 下方：水平分割 ==========
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.viewer = MemoryViewer(self.tool)

        # 右侧 Tab
        self.right_tabs = QTabWidget()
        self.right_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #ccc;
                border-radius: 4px;
            }
            QTabBar::tab {
                padding: 6px 12px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #e0e0e0;
                border-bottom: 2px solid #2196F3;
            }
        """)
        self.search_panel = SearchPanel()
        self.watch_panel = WatchPanel()

        self.right_tabs.addTab(self.search_panel, "🔍 搜索")
        self.right_tabs.addTab(self.watch_panel, "📋 候选")

        splitter.addWidget(self.viewer)
        splitter.addWidget(self.right_tabs)
        splitter.setSizes([800, 400])
        main_layout.addWidget(splitter, 1)

        # 日志 Dock
        self._setup_dock_log()

    def _setup_dock_log(self):
        """创建日志面板 Dock"""
        self.log_panel = LogPanel()
        dock = QDockWidget("📋 日志")
        dock.setWidget(self.log_panel)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self._log_dock = dock

    def _setup_signals(self):
        """连接信号"""

        self.viewer.viewport_changed.connect(self._on_viewport_changed)
        self.viewer.log_signal.connect(self.log_panel.log)
        self.viewer.bin_viewer.context_menu_requested.connect(self._on_bin_viewer_context_menu)

        self.search_panel.item_activated.connect(self._on_search_item_activated)
        self.search_panel.log_signal.connect(self.log_panel.log)
        self.search_panel.modify_requested.connect(self.viewer._on_modify_requested)
        self.search_panel.context_menu_requested.connect(self._on_search_context_menu)

        self.watch_panel.log_signal.connect(self.log_panel.log)
        self.watch_panel.modify_requested.connect(self.viewer._on_modify_requested)


    # ================= 调度逻辑 =================
    def _update_timer(self):
        """根据当前设置启动/停止定时器"""
        self.timer.stop()
        if self.timer_enabled:
            self.timer.setInterval(self.timer_interval)
            self.timer.start()

    def _toggle_timer(self, checked: bool):
        self.timer_enabled = checked
        self._update_timer()
        self.log_panel.info(f"定时器 {'开启' if checked else '关闭'}")

    def _on_interval_changed(self):
        self.timer_interval = self.interval_combo.currentData()
        self._update_timer()
        self.log_panel.debug(f"定时器间隔设为 {self.timer_interval}ms")

    def _manual_refresh(self):
        self.log_panel.info("手动刷新")
        self._on_timer_timeout()

    def _on_timer_timeout(self):
        if not self.tool.isAttached():
            return
        addr, size = self.viewer.get_viewport()
        if addr is None or size <= 0:
            return
        self._last_addr = addr
        self._last_size = size
        self._do_fetch()

    def _do_fetch(self):
        if self._last_addr is None:
            return

        self.tool.attachedStatusGuard()
        if not self.tool.isAttached():
            return

        requests = {}

        # 1. 视图请求
        requests["view"] = ReadRequest("view", self._last_addr, self._last_size)

        # 2. 搜索地址请求（SearchPanel 存的是绝对地址）
        for addr in self.search_panel.get_addresses():
            requests[f"search_{addr:X}"] = ReadRequest(f"search_{addr:X}", addr, 4)

        # 3. 观察项请求（WatchPanel 存的是表达式，需要解析）
        for entry in self.watch_panel.get_entries():
            try:
                address = self.viewer.getAddrByExpression(entry.expression)
            except Exception as e:
                self.log_panel.warning(f"解析表达式失败: {entry.expression} -> {e}")
                continue
            key = f"watch_{entry.id}"
            requests[key] = ReadRequest(key, address, entry.data_type.get_size())

        self.fetcher.request(requests)

    def _on_viewport_changed(self, address: int, size: int):
        self._last_addr = address
        self._last_size = size
        self._do_fetch()

    # ================= Fetcher 回调 =================
    def _on_fetch_finished(self, results: Dict[str, bytes]):
        if not results:
            return

        # 1. 视图数据
        if "view" in results:
            view_data = results["view"]
            self.viewer.set_data(view_data)
            self.search_panel.set_search_data(view_data, self.viewer.get_viewport()[0])

        # 2. 更新搜索面板
        self.search_panel.update_current_values(results)

        # 3. 更新观察面板
        self.watch_panel.update_values(results)

    def _on_fetch_error(self, err: str):
        self.viewer.set_status(f"读取错误: {err}")
        self.log_panel.error(f"读取错误: {err}")

    # ================= 搜索回调 =================

    def _on_search_item_activated(self, address: int, data_type: DataType, value: object):
        """双击搜索列表 -> 跳转到该地址"""
        self.viewer.jump_to(address, 0x100)
        self.log_panel.debug(f"跳转到搜索结果: 0x{address:X} = {value}")

    # ================= 配置加载/保存 =================

    def serialize(self) -> dict:
        return {
            "viewer": self.viewer.serialize(),
            "timer_interval": self.timer_interval,
            "timer_enabled": self.timer_check.isChecked(),
        }

    def deserialize(self, data: dict):
        if "viewer" in data:
            self.viewer.deserialize(data["viewer"])
        if "timer_interval" in data:
            idx = self.interval_combo.findData(data["timer_interval"])
            if idx >= 0:
                self.interval_combo.setCurrentIndex(idx)
                self.timer_interval = data["timer_interval"]
        if "timer_enabled" in data:
            self.timer_enabled = data["timer_enabled"]
            self.timer_check.setChecked(self.timer_enabled)
        self._update_timer()

    def _load_config(self):
        config_path = "MVCfg.json"
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.deserialize(config)
                self.log_panel.info("配置已加载")
        except Exception as e:
            self.log_panel.error(f"加载配置失败: {e}")

    def closeEvent(self, event):
        try:
            config = self.serialize()
            with open("MVCfg.json", 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            self.log_panel.info("配置已保存")
        except Exception as e:
            self.log_panel.error(f"保存配置失败: {e}")
        super().closeEvent(event)

    # ================= 菜单 =================

    def _setup_menu(self):
        """创建菜单栏"""
        menubar = self.menuBar()

        # ---- 文件菜单 ----
        file_menu = menubar.addMenu("文件")

        load_action = QAction("加载候选文件", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._on_load_candidates)
        file_menu.addAction(load_action)

        save_action = QAction("保存候选文件", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._on_save_candidates)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ---- 窗口菜单 ----
        window_menu = menubar.addMenu("窗口")
        log_action = self._log_dock.toggleViewAction()
        log_action.setText("日志面板")
        window_menu.addAction(log_action)

    def _on_bin_viewer_context_menu(self, menu, row, col, address, value, data_type):
        """外部往 BinViewer 的菜单里添加自定义项"""
        menu.addSeparator()
        
        # 添加到观察区
        watch_action = menu.addAction("添加到观察区")
        # 用 lambda 捕获，不立即执行
        watch_action.triggered.connect(
            lambda: self.watch_panel.add_entry(
                f"0x{address:X}", f"0x{address:X}", data_type
            )
        )

    def _on_search_context_menu(self, menu, row, col, result):
        """外部往 SearchPanel 的菜单里添加自定义项"""
        # 可以直接往 menu 里添加
        menu.addSeparator()
        watch_action = menu.addAction("添加到观察区")
        watch_action.triggered.connect(
            lambda: self.watch_panel.add_entry(
                f"搜索 @ 0x{result.address:X}",
                f"0x{result.address:X}",
                result.data_type
            )
        )

    # ================= 菜单槽函数 =================

    def _on_load_candidates(self):
        """加载候选文件（占位）"""
        self.log_panel.info("加载候选文件 (占位)")
        QMessageBox.information(self, "加载候选", "加载候选文件功能尚未实现 (占位)")

    def _on_save_candidates(self):
        """保存候选文件（占位）"""
        self.log_panel.info("保存候选文件 (占位)")
        QMessageBox.information(self, "保存候选", "保存候选文件功能尚未实现 (占位)")