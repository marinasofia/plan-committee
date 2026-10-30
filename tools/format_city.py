"""Rewrites cities/*/city.json in the house style: one setting per line, one hand picked spot per line.
Run `python3 tools/format_city.py` after editing a city file; CI checks every city file is valid."""
import json
from pathlib import Path


def dump(city):
    out = []
    for k, v in city.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            items = ",\n".join("    " + json.dumps(x, ensure_ascii=False) for x in v)
            out.append(f'  "{k}": [\n{items}\n  ]')
        else:
            out.append(f'  "{k}": {json.dumps(v, ensure_ascii=False)}')
    return "{\n" + ",\n".join(out) + "\n}\n"


if __name__ == "__main__":
    for p in sorted(Path(__file__).resolve().parent.parent.glob("cities/*/city.json")):
        p.write_text(dump(json.loads(p.read_text(encoding="utf-8"))), encoding="utf-8")
        print("formatted", p.parent.name)
