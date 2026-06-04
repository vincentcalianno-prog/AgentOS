PYTHON := python3.12
VENV   := .venv
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

.PHONY: setup test discipline check clean

## setup: create .venv (if absent) and install all dependencies
setup:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment with $(PYTHON)..."; \
		$(PYTHON) -m venv $(VENV); \
	fi
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -r requirements-dev.txt
	$(PIP) install -e . --quiet
	@echo "Setup complete. Activate with: source $(VENV)/bin/activate"

## test: run the full Layer B test suite
test:
	$(PYTEST) acp/layer_b/tests/ -v

## discipline: run the Layer A/B/C discipline check
discipline:
	$(VENV)/bin/python3 acp/discipline_check.py

## check: run test + discipline (the "everything green" gate)
check: test discipline

## clean: remove .venv and all __pycache__ trees
clean:
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
