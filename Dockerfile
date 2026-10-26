FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV RECORD_REPLAY_MODE=replay
ENV OPENBLAS_NUM_THREADS=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

COPY . .

RUN python data/generate_invoices.py
RUN python apps/ledgerone/database.py

EXPOSE 8080 8000

CMD ["python", "run_demo.py"]
