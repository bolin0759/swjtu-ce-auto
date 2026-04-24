from dataclasses import dataclass
from typing import Optional


@dataclass
class CourseItem:
    name: str
    learned: bool
    item_type: str  # doc | video
    row_index: int


@dataclass
class RunConfig:
    status_filter: str = 'unlearned'  # all | unlearned | learned
    type_filter: str = 'doc'  # all | doc | video
    open_interval_ms: int = 1200
    auto_close: bool = True
    close_interval_ms: int = 1500
    item_timeout_ms: int = 8000


@dataclass
class OpenResult:
    success: bool
    reason: str = ''
    opened_page_index: Optional[int] = None
