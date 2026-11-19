PY := .venv/bin/python
KEY_FILE := $(HOME)/.multiverse_demo_key
DESKTOP_KEY := $(HOME)/Desktop/key.txt
COMPANY ?=
DOMAIN ?=
INDUSTRY ?=
EMPLOYEES ?=
COUNTRY ?=
TARGET = --company "$(COMPANY)" --domain "$(DOMAIN)" --industry "$(INDUSTRY)" --employees "$(EMPLOYEES)" --country "$(COUNTRY)"
RUN = @PYTHONDONTWRITEBYTECODE=1 ANTHROPIC_API_KEY="$${ANTHROPIC_API_KEY:-$$(cat "$(KEY_FILE)" 2>/dev/null)}" $(PY) demo.py

.DEFAULT_GOAL := help
.PHONY: help key tests all inbound outbound safety real search brief research forget-key

help:
	@cat demo-commands.txt

key:
	@umask 077; tmp="$(KEY_FILE).tmp"; \
	if tr -d '[:space:]' < "$(DESKTOP_KEY)" > "$$tmp" 2>/dev/null && [ -s "$$tmp" ]; then mv "$$tmp" "$(KEY_FILE)"; else rm -f "$$tmp"; fi; \
	if [ -s "$(KEY_FILE)" ]; then echo "Key loaded"; else echo "Key not found. Paste it into Desktop/key.txt, save, and run make key again."; exit 1; fi

tests:
	@PYTHONDONTWRITEBYTECODE=1 $(PY) -m pytest -q -p no:cacheprovider tests

all:
	$(RUN) all

inbound:
	$(RUN) inbound

outbound:
	$(RUN) outbound

safety:
	$(RUN) safety

real:
	$(RUN) real

search:
	$(RUN) search $(TARGET)

brief:
	$(RUN) brief

research:
	$(RUN) research $(TARGET)

forget-key:
	@rm -f "$(KEY_FILE)"; echo "Saved demo key removed"
