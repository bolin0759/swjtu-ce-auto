import os
import queue
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, List

from playwright.sync_api import sync_playwright

from .models import AnswerItem, FillResult, QuizOption, QuizQuestion


# 基于 div.list-item 扫描题目
# 单选：每道题有 4 个 div.el-radio-group，各含 1 个 label.el-radio
# 多选：每道题有多个 div.el-checkbox-group，各含 1 个 label.el-checkbox
_SCAN_JS = r"""
() => {
    const questions = [];
    const listItems = Array.from(document.querySelectorAll('div.list-item'));
    // 给所有 label 打全局序号，点击时用
    const allRadioLabels = Array.from(document.querySelectorAll('label.el-radio, label.el-radio-button'));
    const allCbLabels    = Array.from(document.querySelectorAll('label.el-checkbox, label.el-checkbox-button'));
    allRadioLabels.forEach((el, i) => { el._ri = i; });
    allCbLabels.forEach((el, i)    => { el._ci = i; });

    listItems.forEach((item, qIdx) => {
        const radioGroups = Array.from(item.querySelectorAll('div.el-radio-group'));
        const cbGroups    = Array.from(item.querySelectorAll('div.el-checkbox-group'));

        if (radioGroups.length > 0) {
            // 单选题：每个 el-radio-group 是一个选项
            const options = radioGroups.map(g => {
                const lbl = g.querySelector('label.el-radio, label.el-radio-button');
                if (!lbl) return null;
                const textEl = lbl.querySelector('span.el-radio__label, span.el-radio-button__inner');
                const text   = textEl ? textEl.textContent.trim() : lbl.textContent.trim();
                const input  = lbl.querySelector('input[type="radio"]');
                return {
                    text,
                    checked: input ? input.checked : lbl.classList.contains('is-checked'),
                    labelIdx: lbl._ri,
                    kind: 'radio',
                };
            }).filter(Boolean);
            if (options.length > 0) {
                questions.push({ qIdx, q_type: 'single', options });
            }
        } else if (cbGroups.length > 0) {
            // 多选题：每个 el-checkbox-group 是一个选项
            const options = cbGroups.map(g => {
                const lbl = g.querySelector('label.el-checkbox, label.el-checkbox-button');
                if (!lbl) return null;
                const textEl = lbl.querySelector('span.el-checkbox__label');
                const text   = textEl ? textEl.textContent.trim() : lbl.textContent.trim();
                const input  = lbl.querySelector('input[type="checkbox"]');
                return {
                    text,
                    checked: input ? input.checked : lbl.classList.contains('is-checked'),
                    labelIdx: lbl._ci,
                    kind: 'checkbox',
                };
            }).filter(Boolean);
            if (options.length > 0) {
                questions.push({ qIdx, q_type: 'multi', options });
            }
        }
    });

    // 清理临时序号
    allRadioLabels.forEach(el => { delete el._ri; });
    allCbLabels.forEach(el    => { delete el._ci; });
    return questions;
}
"""

# 点击指定 label（radio 或 checkbox），用全局序号定位
# page.evaluate 只接受单个 arg，所以打包成对象传入
# 返回 Promise 以便等 Vue 响应式更新后再读选中状态
_CLICK_JS = r"""
async (args) => {
    const { kind, labelIdx } = args;
    const selector = kind === 'radio'
        ? 'label.el-radio, label.el-radio-button'
        : 'label.el-checkbox, label.el-checkbox-button';
    const labels = Array.from(document.querySelectorAll(selector));
    const lbl = labels[labelIdx];
    if (!lbl) return { ok: false, reason: 'label_not_found' };
    lbl.scrollIntoView({ block: 'center', behavior: 'instant' });
    lbl.click();
    // 等一帧让 Vue 响应式更新 class
    await new Promise(r => requestAnimationFrame(r));
    const input = lbl.querySelector('input');
    return { ok: true, checked: input ? input.checked : lbl.classList.contains('is-checked') };
}
"""

# 重新读取所有 label 的选中状态
_GET_CHECKED_JS = r"""
() => {
    const result = [];
    const radioLabels = Array.from(document.querySelectorAll('label.el-radio, label.el-radio-button'));
    radioLabels.forEach((lbl, idx) => {
        const input = lbl.querySelector('input[type="radio"]');
        result.push({ kind: 'radio', idx, checked: input ? input.checked : lbl.classList.contains('is-checked') });
    });
    const cbLabels = Array.from(document.querySelectorAll('label.el-checkbox, label.el-checkbox-button'));
    cbLabels.forEach((lbl, idx) => {
        const input = lbl.querySelector('input[type="checkbox"]');
        result.push({ kind: 'checkbox', idx, checked: input ? input.checked : lbl.classList.contains('is-checked') });
    });
    return result;
}
"""


class BrowserController:
    def __init__(self, logger):
        self.logger = logger
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        self._task_queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _worker_loop(self):
        while True:
            fn, args, kwargs, done_event, box = self._task_queue.get()
            try:
                box['result'] = fn(*args, **kwargs)
            except Exception as e:
                box['error'] = e
            finally:
                done_event.set()

    def _call_in_worker(self, fn: Callable[..., Any], *args, **kwargs):
        done_event = threading.Event()
        box = {}
        self._task_queue.put((fn, args, kwargs, done_event, box))
        done_event.wait()
        if 'error' in box:
            raise box['error']
        return box.get('result')

    # ── 连接 ──────────────────────────────────────────────────────────────────

    def connect_sync(self, cdp_url: str) -> bool:
        return self._call_in_worker(self._connect_impl, cdp_url)

    def _connect_impl(self, cdp_url: str) -> bool:
        self._ensure_stopped_impl()
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(cdp_url)
        contexts = self.browser.contexts
        if not contexts:
            self.logger.error('未获取到浏览器上下文，请确认 Chrome 已开启远程调试端口')
            return False
        self.context = contexts[0]
        self.page = self._pick_page(self.context.pages)
        if self.page is None:
            self.logger.error('未找到可用标签页，请先打开答题页面')
            return False
        self.logger.info(f'连接成功，当前页面: {self.page.url}')
        return True

    def launch_chrome_with_cdp_sync(self, cdp_url: str, target_url: str = 'https://e-learning.swjtu.edu.cn/') -> bool:
        return self._call_in_worker(self._launch_chrome_impl, cdp_url, target_url)

    def _launch_chrome_impl(self, cdp_url: str, target_url: str) -> bool:
        host, port = self._parse_cdp(cdp_url)
        if self._is_cdp_alive(host, port):
            self.logger.info(f'检测到 CDP 已可用: {host}:{port}')
            return True

        chrome_path = self._detect_chrome_path()
        if not chrome_path:
            self.logger.error('未找到 Chrome 可执行文件，请手动启动带调试端口的浏览器')
            return False

        user_data_dir = os.path.join(os.path.expanduser('~'), '.swjtu-quiz-filler-chrome')
        os.makedirs(user_data_dir, exist_ok=True)

        cmd = [
            chrome_path,
            f'--remote-debugging-port={port}',
            f'--user-data-dir={user_data_dir}',
            '--no-first-run',
            '--no-default-browser-check',
            target_url,
        ]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.logger.error(f'启动 Chrome 失败: {e}')
            return False

        for _ in range(30):
            if self._is_cdp_alive(host, port):
                self.logger.info(f'Chrome 已启动并开放 CDP: {host}:{port}')
                return True
            time.sleep(0.2)

        self.logger.error('Chrome 已启动但 CDP 端口未就绪，请稍后重试')
        return False

    def _detect_chrome_path(self):
        candidates = [
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google/Chrome/Application/chrome.exe'),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google/Chrome/Application/chrome.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google/Chrome/Application/chrome.exe'),
        ]
        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    # ── 扫描题目 ───────────────────────────────────────────────────────────────

    def scan_quiz_sync(self) -> List[QuizQuestion]:
        return self._call_in_worker(self._scan_quiz_impl)

    def _scan_quiz_impl(self) -> List[QuizQuestion]:
        self._ensure_ready_impl()
        raw = self.page.evaluate(_SCAN_JS)
        if not raw:
            self.logger.warn('未发现任何题目（未找到 div.list-item）')
            return []

        questions: List[QuizQuestion] = []
        single_count = multi_count = 0

        for i, q_data in enumerate(raw):
            q_num = i + 1
            options = [
                QuizOption(
                    text=o['text'],
                    checked=o['checked'],
                    global_idx=o['labelIdx'],
                    kind=o['kind'],
                )
                for o in q_data['options']
            ]
            q_type = q_data['q_type']
            questions.append(QuizQuestion(number=q_num, q_type=q_type, options=options))
            if q_type == 'single':
                single_count += 1
            else:
                multi_count += 1

        self.logger.info(f'扫描完成: {single_count} 道单选，{multi_count} 道多选，共 {len(questions)} 道客观题')
        return questions

    # ── 执行点击 ───────────────────────────────────────────────────────────────

    def click_answers_sync(
        self,
        questions: List[QuizQuestion],
        answer_items: List[AnswerItem],
        on_progress: Callable,
        stop_event: threading.Event,
        pause_event: threading.Event,
    ) -> List[FillResult]:
        return self._call_in_worker(
            self._click_answers_impl, questions, answer_items, on_progress, stop_event, pause_event
        )

    def _click_answers_impl(
        self,
        questions: List[QuizQuestion],
        answer_items: List[AnswerItem],
        on_progress: Callable,
        stop_event: threading.Event,
        pause_event: threading.Event,
    ) -> List[FillResult]:
        self._ensure_ready_impl()
        q_map = {q.number: q for q in questions}
        results: List[FillResult] = []
        total = len(answer_items)

        for i, ai in enumerate(answer_items):
            if stop_event.is_set():
                break
            while pause_event.is_set() and not stop_event.is_set():
                time.sleep(0.2)
            if stop_event.is_set():
                break

            q = q_map.get(ai.question_number)
            if q is None:
                self.logger.warn(f'题目 {ai.question_number} 未在页面中找到，跳过')
                continue

            on_progress(i, total, f'题目 {ai.question_number}')
            clicked, not_found = [], []

            for ans_text in ai.answers:
                opt = self._find_option(q, ans_text)
                if opt is None:
                    self.logger.warn(f'题目 {ai.question_number}: 未找到选项 "{ans_text}"')
                    not_found.append(ans_text)
                    continue
                try:
                    res = self.page.evaluate(_CLICK_JS, {'kind': opt.kind, 'labelIdx': opt.global_idx})
                    if res.get('ok'):
                        clicked.append(ans_text)
                        self.logger.info(f'题目 {ai.question_number}: 点击 "{ans_text}" ✓')
                    else:
                        self.logger.warn(f'题目 {ai.question_number}: 点击失败 "{ans_text}" ({res.get("reason")})')
                        not_found.append(ans_text)
                except Exception as e:
                    self.logger.error(f'题目 {ai.question_number}: 点击异常 "{ans_text}" - {e}')
                    not_found.append(ans_text)
                time.sleep(0.05)

            results.append(FillResult(
                question_number=ai.question_number,
                q_type=q.q_type,
                expected=ai.answers,
                clicked=clicked,
                not_found=not_found,
            ))

        on_progress(total, total, '完成')
        return results

    @staticmethod
    def _find_option(q: QuizQuestion, ans_text: str) -> QuizOption | None:
        ans = ans_text.strip()
        # 精确匹配
        for opt in q.options:
            if opt.text.strip() == ans:
                return opt
        # 模糊匹配（包含关系）
        for opt in q.options:
            t = opt.text.strip()
            if ans in t or t in ans:
                return opt
        return None

    # ── 验证选中状态 ───────────────────────────────────────────────────────────

    def verify_sync(self, questions: List[QuizQuestion]) -> List[QuizQuestion]:
        return self._call_in_worker(self._verify_impl, questions)

    def _verify_impl(self, questions: List[QuizQuestion]) -> List[QuizQuestion]:
        self._ensure_ready_impl()
        raw = self.page.evaluate(_GET_CHECKED_JS)
        # 分别建立 radio/checkbox 的 idx->checked 映射
        radio_map = {item['idx']: item['checked'] for item in raw if item['kind'] == 'radio'}
        cb_map    = {item['idx']: item['checked'] for item in raw if item['kind'] == 'checkbox'}

        updated = []
        for q in questions:
            new_opts = []
            for o in q.options:
                m = radio_map if o.kind == 'radio' else cb_map
                new_opts.append(QuizOption(
                    text=o.text,
                    checked=m.get(o.global_idx, o.checked),
                    global_idx=o.global_idx,
                    kind=o.kind,
                ))
            updated.append(QuizQuestion(number=q.number, q_type=q.q_type, options=new_opts))
        return updated

    # ── 内部工具 ───────────────────────────────────────────────────────────────

    def _ensure_stopped_impl(self):
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        self.playwright = self.browser = self.context = self.page = None

    def _ensure_ready_impl(self):
        if not self.context or not self.page:
            raise RuntimeError('浏览器未连接，请先连接')

    def _pick_page(self, pages):
        for p in pages:
            if p.url and p.url != 'about:blank':
                return p
        return pages[0] if pages else None

    def _parse_cdp(self, cdp_url: str):
        parsed = urllib.parse.urlparse(cdp_url)
        return parsed.hostname or '127.0.0.1', parsed.port or 9222

    def _is_cdp_alive(self, host: str, port: int) -> bool:
        try:
            with urllib.request.urlopen(f'http://{host}:{port}/json/version', timeout=1.0) as r:
                return r.status == 200
        except Exception:
            return False
