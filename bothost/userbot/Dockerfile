FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pre-install the most common Telegram bot libraries so user containers
# don't need writable filesystem access for `pip install`.
RUN pip install \
    "aiogram==3.13.1" \
    "pyTelegramBotAPI==4.22.0" \
    "python-telegram-bot==21.6" \
    "requests==2.32.3" \
    "aiohttp==3.10.10" \
    "httpx==0.27.2" \
    "python-dotenv==1.0.1" \
    "pydantic==2.9.2" \
    "loguru==0.7.2" \
    "orjson==3.10.7" \
    "pyyaml==6.0.2" \
    "beautifulsoup4==4.12.3" \
    "lxml==5.3.0" \
    "Pillow==10.4.0"

WORKDIR /app

# The user's `bot.py` is mounted at /app/bot.py at runtime.
CMD ["python", "-u", "/app/bot.py"]
