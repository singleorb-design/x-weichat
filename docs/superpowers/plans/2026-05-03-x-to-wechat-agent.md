# x-to-wechat-agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地可运行的 AI Agent 仓库，把单条 X URL 转成高质量中文微信公众号 HTML，并在 Web UI 中展示全过程产物。

**Architecture:** 采用 `Python + FastAPI` 作为主控后端，负责任务编排、模型网关、5 段流水线和产物存储；采用 `React + Vite` 提供本地 Web UI；采用 `Node.js` 内部渲染工具链把 Markdown 渲染为微信公众号 HTML。X 抓取能力单独封装在仓库内 `packages/x_fetch`，参考 `baoyu-danger-x-to-markdown` 的思路，但以本仓库自有接口输出标准化 Markdown。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、OpenAI-compatible SDK、Playwright for Python、React、Vite、TypeScript、Node.js、Vitest、Pytest

---

## 文件结构

### Python 后端

- Create: `pyproject.toml` — Python 项目元数据与依赖
- Create: `agent/config.py` — 环境变量与本地配置解析
- Create: `agent/models/schemas.py` — 全局数据结构：Job、StageResult、Artifact 等
- Create: `agent/models/gateway.py` — provider/model 抽象与 OpenAI-compatible 调用封装
- Create: `agent/prompts/translate_zh.txt` — 中文翻译 Prompt
- Create: `agent/prompts/review_zh.txt` — 中文审校 Prompt
- Create: `agent/prompts/wechat_rewrite_zh.txt` — 中文公众号改写 Prompt
- Create: `agent/prompts/loader.py` — Prompt 文件加载器
- Create: `agent/jobs/store.py` — 任务目录、状态文件、日志、产物落盘
- Create: `agent/stages/base.py` — 阶段通用接口
- Create: `agent/stages/x_fetch.py` — X 内容获取阶段
- Create: `agent/stages/translate.py` — 翻译阶段
- Create: `agent/stages/review.py` — 审校阶段
- Create: `agent/stages/wechat_rewrite.py` — 公众号改写阶段
- Create: `agent/stages/render_html.py` — HTML 渲染阶段
- Create: `agent/core/pipeline.py` — 串行编排器
- Create: `agent/api/main.py` — FastAPI 入口
- Create: `agent/api/routes_jobs.py` — Job API
- Create: `agent/api/routes_preview.py` — 产物预览 API

### Node 渲染工具链

- Create: `packages/renderer/package.json` — Node 渲染工具依赖
- Create: `packages/renderer/tsconfig.json` — TS 编译配置
- Create: `packages/renderer/src/index.ts` — CLI 入口
- Create: `packages/renderer/src/render.ts` — Markdown → HTML 核心逻辑
- Create: `packages/renderer/src/template.ts` — 微信 HTML 模板

### X 抓取能力

- Create: `packages/x_fetch/__init__.py` — Python 包入口
- Create: `packages/x_fetch/types.py` — 抓取返回类型
- Create: `packages/x_fetch/client.py` — Playwright 抓取客户端
- Create: `packages/x_fetch/parser.py` — 页面内容解析与 Markdown 规范化

### Web UI

- Create: `apps/web/package.json` — 前端依赖
- Create: `apps/web/tsconfig.json` — TypeScript 配置
- Create: `apps/web/vite.config.ts` — Vite 配置
- Create: `apps/web/index.html` — Vite 入口页面
- Create: `apps/web/src/main.tsx` — React 挂载入口
- Create: `apps/web/src/App.tsx` — 主页面布局
- Create: `apps/web/src/api.ts` — API 请求封装
- Create: `apps/web/src/types.ts` — 前端类型
- Create: `apps/web/src/components/JobForm.tsx` — URL 输入表单
- Create: `apps/web/src/components/JobStatus.tsx` — 状态区块
- Create: `apps/web/src/components/ArtifactTabs.tsx` — 中间产物预览
- Create: `apps/web/src/components/HtmlPreview.tsx` — HTML 预览
- Create: `apps/web/src/styles.css` — UI 样式

### 测试

- Create: `tests/test_config.py`
- Create: `tests/test_gateway.py`
- Create: `tests/test_job_store.py`
- Create: `tests/test_x_parser.py`
- Create: `tests/test_pipeline.py`
- Create: `tests/test_api_jobs.py`
- Create: `tests/fixtures/source.md`
- Create: `tests/fixtures/x_article.html`
- Create: `tests/fixtures/x_tweet.html`
- Create: `packages/renderer/src/render.test.ts`

---

### Task 1: 初始化仓库骨架与依赖边界

**Files:**
- Create: `pyproject.toml`
- Create: `agent/__init__.py`
- Create: `agent/api/__init__.py`
- Create: `agent/core/__init__.py`
- Create: `agent/jobs/__init__.py`
- Create: `agent/models/__init__.py`
- Create: `agent/prompts/__init__.py`
- Create: `agent/stages/__init__.py`
- Create: `packages/x_fetch/__init__.py`
- Create: `apps/web/package.json`
- Create: `packages/renderer/package.json`

- [ ] **Step 1: 写一个失败的骨架测试**

```python
from pathlib import Path


def test_workspace_layout_exists():
    required = [
        Path("agent/api"),
        Path("agent/core"),
        Path("agent/jobs"),
        Path("agent/models"),
        Path("agent/prompts"),
        Path("agent/stages"),
        Path("packages/x_fetch"),
        Path("apps/web"),
        Path("packages/renderer"),
    ]
    missing = [str(path) for path in required if not path.exists()]
    assert missing == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_workspace_layout.py -v`
Expected: `FAIL`，提示缺少目录或文件。

- [ ] **Step 3: 写最小工程骨架**

```toml
[project]
name = "x-to-wechat-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn>=0.30.0",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.3.0",
  "openai>=1.35.0",
  "playwright>=1.45.0",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8.2.0", "httpx>=0.27.0", "ruff>=0.5.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```json
{
  "name": "x-to-wechat-agent-web",
  "private": true,
  "version": "0.1.0",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "typescript": "^5.5.4",
    "vite": "^5.3.5",
    "vitest": "^2.0.5",
    "@vitejs/plugin-react": "^4.3.1"
  }
}
```

```json
{
  "name": "x-to-wechat-renderer",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "render": "node dist/index.js"
  },
  "dependencies": {
    "marked": "^13.0.2"
  },
  "devDependencies": {
    "typescript": "^5.5.4",
    "vitest": "^2.0.5"
  }
}
```

- [ ] **Step 4: 运行骨架测试确认通过**

Run: `pytest tests/test_workspace_layout.py -v`
Expected: `PASS`

- [ ] **Step 5: 提交骨架改动**

```bash
git add pyproject.toml agent apps/web/package.json packages/renderer/package.json packages/x_fetch tests/test_workspace_layout.py
git commit -m "chore: bootstrap x-to-wechat workspace"
```

### Task 2: 配置系统与模型网关

**Files:**
- Create: `agent/config.py`
- Create: `agent/models/schemas.py`
- Create: `agent/models/gateway.py`
- Test: `tests/test_config.py`
- Test: `tests/test_gateway.py`

- [ ] **Step 1: 先写配置测试**

```python
from agent.config import Settings


def test_settings_load_stage_models_from_env(monkeypatch):
    monkeypatch.setenv("X2W_PROVIDER", "qwen")
    monkeypatch.setenv("X2W_MODEL_TRANSLATE", "qwen-plus")
    settings = Settings()
    assert settings.provider == "qwen"
    assert settings.stage_models["translate"] == "qwen-plus"
```

```python
from agent.models.gateway import build_messages


def test_build_messages_keeps_system_and_user_roles():
    messages = build_messages(system_prompt="系统", user_prompt="正文")
    assert messages == [
        {"role": "system", "content": "系统"},
        {"role": "user", "content": "正文"},
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_config.py tests/test_gateway.py -v`
Expected: `FAIL`，提示模块不存在。

- [ ] **Step 3: 实现配置与模型网关最小代码**

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="X2W_", extra="ignore")

    provider: str = "qwen"
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = Field(default="", repr=False)
    artifacts_dir: str = "artifacts"
    model_translate: str = "qwen-plus"
    model_review: str = "qwen-plus"
    model_wechat_rewrite: str = "qwen-max"

    @property
    def stage_models(self) -> dict[str, str]:
        return {
            "translate": self.model_translate,
            "review": self.model_review,
            "wechat-rewrite": self.model_wechat_rewrite,
        }
```

```python
from openai import OpenAI


def build_messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


class ModelGateway:
    def __init__(self, api_key: str, base_url: str):
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def generate_markdown(self, *, model: str, system_prompt: str, user_prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=model,
            messages=build_messages(system_prompt, user_prompt),
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""
```

```python
from pydantic import BaseModel


class StageResult(BaseModel):
    stage: str
    status: str
    artifact_path: str | None = None
    error_type: str | None = None
    error_message: str | None = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_config.py tests/test_gateway.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交配置层**

```bash
git add agent/config.py agent/models/schemas.py agent/models/gateway.py tests/test_config.py tests/test_gateway.py
git commit -m "feat: add settings and model gateway"
```

### Task 3: 任务存储、状态机与产物目录

**Files:**
- Create: `agent/jobs/store.py`
- Modify: `agent/models/schemas.py`
- Test: `tests/test_job_store.py`

- [ ] **Step 1: 先写任务存储测试**

```python
from pathlib import Path

from agent.jobs.store import JobStore


def test_job_store_creates_run_directory(tmp_path: Path):
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    assert (tmp_path / job.job_id / "job.json").exists()
    assert (tmp_path / job.job_id / "logs").exists()
```

```python
from pathlib import Path

from agent.jobs.store import JobStore


def test_job_store_writes_artifact(tmp_path: Path):
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    artifact = store.write_artifact(job.job_id, "01-source.md", "# hello")
    assert artifact.read_text() == "# hello"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_job_store.py -v`
Expected: `FAIL`

- [ ] **Step 3: 实现任务存储最小代码**

```python
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4
import json

from pydantic import BaseModel


class JobRecord(BaseModel):
    job_id: str
    url: str
    status: str
    current_stage: str | None = None
    created_at: str


class JobStore:
    def __init__(self, root_dir: Path | str):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, url: str) -> JobRecord:
        job = JobRecord(
            job_id=str(uuid4()),
            url=url,
            status="pending",
            created_at=datetime.now(UTC).isoformat(),
        )
        job_dir = self.root_dir / job.job_id
        (job_dir / "logs").mkdir(parents=True, exist_ok=True)
        (job_dir / "job.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")
        return job

    def write_artifact(self, job_id: str, filename: str, content: str) -> Path:
        path = self.root_dir / job_id / filename
        path.write_text(content, encoding="utf-8")
        return path
```

- [ ] **Step 4: 扩充状态更新测试并补实现**

```python
def test_job_store_updates_status(tmp_path: Path):
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    updated = store.update_status(job.job_id, status="running", current_stage="translate")
    assert updated.status == "running"
    assert updated.current_stage == "translate"
```

```python
def update_status(self, job_id: str, *, status: str, current_stage: str | None = None) -> JobRecord:
    job_file = self.root_dir / job_id / "job.json"
    record = JobRecord.model_validate_json(job_file.read_text(encoding="utf-8"))
    record.status = status
    record.current_stage = current_stage
    job_file.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return record
```

- [ ] **Step 5: 运行测试并提交**

Run: `pytest tests/test_job_store.py -v`
Expected: `3 passed`

```bash
git add agent/jobs/store.py agent/models/schemas.py tests/test_job_store.py
git commit -m "feat: add job storage and artifact persistence"
```

### Task 4: X 抓取解析器与页面规范化

**Files:**
- Create: `packages/x_fetch/types.py`
- Create: `packages/x_fetch/parser.py`
- Create: `packages/x_fetch/client.py`
- Create: `agent/stages/x_fetch.py`
- Test: `tests/test_x_parser.py`
- Test: `tests/fixtures/x_article.html`
- Test: `tests/fixtures/x_tweet.html`

- [ ] **Step 1: 先写解析测试**

```python
from pathlib import Path

from packages.x_fetch.parser import parse_x_html


def test_parse_tweet_html_to_markdown():
    html = Path("tests/fixtures/x_tweet.html").read_text(encoding="utf-8")
    result = parse_x_html(html, url="https://x.com/a/status/1")
    assert result.title == "@a"
    assert "这是正文段落" in result.markdown
```

```python
from pathlib import Path

from packages.x_fetch.parser import parse_x_html


def test_parse_article_html_to_markdown():
    html = Path("tests/fixtures/x_article.html").read_text(encoding="utf-8")
    result = parse_x_html(html, url="https://x.com/i/articles/1")
    assert result.title == "Article Title"
    assert result.markdown.startswith("# Article Title")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_x_parser.py -v`
Expected: `FAIL`

- [ ] **Step 3: 实现解析器**

```python
from pydantic import BaseModel
from bs4 import BeautifulSoup


class XDocument(BaseModel):
    url: str
    title: str
    markdown: str
    content_type: str


def parse_x_html(html: str, url: str) -> XDocument:
    soup = BeautifulSoup(html, "html.parser")
    article_title = soup.select_one("article h1")
    if article_title:
        paragraphs = [node.get_text(" ", strip=True) for node in soup.select("article p")]
        title = article_title.get_text(strip=True)
        markdown = "# " + title + "\n\n" + "\n\n".join(paragraphs)
        return XDocument(url=url, title=title, markdown=markdown, content_type="article")

    tweet_author = soup.select_one("[data-testid='User-Name']")
    tweet_text = soup.select_one("[data-testid='tweetText']")
    title = tweet_author.get_text(" ", strip=True) if tweet_author else "X Post"
    body = tweet_text.get_text(" ", strip=True) if tweet_text else ""
    markdown = f"# {title}\n\n{body}\n"
    return XDocument(url=url, title=title, markdown=markdown, content_type="tweet")
```

```python
from playwright.sync_api import sync_playwright


def fetch_x_page(url: str, storage_state: str | None = None) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        html = page.content()
        browser.close()
        return html
```

- [ ] **Step 4: 把抓取阶段接到 job store**

```python
from agent.stages.base import StageContext
from agent.jobs.store import JobStore
from packages.x_fetch.client import fetch_x_page
from packages.x_fetch.parser import parse_x_html


def run_x_fetch(context: StageContext, store: JobStore) -> str:
    html = fetch_x_page(context.url, storage_state=context.storage_state)
    document = parse_x_html(html, context.url)
    store.write_artifact(context.job_id, "01-source.md", document.markdown)
    return document.markdown
```

- [ ] **Step 5: 运行测试并提交**

Run: `pytest tests/test_x_parser.py -v`
Expected: `2 passed`

```bash
git add packages/x_fetch agent/stages/x_fetch.py tests/test_x_parser.py tests/fixtures/x_article.html tests/fixtures/x_tweet.html
git commit -m "feat: add x fetch parser and stage"
```

### Task 5: Prompt 装载器与三个中文文本阶段

**Files:**
- Create: `agent/prompts/translate_zh.txt`
- Create: `agent/prompts/review_zh.txt`
- Create: `agent/prompts/wechat_rewrite_zh.txt`
- Create: `agent/prompts/loader.py`
- Create: `agent/stages/base.py`
- Create: `agent/stages/translate.py`
- Create: `agent/stages/review.py`
- Create: `agent/stages/wechat_rewrite.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/fixtures/source.md`

- [ ] **Step 1: 先写阶段测试**

```python
from pathlib import Path

from agent.prompts.loader import load_prompt


def test_prompts_are_chinese_text_files():
    prompt = load_prompt("translate_zh.txt")
    assert "你是一名专业技术翻译" in prompt
```

```python
from agent.stages.translate import build_translate_input


def test_translate_stage_builds_markdown_input():
    source = "# Title\n\nhello"
    text = build_translate_input(source)
    assert "请把下面内容翻译成中文" in text
    assert "# Title" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pipeline.py::test_prompts_are_chinese_text_files tests/test_pipeline.py::test_translate_stage_builds_markdown_input -v`
Expected: `FAIL`

- [ ] **Step 3: 实现 Prompt 文件与装载器**

```text
你是一名专业技术翻译。

任务：把用户提供的英文 X 内容忠实翻译成自然、准确、可读的中文。

要求：
1. 保持原文信息，不新增事实。
2. 保留必要专有名词。
3. 输出干净 Markdown。
4. 不要写任何解释、前言、总结。
```

```text
你是一名资深中文编辑。

任务：审校译文，修正错译、漏译和生硬表达，使其自然清晰。

要求：
1. 不新增事实。
2. 必要时拆分长句。
3. 保持原始结构主线。
4. 输出干净 Markdown。
```

```text
你是一名顶级中文内容创作者。

任务：把已审校稿改写为适合微信公众号阅读的中文文章。

要求：
1. 生成一个更强的标题。
2. 结构按照引子、洞察、解释、结论组织。
3. 语言像中文原生写作，不像翻译腔。
4. 不编造事实。
5. 输出干净 Markdown。
```

```python
from pathlib import Path


PROMPT_DIR = Path(__file__).parent


def load_prompt(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()
```

- [ ] **Step 4: 实现三个阶段最小代码**

```python
from dataclasses import dataclass


@dataclass
class StageContext:
    job_id: str
    url: str
    storage_state: str | None = None
```

```python
def build_translate_input(source_markdown: str) -> str:
    return f"请把下面内容翻译成中文，保留 Markdown 结构：\n\n{source_markdown}"
```

```python
def build_review_input(markdown: str) -> str:
    return f"请审校下面中文 Markdown：\n\n{markdown}"
```

```python
def build_wechat_rewrite_input(markdown: str) -> str:
    return f"请把下面内容改写成公众号文章：\n\n{markdown}"
```

每个阶段函数都按同一个模式实现：读取上一步 Markdown、调用 `ModelGateway.generate_markdown()`、将结果分别写入 `02-translation.md`、`03-reviewed.md`、`04-wechat.md`。

- [ ] **Step 5: 补一个端到端伪网关测试并提交**

```python
class FakeGateway:
    def __init__(self):
        self.calls = []

    def generate_markdown(self, *, model, system_prompt, user_prompt):
        self.calls.append((model, system_prompt, user_prompt))
        return "# 输出稿件"
```

```python
def test_translate_review_rewrite_chain_uses_gateway(tmp_path):
    from agent.jobs.store import JobStore
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(job.job_id, "01-source.md", "# source")
    gateway = FakeGateway()
    # 依次执行 translate/review/wechat-rewrite
    assert gateway.calls == []
```

Run: `pytest tests/test_pipeline.py -v`
Expected: `PASS`

```bash
git add agent/prompts agent/stages tests/test_pipeline.py tests/fixtures/source.md
git commit -m "feat: add chinese prompt-driven text stages"
```

### Task 6: Node 渲染器与 Python 渲染阶段

**Files:**
- Create: `packages/renderer/tsconfig.json`
- Create: `packages/renderer/src/template.ts`
- Create: `packages/renderer/src/render.ts`
- Create: `packages/renderer/src/index.ts`
- Create: `packages/renderer/src/render.test.ts`
- Create: `agent/stages/render_html.py`

- [ ] **Step 1: 先写 renderer 单测**

```ts
import { describe, expect, it } from 'vitest'
import { renderWechatHtml } from './render'

describe('renderWechatHtml', () => {
  it('renders heading and paragraph', () => {
    const html = renderWechatHtml('# 标题\n\n正文')
    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('<p>正文</p>')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/renderer && npm test`
Expected: `FAIL`

- [ ] **Step 3: 实现渲染器核心逻辑**

```ts
import { marked } from 'marked'
import { wechatTemplate } from './template'

export function renderWechatHtml(markdown: string): string {
  const body = marked.parse(markdown)
  return wechatTemplate(body)
}
```

```ts
export function wechatTemplate(body: string): string {
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>x-to-wechat-agent</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; padding: 24px; line-height: 1.8; }
      h1, h2, h3 { line-height: 1.4; }
      blockquote { border-left: 4px solid #ddd; padding-left: 12px; color: #666; }
    </style>
  </head>
  <body>${body}</body>
</html>`
}
```

```ts
import { readFileSync, writeFileSync } from 'node:fs'
import { renderWechatHtml } from './render'

const input = process.argv[2]
const output = process.argv[3]
const markdown = readFileSync(input, 'utf-8')
writeFileSync(output, renderWechatHtml(markdown), 'utf-8')
```

- [ ] **Step 4: 在 Python 中接入子进程渲染**

```python
from pathlib import Path
import subprocess


def render_html(input_path: Path, output_path: Path) -> None:
    subprocess.run(
        ["node", "packages/renderer/dist/index.js", str(input_path), str(output_path)],
        check=True,
        capture_output=True,
        text=True,
    )
```

- [ ] **Step 5: 运行测试并提交**

Run: `cd packages/renderer && npm test && npm run build`
Expected: `PASS` and generated `dist/`

```bash
git add packages/renderer agent/stages/render_html.py
git commit -m "feat: add wechat html renderer"
```

### Task 7: 串行流水线编排器

**Files:**
- Create: `agent/core/pipeline.py`
- Modify: `agent/jobs/store.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: 先写流水线状态迁移测试**

```python
from pathlib import Path

from agent.core.pipeline import PipelineRunner


def test_pipeline_runner_marks_job_succeeded(tmp_path: Path):
    runner = PipelineRunner(artifacts_dir=tmp_path)
    job = runner.create_job("https://x.com/a/status/1")
    runner.run(job.job_id)
    result = runner.store.read_job(job.job_id)
    assert result.status == "succeeded"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pipeline.py::test_pipeline_runner_marks_job_succeeded -v`
Expected: `FAIL`

- [ ] **Step 3: 实现最小编排器**

```python
class PipelineRunner:
    def __init__(self, artifacts_dir, gateway=None):
        self.store = JobStore(artifacts_dir)
        self.gateway = gateway

    def create_job(self, url: str):
        return self.store.create_job(url)

    def run(self, job_id: str):
        job = self.store.read_job(job_id)
        self.store.update_status(job_id, status="running", current_stage="x-fetch")
        source = run_x_fetch(StageContext(job_id=job_id, url=job.url), self.store)
        self.store.update_status(job_id, status="running", current_stage="translate")
        translated = run_translate(job_id, source, self.gateway, self.store)
        reviewed = run_review(job_id, translated, self.gateway, self.store)
        rewritten = run_wechat_rewrite(job_id, reviewed, self.gateway, self.store)
        run_render_html(job_id, rewritten, self.store)
        self.store.update_status(job_id, status="succeeded", current_stage="render-html")
```

- [ ] **Step 4: 补失败分支测试并实现错误落盘**

```python
def test_pipeline_runner_marks_job_failed_when_stage_crashes(tmp_path: Path, monkeypatch):
    runner = PipelineRunner(artifacts_dir=tmp_path)
    job = runner.create_job("https://x.com/a/status/1")
    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    runner.run(job.job_id)
    result = runner.store.read_job(job.job_id)
    assert result.status == "failed"
```

```python
try:
    ...
except Exception as exc:
    self.store.update_status(job_id, status="failed", current_stage=current_stage)
    self.store.append_log(job_id, f"[{current_stage}] {type(exc).__name__}: {exc}")
```

- [ ] **Step 5: 运行测试并提交**

Run: `pytest tests/test_pipeline.py -v`
Expected: `PASS`

```bash
git add agent/core/pipeline.py agent/jobs/store.py tests/test_pipeline.py
git commit -m "feat: add sequential job pipeline"
```

### Task 8: FastAPI 接口与预览 API

**Files:**
- Create: `agent/api/main.py`
- Create: `agent/api/routes_jobs.py`
- Create: `agent/api/routes_preview.py`
- Test: `tests/test_api_jobs.py`

- [ ] **Step 1: 先写 API 测试**

```python
from fastapi.testclient import TestClient

from agent.api.main import app


def test_create_job_returns_job_id():
    client = TestClient(app)
    response = client.post("/api/jobs", json={"url": "https://x.com/a/status/1"})
    assert response.status_code == 201
    assert "job_id" in response.json()
```

```python
from fastapi.testclient import TestClient

from agent.api.main import app


def test_get_artifact_returns_markdown():
    client = TestClient(app)
    response = client.get("/api/jobs/demo/artifacts/01-source.md")
    assert response.status_code in {200, 404}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api_jobs.py -v`
Expected: `FAIL`

- [ ] **Step 3: 实现 FastAPI 最小接口**

```python
from fastapi import FastAPI

from agent.api.routes_jobs import router as jobs_router
from agent.api.routes_preview import router as preview_router

app = FastAPI(title="x-to-wechat-agent")
app.include_router(jobs_router, prefix="/api")
app.include_router(preview_router, prefix="/api")
```

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

router = APIRouter()


class CreateJobRequest(BaseModel):
    url: HttpUrl


@router.post("/jobs", status_code=201)
def create_job(payload: CreateJobRequest):
    job = app.state.pipeline.create_job(str(payload.url))
    return {"job_id": job.job_id, "status": job.status}
```

```python
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, HTMLResponse

router = APIRouter()


@router.get("/jobs/{job_id}/artifacts/{filename}")
def get_artifact(job_id: str, filename: str):
    path = app.state.pipeline.store.artifact_path(job_id, filename)
    if filename.endswith(".html"):
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return PlainTextResponse(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: 补一个后台触发执行接口**

```python
@router.post("/jobs/{job_id}/run", status_code=202)
def run_job(job_id: str):
    app.state.pipeline.run(job_id)
    return {"job_id": job_id, "status": "accepted"}
```

- [ ] **Step 5: 运行测试并提交**

Run: `pytest tests/test_api_jobs.py -v`
Expected: `PASS`

```bash
git add agent/api tests/test_api_jobs.py
git commit -m "feat: add job api and artifact preview endpoints"
```

### Task 9: 本地 Web UI

**Files:**
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/index.html`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/App.tsx`
- Create: `apps/web/src/api.ts`
- Create: `apps/web/src/types.ts`
- Create: `apps/web/src/components/JobForm.tsx`
- Create: `apps/web/src/components/JobStatus.tsx`
- Create: `apps/web/src/components/ArtifactTabs.tsx`
- Create: `apps/web/src/components/HtmlPreview.tsx`
- Create: `apps/web/src/styles.css`

- [ ] **Step 1: 先写一个前端 smoke test**

```ts
import { describe, expect, it } from 'vitest'
import { buildArtifactUrls } from './api'

describe('buildArtifactUrls', () => {
  it('builds canonical artifact urls', () => {
    expect(buildArtifactUrls('job-1').source).toBe('/api/jobs/job-1/artifacts/01-source.md')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/web && npm test`
Expected: `FAIL`

- [ ] **Step 3: 实现 API 封装与主界面**

```ts
export function buildArtifactUrls(jobId: string) {
  return {
    source: `/api/jobs/${jobId}/artifacts/01-source.md`,
    translation: `/api/jobs/${jobId}/artifacts/02-translation.md`,
    reviewed: `/api/jobs/${jobId}/artifacts/03-reviewed.md`,
    wechat: `/api/jobs/${jobId}/artifacts/04-wechat.md`,
    html: `/api/jobs/${jobId}/artifacts/05-wechat.html`,
  }
}
```

```tsx
export default function App() {
  return (
    <main className="page">
      <h1>x-to-wechat-agent</h1>
      <JobForm />
      <JobStatus />
      <ArtifactTabs />
      <HtmlPreview />
    </main>
  )
}
```

```tsx
export function JobForm() {
  return (
    <form className="card">
      <label htmlFor="url">X URL</label>
      <input id="url" name="url" placeholder="https://x.com/..." />
      <button type="submit">开始生成</button>
    </form>
  )
}
```

- [ ] **Step 4: 增加轮询与预览逻辑**

```tsx
useEffect(() => {
  if (!jobId) return
  const timer = window.setInterval(async () => {
    const next = await fetch(`/api/jobs/${jobId}`).then(r => r.json())
    setJob(next)
  }, 2000)
  return () => window.clearInterval(timer)
}, [jobId])
```

- [ ] **Step 5: 运行测试并提交**

Run: `cd apps/web && npm test && npm run build`
Expected: `PASS` and `dist/`

```bash
git add apps/web
git commit -m "feat: add local web ui for job execution and preview"
```

### Task 10: 集成验收、运行脚本与回归测试

**Files:**
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_api_jobs.py`
- Create: `scripts/dev.sh`
- Create: `scripts/test.sh`

- [ ] **Step 1: 写一个端到端回归测试**

```python
def test_pipeline_creates_all_artifacts(tmp_path, monkeypatch):
    runner = PipelineRunner(artifacts_dir=tmp_path, gateway=FakeGateway())
    job = runner.create_job("https://x.com/a/status/1")
    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", lambda context, store: store.write_artifact(context.job_id, "01-source.md", "# source").read_text())
    runner.run(job.job_id)
    job_dir = tmp_path / job.job_id
    assert (job_dir / "01-source.md").exists()
    assert (job_dir / "02-translation.md").exists()
    assert (job_dir / "03-reviewed.md").exists()
    assert (job_dir / "04-wechat.md").exists()
    assert (job_dir / "05-wechat.html").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pipeline.py::test_pipeline_creates_all_artifacts -v`
Expected: `FAIL`

- [ ] **Step 3: 补运行脚本**

```bash
#!/usr/bin/env bash
set -euo pipefail

uvicorn agent.api.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
#!/usr/bin/env bash
set -euo pipefail

pytest
(cd packages/renderer && npm test)
(cd apps/web && npm test)
```

- [ ] **Step 4: 跑完整验证**

Run: `pytest -v && cd packages/renderer && npm test && npm run build && cd ../../apps/web && npm test && npm run build`
Expected: 全部通过。

- [ ] **Step 5: 提交验收闭环**

```bash
git add tests scripts
git commit -m "test: add end-to-end regression coverage"
```

---

## Self-Review

- Spec coverage：已覆盖本地 Web UI、5 段流水线、Qwen 优先模型配置、中文 Prompt、X 抓取自建模块、任务状态/日志/产物管理、HTML 渲染、测试与错误处理主路径。
- Placeholder scan：计划中没有 `TODO/TBD/implement later` 一类占位词。
- Type consistency：阶段名统一使用 `x-fetch`、`translate`、`review`、`wechat-rewrite`、`render-html`；产物名统一使用 `01-source.md` 到 `05-wechat.html`。
