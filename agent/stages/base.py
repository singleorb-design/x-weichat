from dataclasses import dataclass
from typing import Callable

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.prompts.loader import load_prompt


@dataclass(slots=True)
class StageContext:
    job_id: str
    url: str
    storage_state: str | None = None


def read_stage_markdown(
    *,
    store: JobStore,
    context: StageContext,
    relative_path: str,
) -> str:
    return store.read_artifact(job_id=context.job_id, relative_path=relative_path)


def run_markdown_stage(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
    input_artifact: str,
    output_artifact: str,
    prompt_filename: str,
    model: str,
    build_input: Callable[[str], str],
) -> str:
    source_markdown = read_stage_markdown(
        store=store,
        context=context,
        relative_path=input_artifact,
    )
    output_markdown = gateway.generate_markdown(
        model=model,
        system_prompt=load_prompt(prompt_filename),
        user_prompt=build_input(source_markdown),
    )
    store.write_artifact(
        job_id=context.job_id,
        relative_path=output_artifact,
        content=output_markdown,
    )
    return output_markdown
