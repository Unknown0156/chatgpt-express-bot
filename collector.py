from enum import Enum, auto

from pybotx import Bot, IncomingMessage, IncomingMessageHandlerFunc, HandlerCollector, StatusRecipient
from pybotx_fsm import FSMCollector

import settings
from ai import generate_text
import ui

#выполнение команд во всех состояниях
async def commands_middleware(
    message: IncomingMessage, bot: Bot, call_next: IncomingMessageHandlerFunc
) -> None:
    if message.body == "/help":
        await help_handler(message, bot)
    elif message.body == "/start":
        await start_handler(message, bot)
    elif message.body == "/end":
        await end_handler(message, bot)
    else:
        await call_next(message, bot)

#энумерация для fsm
class AIStates(Enum):
    WAITING_USER_START = auto()
    WAITING_USER_PROMPT = auto()
    WAITING_AI_RESPONSE = auto()
    WAITING_AI_PRINT = auto()

collector = HandlerCollector()
fsm = FSMCollector(AIStates)

#стандартный обработчик сообщений
@collector.default_message_handler
async def default_handler(message: IncomingMessage, bot: Bot,) -> None:
    #установка состояния ожидания старта
    await message.state.fsm.change_state(
        AIStates.WAITING_USER_START,
    )
    #отправка стандартного ответа
    await bot.answer_message(
        body=f"Привет, {message.sender.username}! Этот бот предоставит доступ к ChatGPT.\nВАЖНО! Не передавай боту логины, пароли и другие персональные данные!",
        bubbles=ui.start,
        silent_response=True,
    )

#обработчик помощи
@collector.command("/help", description="Доступные команды")
async def help_handler(message: IncomingMessage, bot: Bot) -> None:
    #получение списка команд
    status_recipient = StatusRecipient.from_incoming_message(message)
    status = await bot.get_status(status_recipient)
    command_map = dict(sorted(status.items()))
    answer_body = "\n".join(
        f"`{command}` -- {description}" for command, description in command_map.items()
    )
    #проверка состояния
    if (await message.state.fsm.get_state() in {AIStates.WAITING_USER_START, AIStates.WAITING_AI_RESPONSE}):
        silent_response = True
    else:
        silent_response = False
    #отправка ответа
    await bot.answer_message(answer_body, silent_response=silent_response)

#обработчик начала работы
@collector.command("/start", description="Начать чат с ИИ")
async def start_handler(message: IncomingMessage, bot: Bot) -> None:
    #установка состояния ожидания промпта
    await message.state.fsm.change_state(
        AIStates.WAITING_USER_PROMPT,
        history=[],
    )
    #отправка ответа
    await bot.answer_message("Отправь сообщение, чтобы начать переписку", bubbles=ui.end, silent_response=False)

#обработчик завершения диалога
@collector.command("/end", description="Закончить диалог")
async def end_handler(message: IncomingMessage, bot: Bot, body: str = "") -> None:
    #сброс состояния
    await message.state.fsm.drop_state()
    #установка состояния ожидания старта
    await message.state.fsm.change_state(
        AIStates.WAITING_USER_START,
    )
    #отправка ответа
    body += "История диалога очищена. Можно начать сначала."
    await bot.answer_message(body=body, bubbles=ui.start, silent_response=True)

#обработчик старта
@fsm.on(AIStates.WAITING_USER_START, middlewares=[commands_middleware])
async def waiting_start_handler(message: IncomingMessage, bot: Bot) -> None:
    pass

#обработчик запроса chatgpt
@fsm.on(AIStates.WAITING_USER_PROMPT, middlewares=[commands_middleware])
async def waiting_prompt_handler(message: IncomingMessage, bot: Bot) -> None:
    #получение контекста
    history = message.state.fsm_storage.history
    if len(history) > settings.max_context_size:
        await end_handler(message, bot, "Превышен максимальный размер контекста. ")
        return
    #установка состояния ожидания ответа chatgpt
    await message.state.fsm.change_state(
        AIStates.WAITING_AI_RESPONSE,
        history=history
    )
    #ответ
    body = "..."
    dummy_id = await bot.answer_message(body=body, silent_response=True, keyboard=ui.stop)
    #сохранение вопроса в контекст
    history.append({"role": "user", "content": message.body})
    #генерации chatgpt
    stream = await generate_text(history)
    #проверка на изменение состояния
    if (await message.state.fsm.get_state() == AIStates.WAITING_AI_RESPONSE):
        await message.state.fsm.change_state(
            AIStates.WAITING_AI_PRINT,
            history=history,
        )
    else:
        return
    #стриминг ответа
    async for part in stream:
        #получение части ответа
        if (body == "..."):
            body = part.choices[0].delta.content or ""
        else:
            body += part.choices[0].delta.content or ""
        #проверка на изменение состояния
        if (await message.state.fsm.get_state() == AIStates.WAITING_AI_PRINT):
            #редактирование сообщения
            await bot.edit_message(bot_id=message.bot.id, sync_id=dummy_id, body=body)
        else:
            break
    #генерация завершена
    await bot.delete_message(bot_id=message.bot.id, sync_id=dummy_id)
    await bot.answer_message(body=body, silent_response=False, bubbles=ui.end)
    #сохранение ответа в контекст
    history.append({"role": "assistant", "content": body})
    #остановка симуляции использования клавиатуры ботом
    await bot.stop_typing(
        bot_id=message.bot.id,
        chat_id=message.chat.id,
    )
    #установка состояния ожидания промпта
    await message.state.fsm.change_state(
        AIStates.WAITING_USER_PROMPT,
        history=history
    )    

#обработчик ожидания ответа chatgpt
@fsm.on(AIStates.WAITING_AI_RESPONSE, middlewares=[commands_middleware])
async def waiting_response_handler(message: IncomingMessage, bot: Bot) -> None:
    #получение контекста
    history = message.state.fsm_storage.history
    #остановка генерации
    if message.body == "/_stop":
        await message.state.fsm.change_state(
            AIStates.WAITING_USER_PROMPT,
            history=history,
        )
        await bot.delete_message(bot_id=message.bot.id, sync_id=message.source_sync_id)
        await bot.answer_message(body="[прерван]", silent_response=False, bubbles=ui.end)

@fsm.on(AIStates.WAITING_AI_PRINT, middlewares=[commands_middleware])
async def waiting_print_handler(message: IncomingMessage, bot: Bot) -> None:
    #симуляция использования клавиатуры ботом
    await bot.start_typing(
        bot_id=message.bot.id,
        chat_id=message.chat.id,
    )
    #получение контекста
    history = message.state.fsm_storage.history
    #остановка генерации
    if message.body == "/_stop":
        await message.state.fsm.change_state(
            AIStates.WAITING_USER_PROMPT,
            history=history,
        )