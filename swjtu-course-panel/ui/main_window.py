import queue
import threading
import customtkinter as ctk

from core.browser_controller import BrowserController
from core.logger import AppLogger
from core.models import RunConfig
from core.task_runner import TaskRunner


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('SWJTU 学习助手 V1')
        self.geometry('980x700')

        ctk.set_appearance_mode('System')
        ctk.set_default_color_theme('blue')

        self.ui_queue = queue.Queue()
        self.items = []
        self.is_paused = False

        self.logger = AppLogger(self._enqueue_log)
        self.browser = BrowserController(self.logger)
        self.runner = TaskRunner(self.logger, self.browser)

        self._init_vars()
        self._build_ui()
        self.after(100, self._drain_ui_queue)

    def _init_vars(self):
        self.cdp_var = ctk.StringVar(value='http://127.0.0.1:9222')
        self.status_filter_var = ctk.StringVar(value='unlearned')
        self.type_filter_var = ctk.StringVar(value='doc')

        self.open_interval_var = ctk.StringVar(value='1200')
        self.close_interval_var = ctk.StringVar(value='1500')
        self.timeout_var = ctk.StringVar(value='8000')

        self.auto_close_var = ctk.BooleanVar(value=True)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self.grid_rowconfigure(5, weight=2)

        self._build_connection_frame()
        self._build_filter_frame()
        self._build_control_frame()
        self._build_progress_frame()
        self._build_items_frame()
        self._build_log_frame()

    def _build_connection_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=12, pady=(12, 6), sticky='ew')
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text='CDP URL').grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkEntry(frame, textvariable=self.cdp_var).grid(row=0, column=1, padx=8, pady=8, sticky='ew')
        ctk.CTkButton(frame, text='连接浏览器', command=self.on_connect).grid(row=0, column=2, padx=8, pady=8)
        ctk.CTkButton(frame, text='刷新条目', command=self.on_refresh_items).grid(row=0, column=3, padx=8, pady=8)

        self.connection_label = ctk.CTkLabel(frame, text='未连接', text_color='#cc4444')
        self.connection_label.grid(row=0, column=4, padx=8, pady=8)

    def _build_filter_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=1, column=0, padx=12, pady=6, sticky='ew')

        ctk.CTkLabel(frame, text='学习状态').grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkOptionMenu(frame, variable=self.status_filter_var, values=['all', 'unlearned', 'learned']).grid(row=0, column=1, padx=8, pady=8)

        ctk.CTkLabel(frame, text='类型').grid(row=0, column=2, padx=8, pady=8)
        ctk.CTkOptionMenu(frame, variable=self.type_filter_var, values=['all', 'doc', 'video']).grid(row=0, column=3, padx=8, pady=8)

        ctk.CTkLabel(frame, text='打开间隔(ms)').grid(row=0, column=4, padx=8, pady=8)
        ctk.CTkEntry(frame, width=90, textvariable=self.open_interval_var).grid(row=0, column=5, padx=8, pady=8)

        ctk.CTkCheckBox(frame, text='自动关闭标签页', variable=self.auto_close_var).grid(row=0, column=6, padx=8, pady=8)

        ctk.CTkLabel(frame, text='关闭间隔(ms)').grid(row=0, column=7, padx=8, pady=8)
        ctk.CTkEntry(frame, width=90, textvariable=self.close_interval_var).grid(row=0, column=8, padx=8, pady=8)

        ctk.CTkLabel(frame, text='单项超时(ms)').grid(row=0, column=9, padx=8, pady=8)
        ctk.CTkEntry(frame, width=90, textvariable=self.timeout_var).grid(row=0, column=10, padx=8, pady=8)

    def _build_control_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=2, column=0, padx=12, pady=6, sticky='ew')

        self.start_btn = ctk.CTkButton(frame, text='开始', command=self.on_start)
        self.start_btn.grid(row=0, column=0, padx=8, pady=8)

        self.pause_btn = ctk.CTkButton(frame, text='暂停', command=self.on_pause)
        self.pause_btn.grid(row=0, column=1, padx=8, pady=8)

        self.resume_btn = ctk.CTkButton(frame, text='继续', command=self.on_resume)
        self.resume_btn.grid(row=0, column=2, padx=8, pady=8)

        self.stop_btn = ctk.CTkButton(frame, text='停止', command=self.on_stop)
        self.stop_btn.grid(row=0, column=3, padx=8, pady=8)

    def _build_progress_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=3, column=0, padx=12, pady=6, sticky='ew')
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text='进度').grid(row=0, column=0, padx=8, pady=8)
        self.progress_bar = ctk.CTkProgressBar(frame)
        self.progress_bar.grid(row=0, column=1, padx=8, pady=8, sticky='ew')
        self.progress_bar.set(0)

        self.progress_label = ctk.CTkLabel(frame, text='0 / 0')
        self.progress_label.grid(row=0, column=2, padx=8, pady=8)

        self.current_label = ctk.CTkLabel(frame, text='当前: -')
        self.current_label.grid(row=0, column=3, padx=8, pady=8)

    def _build_items_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=4, column=0, padx=12, pady=6, sticky='nsew')
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(frame, text='当前课程筛选结果').grid(row=0, column=0, padx=8, pady=(8, 0), sticky='w')
        self.items_text = ctk.CTkTextbox(frame)
        self.items_text.grid(row=1, column=0, padx=8, pady=8, sticky='nsew')

    def _build_log_frame(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=5, column=0, padx=12, pady=(6, 12), sticky='nsew')
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(frame, text='日志').grid(row=0, column=0, padx=8, pady=(8, 0), sticky='w')
        self.log_text = ctk.CTkTextbox(frame)
        self.log_text.grid(row=1, column=0, padx=8, pady=8, sticky='nsew')

    def _build_config(self) -> RunConfig:
        def _to_int(v: str, fallback: int, minimum: int = 1):
            try:
                val = int(v)
                return max(minimum, val)
            except Exception:
                return fallback

        return RunConfig(
            status_filter=self.status_filter_var.get(),
            type_filter=self.type_filter_var.get(),
            open_interval_ms=_to_int(self.open_interval_var.get(), 1200, 100),
            auto_close=self.auto_close_var.get(),
            close_interval_ms=_to_int(self.close_interval_var.get(), 1500, 100),
            item_timeout_ms=_to_int(self.timeout_var.get(), 8000, 500),
        )

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

    def on_refresh_items(self):
        cfg = self._build_config()

        def _task():
            try:
                items = self.browser.get_current_course_items_sync(cfg)
                self.ui_queue.put(('items', items))
            except Exception as e:
                self._enqueue_log(f'[ERROR] 刷新条目失败: {e}')

        threading.Thread(target=_task, daemon=True).start()

    def on_start(self):
        if self.runner.is_running():
            self._enqueue_log('[WARN] 任务已在运行')
            return

        if not self.items:
            self._enqueue_log('[WARN] 请先刷新条目并确认有可执行项')
            return

        cfg = self._build_config()

        def _on_progress(done: int, total: int, current: str):
            self.ui_queue.put(('progress', done, total, current))

        def _on_finished():
            self.ui_queue.put(('finished',))

        self.runner.start(self.items, cfg, _on_progress, _on_finished)

    def on_pause(self):
        self.runner.pause()

    def on_resume(self):
        self.runner.resume()

    def on_stop(self):
        self.runner.stop()

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
                    self.connection_label.configure(text='已连接', text_color='#33aa55')
                else:
                    self.connection_label.configure(text='连接失败', text_color='#cc4444')
            elif kind == 'items':
                self.items = event[1]
                self._render_items()
                self._append_log(f'[INFO] 已获取条目: {len(self.items)} 项')
            elif kind == 'progress':
                done, total, current = event[1], event[2], event[3]
                ratio = (done / total) if total else 0
                self.progress_bar.set(ratio)
                self.progress_label.configure(text=f'{done} / {total}')
                self.current_label.configure(text=f'当前: {current}')
            elif kind == 'finished':
                self._append_log('[INFO] 执行流程已结束')

        self.after(100, self._drain_ui_queue)

    def _render_items(self):
        self.items_text.delete('1.0', 'end')
        if not self.items:
            self.items_text.insert('end', '无匹配条目\n')
            return

        for idx, item in enumerate(self.items, start=1):
            learned = '已学习' if item.learned else '未学习'
            self.items_text.insert('end', f'{idx:03d}. [{item.item_type}] [{learned}] {item.name}\n')

    def _append_log(self, line: str):
        self.log_text.insert('end', line + '\n')
        self.log_text.see('end')
