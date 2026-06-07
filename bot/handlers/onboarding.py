import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.keyboards import cancel_keyboard, remove_keyboard
from config import Settings
from database import TrainingResultRepository
from schemas import TrainingSessionDraft
from services import AITrainingService, TrainingService

logger = logging.getLogger(__name__)
router = Router()


class TrainingStates(StatesGroup):
    active = State()
    waiting_for_readiness = State()


@router.message(Command("start"))
async def handle_start(message: Message, state: FSMContext, settings: Settings, training_service: TrainingService) -> None:
    await state.clear()
    await state.set_state(TrainingStates.active)
    await state.update_data(
        draft=training_service.start_session(settings.quiz_question_count).model_dump(),
        result_id=None,
        name_collected=False,
        waiting_for_readiness=False,
    )
    await message.answer(
        "Здравствуйте! Я проведу тестирование по теме: «" + settings.training_topic + "».\n\n"
        "Напишите имя сотрудника, которого нужно обучить.",
        reply_markup=cancel_keyboard(),
    )


@router.message(Command("cancel"))
async def handle_cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Сейчас нет активной сессии обучения.", reply_markup=remove_keyboard())
        return

    await state.clear()
    await message.answer(
        "Сессия обучения отменена. Чтобы начать заново, отправьте /start.",
        reply_markup=remove_keyboard(),
    )


@router.message(TrainingStates.active, F.text)
async def process_ai_training(
    message: Message,
    state: FSMContext,
    settings: Settings,
    training_service: TrainingService,
    ai_training_service: AITrainingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    state_data = await state.get_data()
    draft = TrainingSessionDraft.model_validate(state_data.get("draft", {}))
    name_collected = bool(state_data.get("name_collected"))
    waiting_for_readiness = bool(state_data.get("waiting_for_readiness", False))
    user_text = message.text or ""

    try:
        # Если ждём подтверждения готовности — проверяем ответ
        if waiting_for_readiness:
            user_lower = user_text.strip().lower()
            if user_lower in ["да", "готов", "конечно", "пошёл", "начинай", "давай", "поехали"]:
                # Переходим к тесту
                await state.update_data(waiting_for_readiness=False)
                updated_draft = TrainingSessionDraft.model_validate(state_data.get("draft", {}))
                updated_draft.phase = "testing"
                
                ai_turn = await ai_training_service.generate_turn(
                    draft=updated_draft,
                    user_message="Пользователь готов к тесту. Задай первый вопрос.",
                    is_new_dialogue=True,
                )
                updated_draft = training_service.apply_ai_turn(updated_draft, ai_turn)
                await state.update_data(draft=updated_draft.model_dump())
                
                # Показываем первый вопрос
                if ai_turn.next_question:
                    await message.answer(ai_turn.next_question, reply_markup=cancel_keyboard())
                else:
                    await message.answer(ai_turn.reply, reply_markup=cancel_keyboard())
                return
            else:
                await message.answer("Чтобы начать тест, напишите «да» или «готов».", reply_markup=cancel_keyboard())
                return

        if not name_collected:
            updated_draft = training_service.register_employee_name(draft=draft, employee_name=user_text)
            await state.update_data(draft=updated_draft.model_dump(), name_collected=True)
            
            # Показываем материал и спрашиваем о готовности
            await state.update_data(waiting_for_readiness=True)
            
            response_parts = [
                f"✅ Готово, {updated_draft.employee_name}, начинаем тест.",
                f"📚 Материал для тестирования:\n{settings.get_training_material()}",
                f"Всего вопросов: {updated_draft.total_questions}.",
                "\n👉 Готовы начать тестирование? Напишите «да» или «готов».",
            ]
            
            await message.answer("\n\n".join(response_parts), reply_markup=cancel_keyboard())
            return
        else:
            ai_turn = await ai_training_service.generate_turn(
                draft=draft,
                user_message=user_text,
                is_new_dialogue=False,
            )
            updated_draft = training_service.apply_ai_turn(draft, ai_turn)
            await state.update_data(draft=updated_draft.model_dump())

        if ai_turn.phase == "completed":
            async with session_factory() as session:
                repository = TrainingResultRepository(session)
                await training_service.create_result(
                    repository=repository,
                    draft=updated_draft,
                    topic=settings.training_topic,
                    telegram_user_id=message.from_user.id if message.from_user else 0,
                    telegram_chat_id=message.chat.id,
                )

            await state.clear()
            await message.answer(
                f"{ai_turn.reply}\n\n"
                f"Результат сохранен в Postgres.\n"
                f"Итог: {updated_draft.correct_answers}/{updated_draft.total_questions} "
                f"({updated_draft.score_percent()}%).",
                reply_markup=remove_keyboard(),
            )
            return

        # Показываем обратную связь и следующий вопрос
        if ai_turn.answer_feedback and ai_turn.next_question:
            response_text = f"{ai_turn.answer_feedback}\n\n{ai_turn.next_question}"
        elif ai_turn.answer_feedback:
            response_text = ai_turn.answer_feedback
        elif ai_turn.next_question:
            response_text = ai_turn.next_question
        else:
            response_text = ai_turn.reply

        await message.answer(response_text, reply_markup=cancel_keyboard())
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=cancel_keyboard())
    except Exception:
        logger.exception("Failed to process AI training")
        await message.answer(
            "Не удалось обработать сообщение. Попробуйте еще раз или отправьте /cancel.",
            reply_markup=cancel_keyboard(),
        )


@router.message(TrainingStates.active)
async def handle_invalid_collecting_input(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте ответ текстом.", reply_markup=cancel_keyboard())


@router.message(F.text)
async def handle_text_without_flow(message: Message) -> None:
    await message.answer("Чтобы начать тестирование, отправьте /start.")


@router.message()
async def handle_unsupported_input(message: Message) -> None:
    await message.answer("Пожалуйста, используйте текстовые сообщения или команду /start.")
