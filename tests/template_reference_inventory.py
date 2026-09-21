from __future__ import annotations

from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "app" / "templates"
TEXT_SUFFIXES = {".py", ".html", ".js", ".css", ".md", ".sh", ".yml", ".yaml", ".ps1"}


def references_to(template_name: str, own_path: Path):
    refs = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path == own_path or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if template_name in text:
            refs.append(str(path.relative_to(ROOT)))
    return sorted(set(refs))


def classify(refs):
    runtime = [p for p in refs if p.startswith("app/")]
    tests = [p for p in refs if p.startswith("tests/")]
    other = [p for p in refs if p not in runtime and p not in tests]
    return runtime, tests, other


def main():
    templates = sorted(TEMPLATE_DIR.glob("*.html"))
    print("=== TEMPLATE REFERENCE INVENTORY ===")
    orphans = []
    for path in templates:
        refs = references_to(path.name, path)
        runtime, tests, other = classify(refs)
        print(
            f"TEMPLATE {path.name} runtime_refs={len(runtime)} "
            f"test_refs={len(tests)} other_refs={len(other)}"
        )
        for ref in runtime:
            print(f"  RUNTIME_REF {ref}")
        for ref in tests:
            print(f"  TEST_REF {ref}")
        for ref in other:
            print(f"  OTHER_REF {ref}")
        if not refs:
            orphans.append(path.name)
            print(f"  ORPHAN_TEMPLATE {path.name}")

    print(f"SUMMARY templates={len(templates)} orphan_templates={len(orphans)}")
    print("template reference inventory passed")


if __name__ == "__main__":
    main()
