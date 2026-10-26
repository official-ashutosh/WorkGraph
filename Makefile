.PHONY: setup test eval demo clean

setup:
	python -m pip install -r requirements.txt
	python -m playwright install chromium
	python data/generate_invoices.py
	python apps/ledgerone/database.py

test:
	python -m pytest tests/ -v

eval:
	python evals/runner.py

demo:
	python run_demo.py

clean:
	python -c "import os; [os.remove(f) for f in ['data/workgraph.db', 'data/memory.db', 'apps/ledgerone/ledgerone.db'] if os.path.exists(f)]"
