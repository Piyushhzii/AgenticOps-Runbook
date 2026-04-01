'''import yaml
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_config(relative_path):
    full_path = os.path.join(BASE_DIR, relative_path)

    with open(full_path, "r") as f:
        return yaml.safe_load(f)

llm_config = load_config("configs/llm_config.yaml")
db_config = load_config("configs/db_config.yaml")
runbook_config = load_config("configs/runbook_config.yaml")
'''

import yaml
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_config(relative_path):
    full_path = os.path.join(BASE_DIR, relative_path)
    
    print("Looking for:", full_path)
    print("Exists?", os.path.exists(full_path))
    
    if not os.path.exists(full_path):
        raise FileNotFoundError("Missing: " + full_path)
    
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if config is None:
            raise ValueError("Empty YAML: " + full_path)
        print(f"Loaded {relative_path}")
        return config
    except Exception as e:
        raise ValueError("YAML load failed " + full_path + ": " + str(e))

llm_config = load_config("configs/llm_config.yaml")
db_config = load_config("configs/db_config.yaml")
runbook_config = load_config("configs/runbook_config.yaml")
