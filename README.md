# Easy Memory Viewer

基于 PySide6 的实时内存查看与修改工具，通过自研 Cracker 内核驱动读写目标进程内存。

## 功能

- 按进程名附加/分离，定时刷新或手动刷新
- 十六进制内存查看：多格式组（Byte / Int16 / Int32 / Int64 / Float / Double / String / Hex），变化高亮，支持相对地址模式
- CE 风格精确搜索：首次扫描 + 再次扫描
- 树形观察区：父子结构、展开/收起、表达式继承，多选删除/复制
- 修改内存值，地址与数值均支持表达式
- 保存/加载观察数据、导出内存数据、跳转历史
- 表格选中区域支持 Ctrl+C 复制（TSV 格式）

## 运行

```bash
pip install -r requirements.txt
python main.py
```

读写目标进程内存需要管理员权限。驱动安装：

```text
DriverInstall.bat       以管理员身份安装驱动
DriverUninstaller.bat   以管理员身份卸载驱动
```

`main.py` 默认不会自动安装驱动；如需启动时自动安装/卸载，可调用 `main(auto_install=True)`。

## 表达式

观察区表达式采用 CE 风格，例如 `[xxx.exe + 0x123] + 0x111`。

子项表达式以运算符开头时会继承父项的有效表达式：

```text
父项: [xxx.exe + 0x123] + 0x111
子项: + 0x4            =>  ([xxx.exe + 0x123] + 0x111) + 0x4
子项: [yyy.exe + 0x1]  =>  不继承，独立表达式
```

## 项目结构

```text
main.py
common/
  types.py
  expression.py
core/
  memory_tool.py        底层驱动封装
  memory_engine.py      内存交互门面（表达式/读写/批量请求）
  fetcher.py            批量读取请求合并
  search_engine.py      搜索算法
  cracker_client.py     驱动 IOCTL 通信
  cracker_installer.py  驱动安装/卸载
ui/
  main_window.py
  memory_viewer.py
  bin_viewer.py
  search_panel.py
  watch_panel.py
  dialog.py
  log_panel.py
  clipboard_utils.py
resources/
  style.qss
driver/
  cracker.zip
```

## 说明

本项目仅用于学习研究与自有环境调试，请勿用于非法用途。