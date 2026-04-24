import threading
from typing import Callable, List

from .models import AnswerItem, FillResult, QuizQuestion


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
        questions: List[QuizQuestion],
        answer_items: List[AnswerItem],
        on_progress: Callable[[int, int, str], None],
        on_finished: Callable[[List[FillResult]], None],
    ) -> None:
        if self.is_running():
            self.logger.warn('任务已在运行中')
            return

        self._stop_event.clear()
        self._pause_event.clear()

        def _run():
            results = []
            try:
                results = self.browser.click_answers_sync(
                    questions, answer_items, on_progress,
                    self._stop_event, self._pause_event,
                )
            except Exception as e:
                self.logger.error(f'任务异常: {e}')
            finally:
                on_finished(results)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

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
        self.logger.info('正在停止...')
