# x-to-wechat-agent

## 1. Project Overview

- This repository builds a local-first `X URL -> 中文翻译 -> 审校 -> 公众号改写 -> 微信 HTML` pipeline with a Web UI for status tracking and artifact preview. The intended v1 scope is intentionally narrow: one tweet URL or one X Article URL, one local user, one serial pipeline, and no thread aggregation, batch processing, approval workflow, or direct publishing. See `docs/superpowers/specs/2026-05-03-x-to-wechat-agent-design.md`.
- The top-level architecture is `Web UI` + `Python Agent Core` + `Node Renderer`. Python owns job orchestration, state, prompts, model calls, logs, and artifact storage; Node is an internal renderer invoked by Python rather than a standalone service. See `docs/superpowers/specs/2026-05-03-x-to-wechat-agent-design.md:42`, `docs/superpowers/specs/2026-05-03-x-to-wechat-agent-design.md:83`, `docs/superpowers/specs/2026-05-03-x-to-wechat-agent-design.md:91`.
- The graph report identifies the main architectural hubs as `JobStore`, `Settings`, `ModelGateway`, `PipelineRunner`, and `StageContext`. Read these first when changing core behavior. See `graphify-out/GRAPH_REPORT.md:50`.
- Backend composition root: `agent/api/main.py:13` wires `Settings`, `JobStore`, `ModelGateway`, and `PipelineRunner` into the FastAPI app and mounts the API under `/api`.
- Frontend composition root: `apps/web/src/App.tsx:69` is the main stateful container; it creates jobs, starts runs, polls job status, loads prompts, and fetches artifacts. API access is centralized in `apps/web/src/api.ts:22`.

### Main Runtime Flow

1. `POST /api/jobs` validates an X URL and creates a pending job. See `agent/api/routes_jobs.py:21` and `agent/api/routes_jobs.py:43`.
2. `POST /api/jobs/{job_id}/run` claims the job and starts background execution. See `agent/api/routes_jobs.py:72`.
3. `PipelineRunner.run()` executes the fixed stage chain `x-fetch -> translate -> review -> wechat-rewrite -> render-html`. See `agent/core/pipeline.py:17`, `agent/core/pipeline.py:43`.
4. Each stage reads the previous artifact and writes the next one into the job workspace under `artifacts/<job_id>/`. Allowed artifact names are fixed in `agent/jobs/store.py:16`.
5. The UI polls `GET /api/jobs/{job_id}` and reads artifacts from `/api/jobs/{job_id}/artifacts/...`; HTML is returned as `text/html` for iframe preview and Markdown as plain text. See `agent/api/routes_preview.py:12`.

### Backend Structure

- `agent/config.py`: Pydantic settings loaded from `.env` and `X2W_*` variables.
- `agent/api/`: FastAPI app factory and routes.
- `agent/core/pipeline.py`: serial stage orchestration, status transitions, per-stage metadata, and error normalization.
- `agent/jobs/store.py`: job workspace management, `job.json`, logs, SQLite index, artifact IO, and run-claim concurrency control.
- `agent/models/gateway.py`: OpenAI-compatible model wrapper with long timeout and retry logic.
- `agent/models/schemas.py`: shared job/status/error/model schemas and stage constraints.
- `agent/stages/`: stage implementations. `x-fetch` is local fetch/parse with article fallback; `translate`, `review`, and `wechat-rewrite` are Markdown LLM stages; `render-html` shells out to the Node renderer.
- `agent/prompts/`: stage prompts. Prompt filenames are versioned assets referenced from `PipelineRunner.STAGE_PROMPT_VERSIONS` in `agent/core/pipeline.py:23`.

### Frontend Structure

- `apps/web/src/App.tsx`: single-page container for job list, polling, progress, artifact tabs, prompt display, and preview.
- `apps/web/src/api.ts`: canonical API routes and fixed artifact URL mapping.
- `apps/web/src/components/`: view components only; orchestration remains in `App.tsx`.
- `apps/web/src/types.ts`: mirrors the backend job contract; avoid schema drift without updating both sides.

### Invariants Worth Preserving

- Only tweet URLs and X Article URLs are accepted. URL validation lives in `agent/api/routes_jobs.py:10`.
- Stage order is a contract, not a UI detail. It is defined in `agent/models/schemas.py:60` and consumed by the pipeline and frontend.
- Artifact filenames are a contract, not just conventions. They are enforced in `agent/jobs/store.py:16` and hard-coded in `apps/web/src/api.ts:22`.
- `StageContext` is intentionally minimal and should stay that way unless a cross-stage dependency is truly stable and generic. See `agent/stages/base.py:11`.
- `x-fetch` uses a primary local fetch/parse path and only falls back to the skill-based path for article URLs after `XFetchError`; do not silently widen fallback behavior for tweets. See `agent/stages/x_fetch.py:15`.
- `wechat-rewrite` supports chunk-aware continuation prompts so long outputs do not repeat titles and introductions. See `agent/stages/wechat_rewrite.py:16` and `agent/stages/base.py:83`.

## 2. Build & Commands

### Standard Entry Point

- Use the `Makefile` as the canonical workflow entry point. Repository tests explicitly assert the presence of `setup`, `install-playwright`, `check-api`, `backend`, `frontend`, `start`, `dev`, `test`, and `build`. See `Makefile:12` and `tests/test_workspace_layout.py:32`.

### Setup

- `make setup`
  - `uv sync --extra dev`
  - installs renderer dependencies
  - builds the renderer
  - installs web dependencies
  - Source: `Makefile:26`
- `make install-playwright`
  - installs Chromium for the Playwright-based fetch path
  - Source: `Makefile:32`

### Local Development

- `make backend`
  - runs `uvicorn agent.api.main:app`
  - binds to `127.0.0.1:8000`
  - uses `--python 3.11`
  - Source: `Makefile:38`
- `make frontend`
  - runs the Vite dev server for `apps/web`
  - Source: `Makefile:41`
- `make dev` or `make start`
  - starts backend first, waits briefly, then starts the frontend
  - Source: `Makefile:44`
- `scripts/dev.sh`
  - direct backend-only startup equivalent
  - Source: `scripts/dev.sh:1`

### Testing

- `make test`
  - runs Python tests with `pytest`
  - runs renderer tests and renderer build
  - runs web tests and web build
  - Source: `Makefile:61`
- `scripts/test.sh`
  - shell equivalent of the multi-part test workflow
  - Source: `scripts/test.sh:1`
- Backend-only tests:
  - `PYTHONPATH="$ROOT_DIR" uv run --directory "$ROOT_DIR" --python 3.11 --extra dev pytest -v "$ROOT_DIR/tests"`
  - Source: `Makefile:62`
- Web-only tests:
  - `npm --prefix apps/web test`
  - Source: `apps/web/package.json:5`
- Renderer-only tests:
  - `npm --prefix packages/renderer test`
  - Source: `packages/renderer/package.json:6`

### Build

- `make build`
  - builds the renderer, then builds the web app
  - Source: `Makefile:68`
- Web build:
  - `npm --prefix apps/web run build`
  - Source: `apps/web/package.json:5`
- Renderer build:
  - `npm --prefix packages/renderer run build`
  - Source: `packages/renderer/package.json:6`

### External Connectivity Check

- `make check-api`
  - loads `Settings()` from the configured env file
  - asserts `X2W_API_KEY` is non-empty
  - instantiates `ModelGateway`
  - calls `gateway._client.models.list()` against the configured API base
  - Source: `Makefile:35`

## 3. Code Style

### Python

- Target runtime is Python `>=3.11`, but the checked-in commands use Python `3.11` explicitly for backend startup and pytest. See `pyproject.toml:4` and `Makefile:39`.
- Settings, runtime contracts, and validation all rely on Pydantic v2 patterns such as `field_validator`, `model_validator`, and typed models. Keep new config and API payload logic consistent with existing patterns in `agent/config.py:10` and `agent/models/schemas.py:27`.
- Centralize job filesystem and metadata changes in `JobStore` instead of writing directly under `artifacts/`. This keeps `job.json`, SQLite index updates, and concurrency semantics aligned. See `agent/jobs/store.py:39` and `agent/jobs/store.py:286`.
- Centralize model invocation in `ModelGateway`; do not add ad-hoc stage-specific SDK calls unless the architecture changes deliberately. See `agent/models/gateway.py:24`.
- Keep prompts as files in `agent/prompts/` and load them through `load_prompt()` so path traversal checks remain in force. See `agent/prompts/loader.py:7`.

### TypeScript / React

- The web app uses strict TypeScript with `moduleResolution: "Bundler"`, `jsx: "react-jsx"`, and `noEmit: true`. Match existing TS strictness when adding types or API fields. See `apps/web/tsconfig.json:2`.
- `App.tsx` owns UI orchestration; leaf components are presentation-focused. Keep business logic, polling, and artifact fetching centralized unless a clear refactor boundary is introduced. See `apps/web/src/App.tsx:69`.
- Artifact route construction is centralized in `apps/web/src/api.ts:22`; reuse it instead of duplicating route strings.

### Naming and Contract Conventions

- Preserve the stage names exactly: `x-fetch`, `translate`, `review`, `wechat-rewrite`, `render-html`. See `agent/models/schemas.py:60`.
- Preserve artifact filenames exactly: `01-source.md`, `02-translation.md`, `03-reviewed.md`, `04-wechat.md`, `05-wechat.html`. See `agent/jobs/store.py:16`.
- Prompt filenames are part of observable runtime metadata and UI display. Keep them stable unless the prompt-version story is updated end-to-end. See `agent/core/pipeline.py:23` and `apps/web/src/App.tsx:39`.

## 4. Testing

### Frameworks

- Backend tests use `pytest`. Test discovery is configured to `tests/` in `pyproject.toml:18`.
- Frontend tests use `Vitest`. The global Vite test environment is `node`, while browser-style component tests opt into `jsdom` explicitly. See `apps/web/vite.config.ts:16` and `apps/web/src/app.test.tsx:1`.
- Renderer tests also use `Vitest`. See `packages/renderer/package.json:6`.

### Existing Test Coverage Patterns

- Workspace contract tests verify required skeleton files, required `.env.example` keys, and the expected one-command workflow targets in the `Makefile`. See `tests/test_workspace_layout.py:4`.
- Config tests verify defaults, alias env names, `.env` loading, env-over-file precedence, invalid provider rejection, and empty model rejection. See `tests/test_config.py:8`.
- Frontend tests verify canonical artifact URLs, initial UI shell, job list visibility, prompt display, deletion behavior, and failed-stage rendering. See `apps/web/src/app.test.tsx:69`.

### How to Extend Safely

- When changing stage order, job status fields, or artifact names, update backend schemas, `JobStore`, pipeline logic, frontend route builders, and tests together.
- When changing config names or defaults, update `.env.example`, `Settings`, and `tests/test_config.py` together.
- When changing top-level workflow commands, update `Makefile` and `tests/test_workspace_layout.py` together.
- Prefer targeted test runs first, then `make test` before concluding larger changes are safe.

## 5. Security

### Sensitive Inputs

- `X2W_API_KEY` is the primary secret. It is loaded from `.env` or environment variables. `Settings.api_key` is declared with `repr=False`, but that does not make `.env` safe to commit. See `agent/config.py:23`.
- `X2W_X_STORAGE_STATE_PATH` points to a local X login state file for Playwright fetches and should be treated like credential material. See `.env.example:8` and `agent/config.py:25`.

### Input and File Safety

- Prompt loading rejects path traversal by forcing prompt reads to stay under `agent/prompts/`. See `agent/prompts/loader.py:7`.
- Artifact reads and writes are restricted to the fixed allowlist in `JobStore.ALLOWED_ARTIFACTS`. See `agent/jobs/store.py:16`.
- Log filenames may not contain path separators. See `agent/jobs/store.py:87`.
- Supported job input URLs are explicitly constrained to X tweet and article patterns. See `agent/api/routes_jobs.py:10`.

### Runtime Safety

- Renderer output sanitizes raw HTML and blocks unsafe `javascript:` and `data:` URL schemes in links and images. See `packages/renderer/src/render.ts:5`, `packages/renderer/src/render.ts:47`, and `packages/renderer/src/render.ts:111`.
- `ModelGateway` disables SDK auto-retries and implements its own bounded retry loop for retryable connection and server errors. See `agent/models/gateway.py:8` and `agent/models/gateway.py:39`.
- Job execution is protected by run-claim files with a five-minute TTL so the same pending job is not started concurrently. See `agent/jobs/store.py:15` and `agent/jobs/store.py:202`.

### Agent Guidance

- Do not print, copy, or commit real values from `.env`, local storage-state files, or generated article assets unless the task explicitly requires handling them.
- If you need to debug API connectivity, prefer `make check-api` over writing custom probe scripts because it uses the repository's own `Settings` and `ModelGateway` wiring. See `Makefile:35`.

## 6. Configuration

### Environment Model

- Configuration is loaded by `Settings` from `.env` with `env_prefix="X2W_"` and `extra="ignore"`. See `agent/config.py:10`.
- Environment variables override `.env`. This is covered by `tests/test_config.py:51`.

### Supported Keys

- `X2W_API_KEY`
- `X2W_PROVIDER` or `X2W_MODEL_PROVIDER`
- `X2W_API_BASE`
- `X2W_MODEL_TRANSLATE` or `X2W_TRANSLATE_MODEL`
- `X2W_MODEL_REVIEW` or `X2W_REVIEW_MODEL`
- `X2W_MODEL_WECHAT_REWRITE` or `X2W_WECHAT_REWRITE_MODEL`
- `X2W_X_STORAGE_STATE_PATH`

Defaults and aliases are defined in `agent/config.py:18` and exemplified in `.env.example:1`.

### Default Behavior

- Default provider is `qwen`.
- Default API base is `https://dashscope.aliyuncs.com/compatible-mode/v1`.
- Default stage models are:
  - `translate -> qwen-mt-plus`
  - `review -> qwen-mt-plus`
  - `wechat-rewrite -> qwen-mt-plus`
- Default artifact root is `artifacts/`.
- Source: `agent/config.py:18` and `tests/test_config.py:8`.

### Local Networking

- Backend development server: `127.0.0.1:8000`. See `Makefile:38`.
- Frontend dev server: `127.0.0.1:5173`. See `apps/web/vite.config.ts:6`.
- Frontend `/api` requests proxy to the backend during local development. See `apps/web/vite.config.ts:9`.

## 7. Rules File Scan

- No repository-local Cursor rules were found under `.cursor/rules/`.
- No repository-local Copilot instruction file was found at `.github/copilot-instructions.md`.
- No repository-local Trae rules were found under `.trae/rules/`.
- No existing `AGENT.md` or repository-local `AGENTS.md` was present before this file was added.

## 8. Quick Orientation for Future Agents

- Start with `graphify-out/GRAPH_REPORT.md`, `agent/core/pipeline.py`, `agent/jobs/store.py`, `agent/models/schemas.py`, and `apps/web/src/App.tsx`.
- If the task touches workflow behavior, inspect both the backend contract and the frontend assumptions before editing.
- If the task touches prompts or models, inspect `agent/prompts/`, `agent/config.py`, `agent/models/gateway.py`, and the prompt display logic in `apps/web/src/App.tsx:154`.
- If the task touches output rendering or preview safety, inspect `agent/stages/render_html.py` and `packages/renderer/src/render.ts` together.
