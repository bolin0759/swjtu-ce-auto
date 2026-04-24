import threading
import time
from typing import Callable, List

from .models import CourseItem, RunConfig


class TaskRunner:
    def __init__(self, logger, browser_controller):
        self.logger = logger
        self.browser = browser_controller
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        items: List[CourseItem],
        config: RunConfig,
        on_progress: Callable[[int, int, str], None],
        on_finished: Callable[[], None],
    ) -> None:
        if self.is_running():
            self.logger.warn('任务已在运行中')
            return

        self._stop_event.clear()
        self._pause_event.clear()

        def _run():
            try:
                self._run_sync(items, config, on_progress)
            except Exception as e:
                self.logger.error(f'任务异常: {e}')
            finally:
                on_finished()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _run_sync(self, items, config, on_progress):
        total = len(items)
        done = 0
        self.logger.info(f'任务开始，总计 {total} 项')

        for item in items:
            if self._stop_event.is_set():
                self.logger.warn('收到停止指令，任务终止')
                break

            while self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(0.2)

            if self._stop_event.is_set():
                break

            on_progress(done, total, item.name)
            result = self.browser.open_item_by_real_click(item, config.item_timeout_ms)
            if result.success:
                self.logger.info(f'打开成功: {item.name}')
                if config.auto_close and result.opened_page_id is not None:
                    time.sleep(max(0.1, config.close_interval_ms / 1000))
                    closed = self._close_with_retry(result.opened_page_id)
                    if closed:
                        self.logger.info(f'已自动关闭标签页: {item.name}')
                    else:
                        self.logger.warn(f'自动关闭失败，尝试兜底清理: {item.name}')
                        fallback_closed = self.browser.close_non_main_pages()
                        if fallback_closed > 0:
                            self.logger.info(f'兜底清理完成，关闭 {fallback_closed} 个标签页')
                        else:
                            self.logger.warn(f'兜底清理未关闭任何标签页: {item.name}')
                if config.auto_close:
                    self._guard_excess_tabs(config.max_non_main_tabs)
            else:
                self.logger.warn(f'打开失败: {item.name} | {result.reason}')

            done += 1
            on_progress(done, total, item.name)
            time.sleep(max(0.1, config.open_interval_ms / 1000))

        if config.auto_close:
            tail_closed = self.browser.close_non_main_pages()
            if tail_closed > 0:
                self.logger.info(f'任务结束前清理标签页: {tail_closed} 个')

        on_progress(done, total, '完成')
        self.logger.info('任务结束')

    def _close_with_retry(self, page_id: int) -> bool:
        for attempt in range(3):
            if self.browser.close_page_by_id(page_id):
                return True
            time.sleep(0.2 * (attempt + 1))
        return False

    def _guard_excess_tabs(self, max_non_main_tabs: int):
        non_main_count = self.browser.count_non_main_pages()
        if non_main_count <= max(0, max_non_main_tabs):
            return
        self.logger.warn(f'检测到非主标签页过多: {non_main_count}，执行强制清理')
        closed = self.browser.close_non_main_pages()
        if closed > 0:
            self.logger.info(f'强制清理完成，关闭 {closed} 个标签页')

    def pause(self):
        if not self.is_running():
            return
        self._pause_event.set()
        self.logger.info('任务已暂停')

    def resume(self):
        if not self.is_running():
            return
        self._pause_event.clear()
        self.logger.info('任务已继续')

    def stop(self):
        if not self.is_running():
            return
        self._stop_event.set()
        self._pause_event.clear()
        self.logger.info('正在停止任务...')
