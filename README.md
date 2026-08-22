# DumpFlow

多快照离线内存对比分析工具（PySide6）。

## 功能

- 加载单个 `.bin` / `.dump` / `.mem` 文件，或按文件名字典序加载整个文件夹
- 时间轴滑块 / ◀ ▶ 按钮 / `←` `→` 快捷键切换快照
- Memory Viewer：每行 16 字节，偏移 + 两个可调类型列；列头右键切换
  Byte / Int16 / Int32 / Int64 / Float / Double / String / Hex，按所选类型整行分组翻译
- 切换快照时，相对上一张快照变化的字节永久标红；「查看 -> 清除高亮」一键清空
- CE 风格精确搜索：首次扫描 + 再次扫描（自动切快照），支持
  Byte / Int16 / Int32 / Int64 / Float / Double / String 类型，以及 `=` `>` `<` `增加` `减少` `变化` `不变`
- 候选列表默认只显示当前快照值，勾选「显示全部快照值」再展开所有快照列与变化趋势
- 任意两份快照差异对比（A/B 值列可切换类型），双击结果跳转到主视图
- `Ctrl+G` 或顶部跳转框按偏移定位

## 运行

```bash
pip install -r requirements.txt
python main.py
```

## 项目结构

```text
main.py
core/
  snapshot_manager.py
  search_engine.py
ui/
  main_window.py
  memory_viewer.py
  timeline_widget.py
  search_panel.py
utils/
  formatter.py
  diff.py
resources/
  style.qss
```
