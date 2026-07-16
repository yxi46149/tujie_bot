FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system bot && adduser --system --ingroup bot bot

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=bot:bot app ./app
COPY --chown=bot:bot scripts ./scripts
RUN mkdir -p /app/data && chown -R bot:bot /app/data

USER bot

CMD ["python", "-m", "app.main"]
