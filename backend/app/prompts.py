from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str):
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
