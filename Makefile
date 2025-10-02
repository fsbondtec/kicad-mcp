.PHONY: help install test lint format clean build run

help:
	@echo "Available commands:"
	@echo " 	install       		Install dependencies"
	@echo " 	test          		Run tests"
	@echo " 	test <file>   		Run specific test file"
	@echo " 	lint          		Run linting"
	@echo " 	format        		Format code"
	@echo " 	clean         		Clean build artifacts"
	@echo " 	build         		Build package"
	@echo " 	run           		Start the KiCad MCP server"

install:
	uv sync --group dev

test:
	# Collect extra args; if none, use tests/
	@files="$(filter-out $@,$(MAKECMDGOALS))"; \
	if [ -z "$$files" ]; then files="tests/"; fi; \
	uv run pytest $$files -v

# Prevent “No rule to make target …” errors for the extra args
%::
	@:

lint:
	uv run ruff check kicad_mcp/ tests/
	uv run mypy kicad_mcp/

format:
	uv run ruff format kicad_mcp/ tests/

clean:
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -f coverage.xml
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

build:
	uv build

run:
	uv run python main.py
