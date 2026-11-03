import os
from functools import lru_cache

import yaml
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(BASE_DIR, ".env"))


def resolve_path(relative_path):
    return os.path.join(BASE_DIR, relative_path)


def load_yaml(relative_path):
    full_path = resolve_path(relative_path)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Missing config file: {full_path}")

    with open(full_path, "r", encoding="utf-8") as file_handle:
        data = yaml.safe_load(file_handle)

    if data is None:
        raise ValueError(f"Empty YAML config: {full_path}")

    return data


@lru_cache(maxsize=1)
def get_llm_config():
    return load_yaml("configs/llm_config.yaml")


@lru_cache(maxsize=1)
def get_db_config():
    return load_yaml("configs/db_config.yaml")


@lru_cache(maxsize=1)
def get_runbook_config():
    return load_yaml("configs/runbook_config.yaml")


def get_env(name, default=None):
    return os.getenv(name, default)