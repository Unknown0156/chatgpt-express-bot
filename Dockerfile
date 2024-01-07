FROM python:3.10-alpine as api

WORKDIR /chatgpt_express
COPY . .
RUN pip install -r requirements.txt --no-cache-dir

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1