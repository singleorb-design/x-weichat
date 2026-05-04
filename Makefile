SHELL := /bin/bash
.DEFAULT_GOAL := help

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
RENDERER_DIR := $(ROOT_DIR)/packages/renderer
WEB_DIR := $(ROOT_DIR)/apps/web
ENV_FILE ?= .env

-include $(ENV_FILE)
export

.PHONY: help setup install-playwright check-api backend frontend start dev test build

help:
	@printf "x-to-wechat-agent Make targets:\n"
	@printf "  make setup               安装 Python/Node 依赖并构建 renderer\n"
	@printf "  make install-playwright  安装 Chromium\n"
	@printf "  make check-api           用 $(ENV_FILE) 中的 API Key 测试模型网关连通性\n"
	@printf "  make backend             启动 FastAPI 后端 (127.0.0.1:8000)\n"
	@printf "  make frontend            启动 Vite 前端 (127.0.0.1:5173)\n"
	@printf "  make start               一键同时启动后端和前端\n"
	@printf "  make dev                 一键同时启动后端和前端\n"
	@printf "  make test                运行仓库测试\n"
	@printf "  make build               构建 renderer 和 web\n"

setup:
	uv sync --extra dev
	npm --prefix "$(RENDERER_DIR)" install
	npm --prefix "$(RENDERER_DIR)" run build
	npm --prefix "$(WEB_DIR)" install

install-playwright:
	PYTHONPATH="$(ROOT_DIR)" uv run --directory "$(ROOT_DIR)" playwright install chromium

check-api:
	PYTHONPATH="$(ROOT_DIR)" uv run --directory "$(ROOT_DIR)" python -c "from agent.config import Settings; from agent.models.gateway import ModelGateway; settings = Settings(); api_key = settings.api_key.strip(); env_file = '$(ENV_FILE)'; assert api_key, f'X2W_API_KEY is empty; please configure it in {env_file}'; gateway = ModelGateway(api_key=api_key, base_url=settings.api_base); gateway._client.models.list(); print('API connection OK:', settings.provider, settings.api_base)"

backend:
	PYTHONPATH="$(ROOT_DIR)" uv run --directory "$(ROOT_DIR)" --python 3.11 uvicorn agent.api.main:app --app-dir "$(ROOT_DIR)" --reload --host 127.0.0.1 --port 8000

frontend:
	npm --prefix "$(WEB_DIR)" run dev

start:
	@$(MAKE) dev

dev:
	@set -euo pipefail; \
	BACKEND_PID=""; \
	cleanup() { \
	  if [ -n "$$BACKEND_PID" ] && kill -0 "$$BACKEND_PID" 2>/dev/null; then \
	    kill "$$BACKEND_PID"; \
	  fi; \
	}; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) backend & \
	BACKEND_PID=$$!; \
	sleep 3; \
	$(MAKE) frontend

test:
	PYTHONPATH="$(ROOT_DIR)" uv run --directory "$(ROOT_DIR)" --python 3.11 --extra dev pytest -v "$(ROOT_DIR)/tests"
	npm --prefix "$(RENDERER_DIR)" test
	npm --prefix "$(RENDERER_DIR)" run build
	npm --prefix "$(WEB_DIR)" test
	npm --prefix "$(WEB_DIR)" run build

build:
	npm --prefix "$(RENDERER_DIR)" run build
	npm --prefix "$(WEB_DIR)" run build
