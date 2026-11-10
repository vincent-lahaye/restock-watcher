# restock-watcher — image légère (pas de navigateur : curl_cffi suffit à passer les
# WAF courants avec un proxy résidentiel).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# selectolax / curl_cffi ont des wheels manylinux -> pas de toolchain à installer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY restock_watcher ./restock_watcher

# state.json vit sur un volume monté (/data).
VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "restock_watcher"]
