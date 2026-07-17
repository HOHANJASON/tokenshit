.PHONY: install seed demo eval test serve mcp

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

seed:
	.venv/bin/python -m nextoken_copilot.seed

demo:
	.venv/bin/python -m scripts.ask --role admin "what is our revenue and gross margin and how healthy are the providers"

eval:
	.venv/bin/python -m eval.run_eval

N ?= 5
reliability:
	.venv/bin/python -m eval.reliability -n $(N)

test:
	.venv/bin/python -m pytest -q

serve:
	.venv/bin/uvicorn nextoken_copilot.api:app --port 8088 --reload
