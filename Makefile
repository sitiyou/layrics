.PHONY: all build dev install clean format lint check dist

all: dev

build:
	uv build

dev:
	uv pip install .

install:
	uv tool install .

clean:
	rm -rf build dist *.egg-info
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true

format:
	@echo "Formatting C++ with clang-format..."
	clang-format -i $$(find core -name '*.cpp' -o -name '*.hpp')
	@echo "Formatting Python with ruff..."
	ruff format layrics/

lint:
	ruff check layrics/
	clang-format --dry-run --Werror $$(find core -name '*.cpp' -o -name '*.hpp')

check: lint

dist:
	uv build --wheel
