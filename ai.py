import logging
from openai import AsyncOpenAI

import settings


chatgpt = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    max_retries=5,
)

async def generate_text(history):
    try:
        stream = await chatgpt.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=history,
            max_tokens=4096,
            temperature=1,
            stream=True,
        )
        return stream
    except Exception as e:
        logging.error(e)