FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
	RECORD_REPLAY_MODE=replay \
	OPENBLAS_NUM_THREADS=1 \
	WORKGRAPH_HOST=0.0.0.0 \
	LEDGERONE_HOST=0.0.0.0 \
	PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
	WORKGRAPH_EVENT_DB=/var/lib/workgraph/workgraph.db \
	WORKGRAPH_MEMORY_DB=/var/lib/workgraph/memory.db \
	LEDGERONE_DB_PATH=/var/lib/workgraph/ledgerone.db \
	WORKGRAPH_REPORTS_DIR=/var/lib/workgraph/reports

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

RUN useradd --system --create-home --uid 10001 workgraph \
	&& mkdir -p /var/lib/workgraph /ms-playwright \
	&& chown -R workgraph:workgraph /var/lib/workgraph /ms-playwright

COPY --chown=workgraph:workgraph . .
USER workgraph

RUN python data/generate_invoices.py \
	&& python apps/ledgerone/database.py

EXPOSE 8080 8000

CMD ["python", "run_demo.py"]
