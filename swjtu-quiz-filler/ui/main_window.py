import queue
import threading
import tkinter as tk
from tkinter import filedialog
from typing import List, Optional

import customtkinter as ctk

from core.answer_parser import parse_answer_file
from core.browser_controller import BrowserController
from core.logger import AppLogger
from core.models import AnswerItem, FillResult, QuizQuestion
from core.task_runner import TaskRunner


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('SWJTU 答题助手 V1')
        self.geometry('1100x750')

        ctk.set_appearance_mode('System')
        ctk.set_default_color_theme('blue')

        self.ui_queue = queue.Queue()
        self.questions: List[QuizQuestion] = []
        self.answer_items: List[AnswerItem] = []
        self.results: List[FillResult] = []
        self._result_rows: list = []  # (frame, label_status) 用于着色

        self.logger = AppLogger(self._enqueue_log)
        self.browser = BrowserController(self.logger)
        self.runner = TaskRunner(self.logger, self.browser)

        self._init_vars()
        self._build_ui()
        self.after(100, self._drain_ui_queue)

    def _init_vars(self):
        self.cdp_var = ctk.StringVar(value='http://127.0.0.1:9222')
        self.file_var = ctk.StringVar(value='')

    # ── 界面构建 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_connection_frame()
        self._build_file_frame()
        self._build_control_frame()
        self._build_content_frame()

    def _build_connection_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=12, pady=(12, 6), sticky='ew')
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text='CDP URL').grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkEntry(frame, textvariable=self.cdp_var).grid(row=0, column=1, padx=8, pady=8, sticky='ew')
        ctk.CTkButton(frame, text='一键启动并连接', command=self.on_launch_and_connect).grid(row=0, column=2, padx=8, pady=8)
        ctk.CTkButton(frame, text='连接浏览器', command=self.on_connect).grid(row=0, column=3, padx=8, pady=8)

        self.conn_label = ctk.CTkLabel(frame, text='未连接', text_color='#cc4444')
        self.conn_label.grid(row=0, column=4, padx=8, pady=8)

    def _build_file_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=1, column=0, padx=12, pady=6, sticky='ew')
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text='答案文件').grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkEntry(frame, textvariable=self.file_var).grid(row=0, column=1, padx=8, pady=8, sticky='ew')
        ctk.CTkButton(frame, text='浏览', width=60, command=self.on_browse_file).grid(row=0, column=2, padx=(0, 4), pady=8)
        ctk.CTkButton(frame, text='加载答案', command=self.on_load_answers).grid(row=0, column=3, padx=8, pady=8)

        self.answers_label = ctk.CTkLabel(frame, text='未加载')
        self.answers_label.grid(row=0, column=4, padx=8, pady=8)

    def _build_control_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=2, column=0, padx=12, pady=6, sticky='ew')
        frame.grid_columnconfigure(6, weight=1)

        ctk.CTkButton(frame, text='扫描页面', command=self.on_scan).grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkButton(frame, text='开始答题', command=self.on_start).grid(row=0, column=1, padx=8, pady=8)
        ctk.CTkButton(frame, text='暂停', command=self.on_pause).grid(row=0, column=2, padx=8, pady=8)
        ctk.CTkButton(frame, text='继续', command=self.on_resume).grid(row=0, column=3, padx=8, pady=8)
        ctk.CTkButton(frame, text='停止', command=self.on_stop).grid(row=0, column=4, padx=8, pady=8)
        ctk.CTkButton(frame, text='验证结果', command=self.on_verify).grid(row=0, column=5, padx=8, pady=8)

        # 进度区放在同一行右侧
        self.progress_bar = ctk.CTkProgressBar(frame, width=200)
        self.progress_bar.grid(row=0, column=6, padx=8, pady=8, sticky='ew')
        self.progress_bar.set(0)
        self.progress_label = ctk.CTkLabel(frame, text='0 / 0')
        self.progress_label.grid(row=0, column=7, padx=(0, 8), pady=8)

    def _build_content_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=3, column=0, padx=12, pady=(6, 12), sticky='nsew')
        frame.grid_columnconfigure(0, weight=3)
        frame.grid_columnconfigure(1, weight=2)
        frame.grid_rowconfigure(0, weight=1)

        self._build_result_panel(frame)
        self._build_log_panel(frame)

    def _build_result_panel(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.grid(row=0, column=0, padx=(0, 6), pady=0, sticky='nsew')
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(frame, fg_color='transparent')
        header.grid(row=0, column=0, padx=8, pady=(8, 4), sticky='ew')
        ctk.CTkLabel(header, text='题目答题情况  ✓=成功  ✗=有未匹配  -=待执行').pack(side='left')

        self.result_scroll = ctk.CTkScrollableFrame(frame)
        self.result_scroll.grid(row=1, column=0, padx=8, pady=8, sticky='nsew')
        self.result_scroll.grid_columnconfigure(0, weight=1)

    def _build_log_panel(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.grid(row=0, column=1, padx=(6, 0), pady=0, sticky='nsew')
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(frame, text='日志').grid(row=0, column=0, padx=8, pady=(8, 0), sticky='w')
        self.log_text = ctk.CTkTextbox(frame)
        self.log_text.grid(row=1, column=0, padx=8, pady=8, sticky='nsew')

    # ── 事件处理 ───────────────────────────────────────────────────────────────

    def on_launch_and_connect(self):
        cdp = self.cdp_var.get().strip()

        def _task():
            try:
                launched = self.browser.launch_chrome_with_cdp_sync(cdp)
                if not launched:
                    self.ui_queue.put(('connected', False))
                    return
                ok = self.browser.connect_sync(cdp)
                self.ui_queue.put(('connected', ok))
            except Exception as e:
                self._enqueue_log(f'[ERROR] 一键启动并连接失败: {e}')
                self.ui_queue.put(('connected', False))

        threading.Thread(target=_task, daemon=True).start()

    def on_connect(self):
        cdp = self.cdp_var.get().strip()

        def _task():
            try:
                ok = self.browser.connect_sync(cdp)
                self.ui_queue.put(('connected', ok))
            except Exception as e:
                self._enqueue_log(f'[ERROR] 连接失败: {e}')
                self.ui_queue.put(('connected', False))

        threading.Thread(target=_task, daemon=True).start()

    def on_browse_file(self):
        path = filedialog.askopenfilename(
            title='选择答案文件',
            filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')],
        )
        if path:
            self.file_var.set(path)

    def on_load_answers(self):
        path = self.file_var.get().strip()
        if not path:
            self._enqueue_log('[WARN] 请先选择答案文件')
            return
        try:
            self.answer_items = parse_answer_file(path)
            self._enqueue_log(f'[INFO] 已加载 {len(self.answer_items)} 道题的答案')
            self.ui_queue.put(('answers_loaded', len(self.answer_items)))
        except Exception as e:
            self._enqueue_log(f'[ERROR] 加载答案失败: {e}')

    def on_scan(self):
        def _task():
            try:
                qs = self.browser.scan_quiz_sync()
                self.ui_queue.put(('scanned', qs))
            except Exception as e:
                self._enqueue_log(f'[ERROR] 扫描失败: {e}')

        threading.Thread(target=_task, daemon=True).start()

    def on_start(self):
        if self.runner.is_running():
            self._enqueue_log('[WARN] 任务已在运行')
            return
        if not self.questions:
            self._enqueue_log('[WARN] 请先扫描页面')
            return
        if not self.answer_items:
            self._enqueue_log('[WARN] 请先加载答案文件')
            return

        def _on_progress(done: int, total: int, current: str):
            self.ui_queue.put(('progress', done, total, current))

        def _on_finished(results: List[FillResult]):
            self.ui_queue.put(('finished', results))

        self.runner.start(self.questions, self.answer_items, _on_progress, _on_finished)

    def on_pause(self):
        self.runner.pause()

    def on_resume(self):
        self.runner.resume()

    def on_stop(self):
        self.runner.stop()

    def on_verify(self):
        if not self.questions:
            self._enqueue_log('[WARN] 请先扫描页面')
            return

        def _task():
            try:
                updated = self.browser.verify_sync(self.questions)
                self.ui_queue.put(('verified', updated))
            except Exception as e:
                self._enqueue_log(f'[ERROR] 验证失败: {e}')

        threading.Thread(target=_task, daemon=True).start()

    # ── UI 队列处理 ────────────────────────────────────────────────────────────

    def _enqueue_log(self, message: str):
        self.ui_queue.put(('log', message))

    def _drain_ui_queue(self):
        while True:
            try:
                event = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            kind = event[0]

            if kind == 'log':
                self._append_log(event[1])

            elif kind == 'connected':
                ok = event[1]
                if ok:
                    self.conn_label.configure(text='已连接', text_color='#33aa55')
                else:
                    self.conn_label.configure(text='连接失败', text_color='#cc4444')

            elif kind == 'answers_loaded':
                self.answers_label.configure(text=f'已加载 {event[1]} 题')

            elif kind == 'scanned':
                self.questions = event[1]
                self._render_question_list()

            elif kind == 'progress':
                done, total, current = event[1], event[2], event[3]
                ratio = (done / total) if total else 0
                self.progress_bar.set(ratio)
                self.progress_label.configure(text=f'{done} / {total}')

            elif kind == 'finished':
                self.results = event[1]
                self._apply_results_to_list()
                ok_count = sum(1 for r in self.results if r.success)
                total = len(self.results)
                self._append_log(f'[INFO] 答题完成: {ok_count}/{total} 题全部匹配，请核查后手动提交')

            elif kind == 'verified':
                self.questions = event[1]
                self._apply_verify_to_list()
                self._append_log('[INFO] 验证完成，已更新选中状态显示')

        self.after(100, self._drain_ui_queue)

    # ── 结果列表渲染 ───────────────────────────────────────────────────────────

    def _render_question_list(self):
        for widget in self.result_scroll.winfo_children():
            widget.destroy()
        self._result_rows.clear()

        # 建立答案查找表 question_number -> answers
        ans_map = {ai.question_number: ai.answers for ai in self.answer_items}

        for q in self.questions:
            ans = ans_map.get(q.number, [])
            ans_text = '；'.join(ans) if ans else '（无答案数据）'
            type_label = '单选' if q.q_type == 'single' else '多选'
            row_text = f'{q.number:03d} [{type_label}]  答案: {ans_text}'

            row_frame = ctk.CTkFrame(self.result_scroll, fg_color='transparent')
            row_frame.grid(row=q.number - 1, column=0, sticky='ew', padx=4, pady=2)
            row_frame.grid_columnconfigure(0, weight=1)

            lbl_text = ctk.CTkLabel(row_frame, text=row_text, anchor='w', justify='left')
            lbl_text.grid(row=0, column=0, sticky='ew')

            lbl_status = ctk.CTkLabel(row_frame, text=' - ', width=30, text_color='gray')
            lbl_status.grid(row=0, column=1, padx=(4, 0))

            self._result_rows.append((q.number, lbl_status))

        self._append_log(f'[INFO] 已渲染 {len(self.questions)} 道题目列表')

    def _apply_results_to_list(self):
        result_map = {r.question_number: r for r in self.results}
        status_map = {q_num: lbl for q_num, lbl in self._result_rows}

        for q_num, lbl in self._result_rows:
            r = result_map.get(q_num)
            if r is None:
                continue
            if r.success:
                lbl.configure(text=' ✓ ', text_color='#33aa55')
            else:
                detail = '、'.join(r.not_found)
                lbl.configure(text=f' ✗ 未匹配: {detail}', text_color='#cc4444')

    def _apply_verify_to_list(self):
        # 验证后：根据实际选中状态 + 答案对比显示
        ans_map = {ai.question_number: set(ai.answers) for ai in self.answer_items}
        q_map = {q.number: q for q in self.questions}

        for q_num, lbl in self._result_rows:
            q = q_map.get(q_num)
            expected = ans_map.get(q_num)
            if q is None or not expected:
                continue

            selected_texts = {o.text.strip() for o in q.options if o.checked}
            # 模糊比对：答案文本与选项文本包含关系
            matched = set()
            for exp in expected:
                for sel in selected_texts:
                    if exp.strip() == sel or exp.strip() in sel or sel in exp.strip():
                        matched.add(exp)
                        break

            if matched == expected:
                lbl.configure(text=' ✓ ', text_color='#33aa55')
            else:
                unmatched = expected - matched
                lbl.configure(text=f' ✗ 未选: {"、".join(unmatched)}', text_color='#cc4444')

    def _append_log(self, line: str):
        self.log_text.insert('end', line + '\n')
        self.log_text.see('end')
