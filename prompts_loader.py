import os
from config_loader import llm_config

def load_prompt(prompt_key):
    """
    Loads prompt file path from llm_config.yaml using key
    """

    prompt_path = llm_config["prompts"][prompt_key]

    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()
