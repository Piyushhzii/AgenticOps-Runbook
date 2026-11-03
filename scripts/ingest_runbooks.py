import argparse
import json
import os
import sys

from app.core.config import get_runbook_config, resolve_path
from app.core.database import initialize_database
from app.repositories.runbooks import insert_runbook
from app.services.document_parser import DocumentParseError, parse_source, source_extension
from app.services.llm_gateway import LLMGatewayError, extract_runbook


def load_runbook(source):
    text = parse_source(source)
    if source_extension(source) == ".json":
        return json.loads(text)
    return extract_runbook(text)


def ingest(paths=None, dry_run=False):
    initialize_database()
    if paths is None:
        runbook_config = get_runbook_config()
        source_path = resolve_path(runbook_config["runbooks"]["source_path"])
        formats = tuple(runbook_config["runbooks"]["supported_formats"])
        paths = [
            os.path.join(source_path, name) for name in sorted(os.listdir(source_path))
            if name.lower().endswith(formats)
        ]
    failures = 0
    for source in paths:
        try:
            runbook_data = load_runbook(source)
        except (DocumentParseError, LLMGatewayError, ValueError, OSError) as exc:
            failures += 1
            print(f"Failed: {source} -> {exc}", file=sys.stderr)
            continue
        if dry_run:
            print(json.dumps(runbook_data, indent=2))
            continue
        runbook_id = insert_runbook(runbook_data)
        print(f"Ingested: {source} -> {runbook_id}")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest runbooks from JSON, text, PDF, DOCX, XLSX, PPTX, HTML, Markdown files or URLs"
    )
    parser.add_argument("--file", action="append", help="Runbook path; repeat to ingest multiple files")
    parser.add_argument("--url", action="append", help="http(s) runbook/KB URL; repeat for multiple")
    parser.add_argument("--dry-run", action="store_true", help="Print extracted JSON for review without saving")
    args = parser.parse_args()
    sources = (args.file or []) + (args.url or [])
    sys.exit(1 if ingest(sources or None, dry_run=args.dry_run) else 0)