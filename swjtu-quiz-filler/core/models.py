from dataclasses import dataclass, field
from typing import List


@dataclass
class QuizOption:
    text: str
    checked: bool
    global_idx: int  # label 在同类型 label 列表中的序号
    kind: str = 'radio'  # 'radio' | 'checkbox'


@dataclass
class QuizQuestion:
    number: int        # 1-based
    q_type: str        # 'single' | 'multi'
    options: List[QuizOption] = field(default_factory=list)


@dataclass
class AnswerItem:
    question_number: int
    answers: List[str]  # one item for single-choice, multiple for multi-choice


@dataclass
class FillResult:
    question_number: int
    q_type: str
    expected: List[str]
    clicked: List[str]
    not_found: List[str]

    @property
    def success(self) -> bool:
        return not self.not_found and len(self.clicked) == len(self.expected)
