import os
from config_loader import runbook_config
from runbook_extractor import extract_runbook
from db_inserter import insert_runbook

source_path = runbook_config["runbooks"]["source_path"]
formats = runbook_config["runbooks"]["supported_formats"]


def ingest():
    for file in os.listdir(source_path):

        if any(file.endswith(ext) for ext in formats):
            file_path = os.path.join(source_path, file)

            print(f"Ingesting: {file}")

            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()

            #LLM extraction returns dict
            runbook_data = extract_runbook(text)

            #DB insertion
            insert_runbook(runbook_data)

    print("All runbooks ingested successfully.")


ingest()
