AI_TRAINING_RESPONSE_SCHEMA = {
    "name": "training_turn",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "phase": {"type": "string", "enum": ["learning", "testing", "completed"]},
            "latest_answer_evaluated": {"type": "boolean"},
            "answer_is_correct": {"type": ["boolean", "null"]},
            "answer_feedback": {"type": ["string", "null"]},
            "next_question": {"type": ["string", "null"]},
            "final_summary": {"type": ["string", "null"]},
        },
        "required": [
            "reply",
            "phase",
            "latest_answer_evaluated",
            "answer_is_correct",
            "answer_feedback",
            "next_question",
            "final_summary",
        ],
        "additionalProperties": False,
    },
}


def build_training_system_prompt(topic: str, material: str, total_questions: int) -> str:
    return f"""
Ты — AI-наставник. Проводишь тестирование по теме: {topic}

Материал: {material}

ПРАВИЛА:
1. Если phase = "learning" — объясняй материал кратко
2. Если phase = "testing" — ЗАДАВАЙ ВОПРОСЫ из материала
3. Если phase = "completed" — дай итог

ВАЖНО ДЛЯ testing:
- Каждый раз когда пользователь отвечает — оценивай ответ
- latest_answer_evaluated = true когда оценил ответ
- answer_feedback = "Правильно!" или "Неправильно. Правильный ответ: ..."
- next_question = СЛЕДУЮЩИЙ ВОПРОС (ОБЯЗАТЕЛЬНО заполняй, если тест не завершён!)
- reply = коротко "Правильно" или "Неправильно"
- Не повторяй вопросы

Всего вопросов: {total_questions}
""".strip()
