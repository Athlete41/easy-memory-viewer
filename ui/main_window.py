import os
import json
from typing import Dict

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QLabel, QComboBox, QPushButton, QCheckBox,
    QDockWidget, QFrame, QGroupBox, QMessageBox, QFileDialog
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction

from ui.memory_viewer import MemoryViewer
from ui.log_panel import LogPanel
from ui.search_panel import SearchPanel
from ui.watch_panel import WatchPanel, WatchEntry
from core.memory_engine import MemoryEngine
from core.memory_engine import ReadRequest
from common.types import DataType


class EasyMemoryViewerWindow(QMainWindow):
    """主窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Easy Memory Viewer")
        self.setGeometry(50, 50, 1400, 800)

        self._recent_files: list[str] = []
        self._max_recent_files = 10

        self._jump_history: list[str] = []
        self._max_jump_history = 50

        # ---- 核心依赖 ----
        self.engine = MemoryEngine()
        self.engine.fetch_finished.connect(self._on_fetch_finished)
        self.engine.fetch_error.connect(self._on_fetch_error)

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
        self.viewer = MemoryViewer(self.engine)

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
        self.search_panel.refresh_before_next_scan = True
        self.watch_panel = WatchPanel()

        self.right_tabs.addTab(self.search_panel, "🔍 搜索")
        self.right_tabs.addTab(self.watch_panel, "📋 观察")

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
        self.viewer.bin_viewer.modify_requested.connect(self._on_modify_requested)
        self.viewer.jump_clicked_signal.connect(self._add_jump_history)

        self.search_panel.item_activated.connect(self._on_search_item_activated)
        self.search_panel.log_signal.connect(self.log_panel.log)
        self.search_panel.modify_requested.connect(self._on_modify_requested)
        self.search_panel.context_menu_requested.connect(self._on_search_context_menu)
        self.search_panel.next_scan_requested.connect(self._on_search_next_scan_requested)

        self.watch_panel.log_signal.connect(self.log_panel.log)
        self.watch_panel.modify_requested.connect(self._on_modify_requested)
        self.watch_panel.context_menu_requested.connect(self._on_watch_context_menu)


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
        if not self.engine.isAttached():
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

        self.engine.attachedStatusGuard()
        if not self.engine.isAttached():
            return

        self.engine.clear_pointer_cache()

        requests = {}

        # 1. 视图请求
        requests["view"] = ReadRequest("view", self._last_addr, self._last_size)

        # 2. 搜索地址请求（SearchPanel 存的是绝对地址）
        for addr in self.search_panel.get_addresses():
            requests[f"search_{addr:X}"] = ReadRequest(f"search_{addr:X}", addr, 4)

        # 3. 观察项请求（WatchPanel 存的是表达式，需要解析有效表达式）
        effective_map = self.watch_panel.get_effective_expressions()
        address_map = {}
        for entry in self.watch_panel.get_entries():
            expression = effective_map[entry.id]
            try:
                address = self.engine.resolve_expression(
                    expression,
                    self.viewer.is_64bit_checkbox.isChecked(),
                    use_cache=True
                )
                address_map[entry.id] = address
            except Exception as e:
                self.log_panel.warning(f"解析表达式失败: {expression} -> {e}")
                continue
            key = f"watch_{entry.id}"
            requests[key] = ReadRequest(key, address, entry.data_type.get_size())

        self.watch_panel.update_addresses(address_map)

        self.engine.fetch(requests)

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
        self.scheduler_status.setText(f"读取错误: {err}")
        self.log_panel.error(f"读取错误: {err}")

    def _on_modify_requested(self, address, value_expr: str, data_type: DataType):
        """统一的内存修改入口，经 MemoryEngine 写入。"""
        try:
            resolved = self.engine.modify(
                address,
                value_expr,
                data_type,
                is64bit=self.viewer.is_64bit_checkbox.isChecked(),
            )
            self.log_panel.info(f"修改成功: 0x{resolved:X} <- {value_expr}")
        except Exception as e:
            self.log_panel.error(f"修改失败: {address} <- {value_expr}: {e}")

    # ================= 搜索回调 =================

    def _on_search_next_scan_requested(self):
        """再次扫描前先同步刷新一次内存数据，再用新数据执行扫描。"""
        if not self.engine.isAttached():
            self.log_panel.warning("未附加进程，无法刷新后再次扫描")
            return
        self._manual_refresh()
        self.search_panel.continue_next_scan()

    def _on_search_item_activated(self, address: int, data_type: DataType, value: object):
        """双击搜索列表 -> 跳转到该地址"""
        self.viewer.jump_to(address, size=None)
        self.log_panel.debug(f"跳转到搜索结果: 0x{address:X} = {value}")

    # ================= 配置加载/保存 =================

    def serialize(self) -> dict:
        return {
            "viewer": self.viewer.serialize(),
            "search_panel": self.search_panel.serialize(),
            "timer_interval": self.timer_interval,
            "timer_enabled": self.timer_check.isChecked(),
            "recent_files": self._recent_files,
            # "jump_history": self._jump_history,
        }

    def deserialize(self, data: dict):
        if "viewer" in data:
            self.viewer.deserialize(data["viewer"])
        if "search_panel" in data:
            self.search_panel.deserialize(data["search_panel"])
        if "timer_interval" in data:
            idx = self.interval_combo.findData(data["timer_interval"])
            if idx >= 0:
                self.interval_combo.setCurrentIndex(idx)
                self.timer_interval = data["timer_interval"]
        if "timer_enabled" in data:
            self.timer_enabled = data["timer_enabled"]
            self.timer_check.setChecked(self.timer_enabled)
        if "recent_files" in data:
            self._recent_files = data["recent_files"][:self._max_recent_files]
            self._update_recent_menu()
        # if "jump_history" in data:
        #     self._jump_history = data["jump_history"][-self._max_jump_history:]
        #     self._update_jump_history_menu()
        self._update_timer()

    def _update_recent_menu(self):
        """更新最近文件菜单"""
        self._recent_menu.clear()
        if not self._recent_files:
            no_action = QAction("（无最近文件）", self)
            no_action.setEnabled(False)
            self._recent_menu.addAction(no_action)
            return
        
        for file_path in self._recent_files:
            # 只显示文件名，完整路径作为 tooltip
            name = os.path.basename(file_path)
            action = QAction(name, self)
            action.setToolTip(file_path)
            action.triggered.connect(lambda checked, path=file_path: self._on_load_watch_data(path))
            self._recent_menu.addAction(action)
        
        self._recent_menu.addSeparator()
        clear_action = QAction("清除最近文件", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self._recent_menu.addAction(clear_action)

    def _clear_recent_files(self):
        """清除最近文件列表"""
        self._recent_files.clear()
        self._update_recent_menu()
        self.log_panel.debug("最近文件列表已清除")

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

        # 加载 WatchPanel 数据（手动）
        load_action = QAction("加载观察数据", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._on_load_watch_data)
        file_menu.addAction(load_action)

        # 保存 WatchPanel 数据（手动）
        save_action = QAction("保存观察数据", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._on_save_watch_data)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        # 最近打开文件（显示最近加载的观察数据文件）
        self._recent_menu = file_menu.addMenu("最近打开文件")
        self._update_recent_menu()

        file_menu.addSeparator()

        # 导出内存数据（新增）
        export_action = QAction("导出内存数据", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._on_export_memory_data)
        file_menu.addAction(export_action)

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

        # ---- 查看菜单 ----
        view_menu = menubar.addMenu("查看")
        
        # 跳转历史子菜单
        self._jump_history_menu = view_menu.addMenu("跳转历史")
        self._update_jump_history_menu()  # 初始化

        # 清空历史
        clear_history_action = QAction("清空跳转历史", self)
        clear_history_action.triggered.connect(self._clear_jump_history)
        view_menu.addAction(clear_history_action)

    def _on_bin_viewer_context_menu(self, menu, row, col, address, value, data_type):
        """外部往 BinViewer 的菜单里添加自定义项"""
        menu.addSeparator()
        
        # 添加到观察区
        watch_action = menu.addAction("添加到观察区")
        # 用 lambda 捕获，不立即执行
        watch_action.triggered.connect(lambda: self._add_bin_selection_to_watch())

        if data_type == DataType.HEX64:
            try:
                target = int(str(value), 16)
            except ValueError:
                target = None
            if target is not None:
                menu.addSeparator()
                jump_action = menu.addAction(f"跳转到值 0x{target:X}")
                jump_action.triggered.connect(
                    lambda: self.viewer.jump_to(target, size=None)
                )

    def _add_bin_selection_to_watch(self):
        for address, _value, data_type in self.viewer.bin_viewer.get_selected_entries():
            self.watch_panel.add_entry(f"0x{address:X}", f"0x{address:X}", data_type)

    def _on_search_context_menu(self, menu, result, results):
        """外部往 SearchPanel 的右键菜单里添加自定义项"""
        menu.addSeparator()
        label = f"添加到观察区 ({len(results)})" if len(results) > 1 else "添加到观察区"
        watch_action = menu.addAction(label)
        watch_action.triggered.connect(
            lambda: self._add_search_results_to_watch(results)
        )

    def _add_search_results_to_watch(self, results):
        for result in results:
            self.watch_panel.add_entry(
                f"搜索 @ 0x{result.address:X}",
                f"0x{result.address:X}",
                result.data_type,
            )


    def _on_watch_context_menu(self, menu, entry: WatchEntry):
        """外部往 WatchPanel 的右键菜单里添加自定义项"""
        menu.addSeparator()
        
        # 跳转到该地址
        expression = self.watch_panel.get_effective_expression(entry)
        jump_action = menu.addAction(f"跳转到 {expression}")
        jump_action.triggered.connect(
            lambda: self.viewer.jump_to(expression, size=None)
        )

        if entry.value is not None and isinstance(entry.value, int) and (entry.data_type == DataType.HEX32 or entry.data_type == DataType.HEX64):
            jump_value_action = menu.addAction(f"跳转到 {hex(entry.value)}")
            jump_value_action.triggered.connect(
                lambda: self.viewer.jump_to(entry.value, size=None)
            )

    def _add_jump_history(self, expression: str, size: int):
        """添加跳转历史，去重+长度限制"""
        if not expression:
            return
        
        # 如果和上一条相同，不记录
        if self._jump_history and self._jump_history[-1] == expression:
            return
        
        self._jump_history.append(expression)
        
        # 限制长度
        if len(self._jump_history) > self._max_jump_history:
            self._jump_history = self._jump_history[-self._max_jump_history:]
        
        # 更新菜单
        self._update_jump_history_menu()


    def _update_jump_history_menu(self):
        """更新跳转历史菜单"""
        self._jump_history_menu.clear()
        
        if not self._jump_history:
            no_action = QAction("（无跳转历史）", self)
            no_action.setEnabled(False)
            self._jump_history_menu.addAction(no_action)
            return
        
        for addrExpr in self._jump_history:
            # 截断显示，避免菜单太长
            display_text = addrExpr if len(addrExpr) <= 40 else addrExpr[:37] + "..."
            action = QAction(display_text, self)
            action.setToolTip(addrExpr)
            action.triggered.connect(lambda checked, e=addrExpr: self.viewer.jump_to(e, size=None))
            self._jump_history_menu.addAction(action)

    def _clear_jump_history(self):
        """清空跳转历史"""
        self._jump_history.clear()
        self._update_jump_history_menu()
        self.log_panel.debug("跳转历史已清空")

    def _add_recent_file(self, file_path: str):
        """添加到最近文件列表"""
        if file_path in self._recent_files:
            self._recent_files.remove(file_path)
        self._recent_files.insert(0, file_path)
        if len(self._recent_files) > self._max_recent_files:
            self._recent_files = self._recent_files[:self._max_recent_files]
        self._update_recent_menu()

    # ================= 菜单槽函数 =================
    def _on_save_watch_data(self):
        """手动保存观察数据"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存观察数据",
            "search_data.json",
            "JSON Files (*.json)"
        )
        if not file_path:
            return

        try:
            data = {
                "watch_panel": self.watch_panel.serialize(),
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self.log_panel.info(f"观察数据已保存到: {file_path}")
            self._add_recent_file(file_path)
        except Exception as e:
            self.log_panel.error(f"保存观察数据失败: {e}")
            QMessageBox.warning(self, "保存失败", str(e))

    def _on_load_watch_data(self, file_path: str = None):
        """手动加载观察数据"""
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "加载观察数据",
                ".",
                "JSON Files (*.json)"
            )
        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if "watch_panel" in data:
                self.watch_panel.deserialize(data["watch_panel"])
            
            self.log_panel.info(f"观察数据已加载: {file_path}")
            self._add_recent_file(file_path)
        except Exception as e:
            self.log_panel.error(f"加载观察数据失败: {e}")
            QMessageBox.warning(self, "加载失败", str(e))

    def _on_export_memory_data(self):
        """导出 BinViewer 当前内存数据为二进制文件"""
        # 获取数据
        data = self.viewer.bin_viewer.get_data()
        if not data:
            QMessageBox.warning(self, "导出失败", "没有数据可导出")
            return

        # 弹出保存对话框
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出内存数据",
            "memory_dump.bin",
            "Binary Files (*.bin);;All Files (*)"
        )
        if not file_path:
            return

        try:
            # 保存二进制数据
            with open(file_path, 'wb') as f:
                f.write(data)
            
            # 同时保存一个 .info 文件记录基址和大小
            info_path = file_path + ".info"
            with open(info_path, 'w', encoding='utf-8') as f:
                f.write(f"# 内存导出信息\n")
                f.write(f"base_address: 0x{self.viewer.bin_viewer._base_address:X}\n")
                f.write(f"size: {len(data)} (0x{len(data):X})\n")
                f.write(f"view_address: 0x{self.viewer._view_address:X}\n")
            
            self.log_panel.info(f"内存数据已导出到: {file_path} ({len(data)} 字节)")
            self.log_panel.debug(f"附带信息: {info_path}")
            
            QMessageBox.information(
                self,
                "导出成功",
                f"数据已保存到:\n{file_path}\n\n"
                f"大小: {len(data)} 字节 (0x{len(data):X})\n"
                f"基址: 0x{self.viewer.bin_viewer._base_address:X}"
            )
        except Exception as e:
            self.log_panel.error(f"导出内存数据失败: {e}")
            QMessageBox.warning(self, "导出失败", str(e))