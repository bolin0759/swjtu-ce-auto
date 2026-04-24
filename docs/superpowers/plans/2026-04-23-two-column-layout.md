# Two-Column Content Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将“筛选结果”和“日志”调整为原位置并列双栏（60/40），保持顶部区域不变并持续并列显示。

**Architecture:** 仅调整 `MainWindow` 的网格布局与内容区域组装方式：新增内容容器承载左（筛选结果）右（日志）子框。保留连接/筛选/控制/进度原位置和已有业务逻辑，避免触碰执行链路与数据流。

**Tech Stack:** Python 3.12、CustomTkinter、现有 MainWindow 网格布局

---

### Task 1: 重构主网格，预留单一内容区

**Files:**
- Modify: `swjtu-course-python/ui/main_window.py`

- [ ] **Step 1: 写“失败前提”检查（手工）**

运行程序观察当前行为（改前）：
1. 筛选结果在 row=4
2. 日志在 row=5
3. 两者是上下布局（这就是待修复“失败前提”）

- [ ] **Step 2: 将主网格改为单一内容区承载**

在 `_build_ui()` 中将：
```python
self.grid_rowconfigure(4, weight=1)
self.grid_rowconfigure(5, weight=2)

self._build_connection_frame()
self._build_filter_frame()
self._build_control_frame()
self._build_progress_frame()
self._build_items_frame()
self._build_log_frame()
```
替换为：
```python
self.grid_rowconfigure(4, weight=1)
self.grid_rowconfigure(5, weight=0)

self._build_connection_frame()
self._build_filter_frame()
self._build_control_frame()
self._build_progress_frame()
self._build_content_frame()
```

- [ ] **Step 3: 新增内容容器方法 `_build_content_frame`**

在类中新增：
```python
def _build_content_frame(self):
    frame = ctk.CTkFrame(self)
    frame.grid(row=4, column=0, padx=12, pady=(6, 12), sticky='nsew')
    frame.grid_columnconfigure(0, weight=3)  # 左 60%
    frame.grid_columnconfigure(1, weight=2)  # 右 40%
    frame.grid_rowconfigure(0, weight=1)

    self._build_items_frame(frame, 0, 0)
    self._build_log_frame(frame, 0, 1)
```

- [ ] **Step 4: 运行语法校验**

Run: `python -m py_compile E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py`  
Expected: 无输出（PASS）

- [ ] **Step 5: Commit**

```bash
git add E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
git commit -m "refactor: introduce shared content frame for two-column layout"
```

### Task 2: 调整筛选结果与日志构建函数为可嵌入子容器

**Files:**
- Modify: `swjtu-course-python/ui/main_window.py`

- [ ] **Step 1: 修改 `_build_items_frame` 函数签名与挂载位置**

将：
```python
def _build_items_frame(self):
    frame = ctk.CTkFrame(self)
    frame.grid(row=4, column=0, padx=12, pady=6, sticky='nsew')
```
替换为：
```python
def _build_items_frame(self, parent, row, col):
    frame = ctk.CTkFrame(parent)
    frame.grid(row=row, column=col, padx=(0, 6), pady=0, sticky='nsew')
```

其余内部复选框/滚动区逻辑保持不变。

- [ ] **Step 2: 修改 `_build_log_frame` 函数签名与挂载位置**

将：
```python
def _build_log_frame(self):
    frame = ctk.CTkFrame(self)
    frame.grid(row=5, column=0, padx=12, pady=(6, 12), sticky='nsew')
```
替换为：
```python
def _build_log_frame(self, parent, row, col):
    frame = ctk.CTkFrame(parent)
    frame.grid(row=row, column=col, padx=(6, 0), pady=0, sticky='nsew')
```

日志文本框内部实现保持不变。

- [ ] **Step 3: 为子容器启用伸缩配置**

在上述两个方法内均保留：
```python
frame.grid_columnconfigure(0, weight=1)
frame.grid_rowconfigure(1, weight=1)
```
确保内部滚动区在窗口缩放时可用。

- [ ] **Step 4: 语法校验**

Run: `python -m py_compile E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py`  
Expected: 无输出（PASS）

- [ ] **Step 5: Commit**

```bash
git add E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
git commit -m "feat: mount items and logs as side-by-side child panels"
```

### Task 3: 验证 60/40 并列与行为不回归

**Files:**
- Modify: `swjtu-course-python/ui/main_window.py`（仅在发现小问题时调整）

- [ ] **Step 1: 运行程序做布局验证（手工）**

Run: `python E:/projects/26test0422-study/swjtu-course-python/app.py`

验证项：
1. 顶部四块区域位置不变
2. 下方变为并列双栏（左筛选结果、右日志）
3. 两栏比例视觉接近 60/40
4. 缩窄窗口时两栏保持并列不换行

- [ ] **Step 2: 运行流程回归（手工）**

在程序中执行：
1. 一键启动并连接
2. 刷新条目
3. 勾选若干条并开始
4. 查看左侧列表/右侧日志滚动是否都正常

预期：仅布局变化，功能行为不变。

- [ ] **Step 3: 如需微调，限定于间距与grid参数**

允许调整项示例：
- `padx=(0,6)/(6,0)`
- `pady`
- `grid_columnconfigure` 权重

禁止改动项：
- 执行逻辑（start/pause/resume/stop）
- 浏览器连接与抓取逻辑

- [ ] **Step 4: 最终语法检查**

Run: `python -m py_compile E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py`  
Expected: 无输出（PASS）

- [ ] **Step 5: Commit**

```bash
git add E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
git commit -m "style: finalize two-column content layout with 60-40 split"
```
