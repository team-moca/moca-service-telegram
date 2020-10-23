from pathlib import Path
import json

schemas_folder = Path("schemas").rglob("*.schema.json")

schemas = {}

for schema_file in schemas_folder:
    with open(schema_file, 'r') as f:
        schemas[schema_file.name.split(".")[0]] = json.loads(f.read())
