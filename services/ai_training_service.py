import json

import httpx

from config import Settings
from schemas import TrainingAssistantTurn, TrainingSessionDraft
from services.ai_training_prompts import AI_TRAINING_RESPONSE_SCHEMA, build_training_system_prompt


class AITrainingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._training_material = settings.get_training_material()
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url,
            timeout=httpx.Timeout(120.0, connect=30.0),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
        )

    async def generate_turn(
        self,
        draft: TrainingSessionDraft,
        user_message: str,
        is_new_dialogue: bool,
    ) -> TrainingAssistantTurn:
        payload = {
            "model": self._settings.openai_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": build_training_system_prompt(
                        topic=self._settings.training_topic,
                        material=self._training_material,
                        total_questions=draft.total_questions,
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_prompt(
                        draft=draft,
                        user_message=user_message,
                        is_new_dialogue=is_new_dialogue,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": AI_TRAINING_RESPONSE_SCHEMA,
            },
        }

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return TrainingAssistantTurn.model_validate(json.loads(content))

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _build_prompt(
        draft: TrainingSessionDraft,
        user_message: str,
        is_new_dialogue: bool,
    ) -> str:
        questions_asked_str = "\n".join(f"- {q}" for q in draft.questions_asked) if draft.questions_asked else "Нет ещё"
        
        user_message_lower = user_message.strip().lower()
        is_command = user_message_lower in [
            "да", "готов", "конечно", "пошёл", "начинай", "давай", "поехали",
            "дальше", "следующий", "продолжить", "к тесту"
        ]
        
        needs_evaluation = (
            draft.phase == "testing" 
            and draft.current_question is not None 
            and draft.current_question.strip() != ""
            and not is_command
        )
        
        return (
            f"=== ТЕКУЩЕЕ СОСТОЯНИЕ ===\n"
            f"Фаза: {draft.phase}\n"
            f"Вопросов отвечено: {draft.questions_answered} из {draft.total_questions}\n"
            f"Правильных: {draft.correct_answers}\n"
            f"Текущий вопрос: \"{draft.current_question or 'НЕТ'}\"\n\n"
            f"Вопросы которые уже задавались:\n{questions_asked_str}\n\n"
            f"Сообщение пользователя: \"{user_message}\"\n\n"
            f"Это команда (не ответ): {str(is_command).lower()}\n"
            f"Нужно оценить как ответ: {str(needs_evaluation).lower()}\n\n"
            "=== ТВОЕ ЗАДАНИЕ ===\n\n"
            "ЕСЛИ phase = 'testing' и current_question = 'НЕТ' (новый тест):\n"
            "- reply: 'Начинаем тест'\n"
            "- phase: 'testing'\n"
            "- latest_answer_evaluated: false\n"
            "- answer_is_correct: null\n"
            "- answer_feedback: null\n"
            "- next_question: ЗАДАЙ ПЕРВЫЙ ВОПРОС из материала!\n"
            "- final_summary: null\n\n"
            "ЕСЛИ needs_evaluation = true (пользователь ответил на вопрос):\n"
            "- reply: 'Правильно' или 'Неправильно'\n"
            "- phase: 'testing'\n"
            "- latest_answer_evaluated: true\n"
            "- answer_is_correct: true/false\n"
            "- answer_feedback: краткий правильный ответ если ошибся\n"
            "- next_question: СЛЕДУЮЩИЙ ВОПРОС (не повторяй!)\n"
            "- final_summary: null\n\n"
            "ЕСЛИ questions_answered >= total_questions:\n"
            "- phase: 'completed'\n"
            "- final_summary: итог теста\n"
            "- next_question: null"
        )
