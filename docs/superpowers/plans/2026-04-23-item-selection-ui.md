# Item Selection UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在条目列表中支持复选执行（默认全不选、全选/全不选/反选、仅执行勾选项），满足“手动只测5条”等场景。

**Architecture:** 仅改动 `ui/main_window.py` 的展示与选择层。将原文本框列表替换为滚动复选框列表，维护 `BooleanVar` 与 `CourseItem` 的同索引映射，`on_start()` 只提取勾选项传入既有 `TaskRunner`。浏览器连接与执行核心逻辑不改。

**Tech Stack:** Python 3.12、CustomTkinter、现有 TaskRunner/BrowserController

---

### Task 1: 列表区域改为复选框容器

**Files:**
- Modify: `swjtu-course-python/ui/main_window.py`

- [ ] **Step 1: 在 `__init__` 初始化选择状态容器**

将：
```python
self.ui_queue = queue.Queue()
self.items = []
```
替换为：
```python
self.ui_queue = queue.Queue()
self.items = []
self.item_rows = []
self.item_check_vars = []
self.item_checkboxes = []
```

- [ ] **Step 2: 替换条目区域 UI 结构为操作栏 + 可滚动复选框容器**

将 `_build_items_frame()` 中：
```python
ctk.CTkLabel(frame, text='当前课程筛选结果').grid(row=0, column=0, padx=8, pady=(8, 0), sticky='w')
self.items_text = ctk.CTkTextbox(frame)
self.items_text.grid(row=1, column=0, padx=8, pady=8, sticky='nsew')
```
替换为：
```python
header = ctk.CTkFrame(frame, fg_color='transparent')
header.grid(row=0, column=0, padx=8, pady=(8, 4), sticky='ew')
header.grid_columnconfigure(0, weight=1)

ctk.CTkLabel(header, text='当前课程筛选结果（可勾选）').grid(row=0, column=0, sticky='w')
ctk.CTkButton(header, width=70, text='全选', command=self.on_select_all).grid(row=0, column=1, padx=(6, 0))
ctk.CTkButton(header, width=80, text='全不选', command=self.on_select_none).grid(row=0, column=2, padx=(6, 0))
ctk.CTkButton(header, width=70, text='反选', command=self.on_select_invert).grid(row=0, column=3, padx=(6, 0))

self.items_scroll = ctk.CTkScrollableFrame(frame)
self.items_scroll.grid(row=1, column=0, padx=8, pady=8, sticky='nsew')
self.items_scroll.grid_columnconfigure(0, weight=1)
```

- [ ] **Step 3: 新增清空列表容器方法**

在类中新增：
```python
def _clear_items_widgets(self):
    for widget in self.items_scroll.winfo_children():
        widget.destroy()
    self.item_check_vars = []
    self.item_checkboxes = []
    self.item_rows = []
```

- [ ] **Step 4: 语法检查**

Run: `python -m py_compile E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py`
Expected: 无输出（PASS）

- [ ] **Step 5: Commit**

```bash
git add E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
git commit -m "feat: render selectable item list with checkbox container"
```

### Task 2: 渲染复选框 + 默认全不选

**Files:**
- Modify: `swjtu-course-python/ui/main_window.py`

- [ ] **Step 1: 重写 `_render_items()` 为复选框渲染**

将 `_render_items()` 替换为：
```python
def _render_items(self):
    self._clear_items_widgets()

    if not self.items:
        ctk.CTkLabel(self.items_scroll, text='无匹配条目').grid(row=0, column=0, sticky='w', padx=6, pady=6)
        return

    self.item_rows = list(self.items)
    for idx, item in enumerate(self.item_rows, start=1):
        learned = '已学习' if item.learned else '未学习'
        text = f'{idx:03d}. [{item.item_type}] [{learned}] {item.name}'
        var = ctk.BooleanVar(value=False)
        cb = ctk.CTkCheckBox(self.items_scroll, text=text, variable=var)
        cb.grid(row=idx - 1, column=0, sticky='w', padx=6, pady=4)
        self.item_check_vars.append(var)
        self.item_checkboxes.append(cb)
```

- [ ] **Step 2: 刷新后日志补充可选总数**

在 `_drain_ui_queue()` 的 `kind == 'items'` 分支，将：
```python
self._append_log(f'[INFO] 已获取条目: {len(self.items)} 项')
```
替换为：
```python
self._append_log(f'[INFO] 已获取条目: {len(self.items)} 项（默认全不勾选）')
```

- [ ] **Step 3: 手工失败/通过验证（TDD风格）**

先验证旧行为失败（改前）：
1. 刷新条目后看不到复选框（FAIL，旧行为）

再验证改后通过：
1. 刷新条目后每条前有复选框
2. 默认全部未勾选

- [ ] **Step 4: Commit**

```bash
git add E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
git commit -m "feat: render items as unchecked checkboxes by default"
```

### Task 3: 快捷按钮逻辑（全选/全不选/反选）

**Files:**
- Modify: `swjtu-course-python/ui/main_window.py`

- [ ] **Step 1: 新增三个操作方法**

在类中新增：
```python
def on_select_all(self):
    for var in self.item_check_vars:
        var.set(True)
    self._append_log('[INFO] 已全选当前列表')


def on_select_none(self):
    for var in self.item_check_vars:
        var.set(False)
    self._append_log('[INFO] 已全不选当前列表')


def on_select_invert(self):
    for var in self.item_check_vars:
        var.set(not var.get())
    self._append_log('[INFO] 已反选当前列表')
```

- [ ] **Step 2: 手工验证**

1. 点击全选 → 所有复选框应为选中
2. 点击全不选 → 所有复选框应为未选中
3. 连续点击反选两次 → 状态应恢复

- [ ] **Step 3: Commit**

```bash
git add E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
git commit -m "feat: add select-all none invert actions"
```

### Task 4: 开始仅执行勾选条目 + 0勾选阻断

**Files:**
- Modify: `swjtu-course-python/ui/main_window.py`

- [ ] **Step 1: 新增勾选项提取方法**

在类中新增：
```python
def _get_selected_items(self):
    selected = []
    for idx, var in enumerate(self.item_check_vars):
        if var.get() and idx < len(self.item_rows):
            selected.append(self.item_rows[idx])
    return selected
```

- [ ] **Step 2: 修改 `on_start()` 只执行勾选项**

将 `on_start()` 中从 `if not self.items:` 到 `self.runner.start(...)` 的逻辑替换为：
```python
if not self.item_rows:
    self._enqueue_log('[WARN] 请先刷新条目并确认有可执行项')
    return

selected_items = self._get_selected_items()
if not selected_items:
    self._enqueue_log('[WARN] 请先勾选要执行的条目')
    return

cfg = self._build_config()
self._enqueue_log(f'[INFO] 已选择 {len(selected_items)}/{len(self.item_rows)} 条，开始执行')


def _on_progress(done: int, total: int, current: str):
    self.ui_queue.put(('progress', done, total, current))


def _on_finished():
    self.ui_queue.put(('finished',))

self.runner.start(selected_items, cfg, _on_progress, _on_finished)
```

- [ ] **Step 3: 手工验证（关键）**

1. 不勾选直接开始 → 提示“请先勾选要执行的条目”，任务不启动
2. 只勾 5 条开始 → 进度显示 `0/5 ... 5/5`
3. 执行日志首行显示“已选择 5/总数 条，开始执行”

- [ ] **Step 4: Commit**

```bash
git add E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
git commit -m "feat: run only selected items with empty-selection guard"
```

### Task 5: 回归验证与收尾

**Files:**
- Modify: `swjtu-course-python/ui/main_window.py`（如有必要的小修）

- [ ] **Step 1: 语法与启动验证**

Run:
```bash
python -m py_compile E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
python E:/projects/26test0422-study/swjtu-course-python/app.py
```
Expected:
- 编译无错误
- 窗口正常打开

- [ ] **Step 2: 端到端手工回归**

1. 一键启动并连接
2. 刷新条目
3. 全选/全不选/反选
4. 勾选5条开始执行
5. 暂停/继续/停止确认不回归

- [ ] **Step 3: 最终提交**

```bash
git add E:/projects/26test0422-study/swjtu-course-python/ui/main_window.py
git commit -m "feat: add checkbox-based item selection workflow"
```

- [ ] **Step 4: 交付说明**

记录以下内容供验收：
- 复选框默认全不选截图
- 仅勾选5条执行日志
- 进度条分母为5的截图
