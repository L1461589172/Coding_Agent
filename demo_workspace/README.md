# Calculator Bug Demo

这是 Coding Agent 的 M4 可重复演示工作区。

任务目标：修复 `calculator.py` 中的 `divide`，使除数为零时返回 `None`，且保持普通除法行为不变。不得修改测试。

初始状态必须失败：

```powershell
python -m pytest -q
```

预期 Agent 会先查看源码与测试，只修改实现，然后再次运行 pytest。`scripts/run_m4_demo.py` 会在每轮真实模型验收前恢复这个初始 Bug，并在结束后再次恢复，确保现场 Demo 可重复。
