import asyncio
from typing import List, Optional

from playwright.async_api import async_playwright

from .models import CourseItem, OpenResult, RunConfig


class BrowserController:
    def __init__(self, logger):
        self.logger = logger
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def connect(self, cdp_url: str) -> bool:
        await self._ensure_stopped()
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url)
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

    def connect_sync(self, cdp_url: str) -> bool:
        return asyncio.run(self.connect(cdp_url))

    async def get_current_course_items(self, config: RunConfig) -> List[CourseItem]:
        self._ensure_ready()
        rows = await self.page.evaluate(
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

    def get_current_course_items_sync(self, config: RunConfig) -> List[CourseItem]:
        return asyncio.run(self.get_current_course_items(config))

    async def open_item_by_real_click(self, item: CourseItem, timeout_ms: int) -> OpenResult:
        self._ensure_ready()

        pages_before = list(self.context.pages)
        before_ids = {id(p) for p in pages_before}

        try:
            await self.page.evaluate(
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
                    return OpenResult(success=True, opened_page_index=idx)
            await asyncio.sleep(step / 1000)
            waited += step

        return OpenResult(success=True, reason='未检测到新标签页，视为已点击')

    async def close_page(self, page_index: int) -> bool:
        self._ensure_ready()
        pages = list(self.context.pages)
        if page_index < 0 or page_index >= len(pages):
            return False
        target = pages[page_index]
        try:
            if target == self.page:
                return False
            await target.close()
            return True
        except Exception:
            return False

    async def _ensure_stopped(self):
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
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

    def _ensure_ready(self):
        if not self.context or not self.page:
            raise RuntimeError('浏览器未连接，请先连接')
