from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parent


def load_prompt(filename: str) -> str:
    prompt_path = (PROMPT_DIR / filename).resolve()

    try:
        prompt_path.relative_to(PROMPT_DIR)
    except ValueError as exc:
        raise ValueError(
            f"Prompt path traversal is not allowed: {filename}"
        ) from exc

    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {filename}")

    return prompt_path.read_text(encoding="utf-8").strip()
