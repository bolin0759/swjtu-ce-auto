import os
import queue
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, List

from playwright.sync_api import sync_playwright

from .models import CourseItem, OpenResult, RunConfig


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
            self.logger.error('未找到可用标签页，请先打开课程页面')
            return False
        self.logger.info(f'连接成功，当前页面: {self.page.url}')
        return True

    def launch_chrome_with_cdp_sync(self, cdp_url: str, target_url: str = 'https://e-learning.swjtu.edu.cn/') -> bool:
        host, port = self._parse_cdp(cdp_url)
        if self._is_cdp_alive(host, port):
            self.logger.info(f'检测到 CDP 已可用: {host}:{port}')
            return True

        chrome_path = self._detect_chrome_path()
        if not chrome_path:
            self.logger.error('未找到 Chrome 可执行文件，请先安装 Chrome 或手动启动带调试端口的浏览器')
            return False

        user_data_dir = os.path.join(os.path.expanduser('~'), '.swjtu-course-python-chrome')
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

    def get_current_course_items_sync(self, config: RunConfig) -> List[CourseItem]:
        return self._call_in_worker(self._get_current_course_items_impl, config)

    def _get_current_course_items_impl(self, config: RunConfig) -> List[CourseItem]:
        self._ensure_ready_impl()
        rows = self.page.evaluate(
            r"""() => {
                const items = Array.from(document.querySelectorAll('.list-item'));
                return items.map((el, idx) => {
                    const nameEl = el.querySelector('.name');
                    const tagEl = el.querySelector('.tag');
                    const titleEl = el.querySelector('.titel');
                    if (!nameEl || !tagEl) return null;
                    const learned = tagEl.classList.contains('active');
                    const rawName = (nameEl.textContent || '').trim();
                    const name = rawName.replace(/\s*\(\d{2}:\d{2}:\d{2}\)\s*$/, '');
                    const isVideo = (titleEl?.textContent || '').includes('视频');
                    return {
                        name,
                        learned,
                        item_type: isVideo ? 'video' : 'doc',
                        row_index: idx,
                    };
                }).filter(Boolean);
            }"""
        )

        items = [CourseItem(**row) for row in rows]
        filtered = []
        for item in items:
            type_pass = config.type_filter == 'all' or item.item_type == config.type_filter
            status_pass = (
                config.status_filter == 'all'
                or (config.status_filter == 'unlearned' and not item.learned)
                or (config.status_filter == 'learned' and item.learned)
            )
            if type_pass and status_pass:
                filtered.append(item)
        return filtered

    def open_item_by_real_click(self, item: CourseItem, timeout_ms: int) -> OpenResult:
        return self._call_in_worker(self._open_item_by_real_click_impl, item, timeout_ms)

    def _open_item_by_real_click_impl(self, item: CourseItem, timeout_ms: int) -> OpenResult:
        self._ensure_ready_impl()
        pages_before = list(self.context.pages)
        before_ids = {id(p) for p in pages_before}

        try:
            self.page.evaluate(
                """(rowIndex) => {
                    const rows = document.querySelectorAll('.list-item');
                    const row = rows[rowIndex];
                    if (!row) throw new Error('row_not_found');
                    row.scrollIntoView({ block: 'center' });
                    const title = row.querySelector('.name') || row;
                    title.click();
                }""",
                item.row_index,
            )
        except Exception as e:
            return OpenResult(success=False, reason=f'点击失败: {e}')

        waited = 0
        step = 100
        while waited < timeout_ms:
            pages_after = list(self.context.pages)
            for idx, p in enumerate(pages_after):
                if id(p) not in before_ids:
                    return OpenResult(success=True, opened_page_index=idx, opened_page_id=id(p))
            time.sleep(step / 1000)
            waited += step

        return OpenResult(success=True, reason='未检测到新标签页，视为已点击')

    def close_page(self, page_index: int) -> bool:
        return self._call_in_worker(self._close_page_impl, page_index)

    def close_page_by_id(self, page_id: int) -> bool:
        return self._call_in_worker(self._close_page_by_id_impl, page_id)

    def close_non_main_pages(self) -> int:
        return self._call_in_worker(self._close_non_main_pages_impl)

    def count_non_main_pages(self) -> int:
        return self._call_in_worker(self._count_non_main_pages_impl)

    def _close_page_impl(self, page_index: int) -> bool:
        self._ensure_ready_impl()
        pages = list(self.context.pages)
        if page_index < 0 or page_index >= len(pages):
            return False
        target = pages[page_index]
        try:
            if target == self.page:
                return False
            target.close()
            return True
        except Exception:
            return False

    def _close_page_by_id_impl(self, page_id: int) -> bool:
        self._ensure_ready_impl()
        for p in list(self.context.pages):
            if id(p) != page_id:
                continue
            if p == self.page:
                return False
            try:
                p.close()
                return True
            except Exception:
                return False
        return False

    def _close_non_main_pages_impl(self) -> int:
        self._ensure_ready_impl()
        closed = 0
        for p in list(self.context.pages):
            if p == self.page:
                continue
            try:
                p.close()
                closed += 1
            except Exception:
                continue
        return closed

    def _count_non_main_pages_impl(self) -> int:
        self._ensure_ready_impl()
        return sum(1 for p in list(self.context.pages) if p != self.page)

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
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def _pick_page(self, pages):
        for p in pages:
            if p.url and p.url != 'about:blank':
                return p
        return pages[0] if pages else None

    def _parse_cdp(self, cdp_url: str):
        parsed = urllib.parse.urlparse(cdp_url)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or 9222
        return host, port

    def _is_cdp_alive(self, host: str, port: int) -> bool:
        try:
            with urllib.request.urlopen(f'http://{host}:{port}/json/version', timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
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

    def _ensure_ready_impl(self):
        if not self.context or not self.page:
            raise RuntimeError('浏览器未连接，请先连接')
