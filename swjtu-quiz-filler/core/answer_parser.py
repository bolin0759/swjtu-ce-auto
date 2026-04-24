from typing import List

from .models import AnswerItem


def parse_answer_file(path: str) -> List[AnswerItem]:
    """
    每行对应一道题（第 N 行 = 第 N 题）。
    空行 = 填空/主观题，跳过不处理。
    含 ；分隔符 = 多选题，拆分为多个答案。
    """
    items = []
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for i, line in enumerate(lines, start=1):
        text = line.strip()
        if not text:
            continue  # 填空/主观题，跳过

        if '；' in text:
            answers = [a.strip() for a in text.split('；') if a.strip()]
        else:
            answers = [text]

        items.append(AnswerItem(question_number=i, answers=answers))

    return items
