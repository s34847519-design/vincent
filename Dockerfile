FROM python:3.12-slim

WORKDIR /app

COPY discord-bot/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# CLAUDE.md 要一起帶進去——人格設定就是從它讀的
COPY CLAUDE.md /CLAUDE.md
COPY discord-bot/ ./

ENV VINCENT_PERSONA_FILES=/CLAUDE.md \
    VINCENT_DB=/data/vincent.db \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]

CMD ["python", "run.py"]
