from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

CANDIDATES = {
    "v0212_payment_routes": ROOT / "app" / "v0212_payment_routes.py",
    "v022_routes": ROOT / "app" / "v022_routes.py",
    "v024_routes": ROOT / "app" / "v024_routes.py",
    "v025_home": ROOT / "app" / "v025_home.py",
    "v026_home": ROOT / "app" / "v026_home.py",
    "v027_home": ROOT / "app" / "v027_home.py",
    "v029_routes": ROOT / "app" / "v029_routes.py",
}

TEXT_SUFFIXES = {".py", ".md", ".sh", ".yml", ".yaml", ".html", ".js", ".css"}


def references_to(module_name: str, own_path: Path):
    patterns = (
        re.compile(rf"\b{re.escape(module_name)}\b"),
        re.compile(rf"\bapp\.{re.escape(module_name)}\b"),
    )
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
        if any(pattern.search(text) for pattern in patterns):
            refs.append(str(path.relative_to(ROOT)))
    return sorted(set(refs))


def classify(refs):
    runtime = [p for p in refs if p.startswith("app/")]
    tests = [p for p in refs if p.startswith("tests/")]
    other = [p for p in refs if p not in runtime and p not in tests]
    return runtime, tests, other


def main():
    print("=== DEAD MODULE REFERENCE INVENTORY ===")
    for name, path in CANDIDATES.items():
        assert path.is_file(), path
        refs = references_to(name, path)
        runtime, tests, other = classify(refs)
        print(
            f"MODULE {name} runtime_refs={len(runtime)} "
            f"test_refs={len(tests)} other_refs={len(other)}"
        )
        for ref in runtime:
            print(f"  RUNTIME_REF {ref}")
        for ref in tests:
            print(f"  TEST_REF {ref}")
        for ref in other:
            print(f"  OTHER_REF {ref}")
        if not runtime:
            print(f"  NO_RUNTIME_IMPORT_CANDIDATE {name}")

    print("dead module reference inventory passed")


if __name__ == "__main__":
    main()
