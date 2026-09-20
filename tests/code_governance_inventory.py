from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
STATIC_REF_RE = re.compile(r"""(?:src|href)=["'](/static/[^"'?]+)""")

KNOWN_DUPLICATE_SIGNATURES = {
    ("GET", "/customers"),
    ("GET", "/customers/new"),
    ("GET", "/customers/{customer_id}/contacts"),
    ("GET", "/customers/{customer_id}/payment"),
    ("GET", "/customers/{customer_id}/services"),
    ("GET", "/customers/{customer_id}/tasks"),
    ("GET", "/customers/{customer_id}/visits"),
    ("GET", "/life"),
    ("GET", "/life/knowledge"),
    ("GET", "/life/recipes"),
    ("GET", "/products"),
    ("GET", "/services/{service_id}/promotions-editor-v029"),
    ("POST", "/contacts/{contact_id}/delete"),
    ("POST", "/customers/new"),
    ("POST", "/customers/{customer_id}/contacts"),
    ("POST", "/customers/{customer_id}/display-attributes"),
    ("POST", "/customers/{customer_id}/documents-v13"),
    ("POST", "/customers/{customer_id}/invoice-groups"),
    ("POST", "/customers/{customer_id}/payment-status"),
    ("POST", "/customers/{customer_id}/promotions"),
    ("POST", "/customers/{customer_id}/services"),
    ("POST", "/customers/{customer_id}/services/reorder"),
    ("POST", "/customers/{customer_id}/tasks"),
    ("POST", "/customers/{customer_id}/visits"),
    ("POST", "/invoice-groups/{group_id}/delete"),
    ("POST", "/life/knowledge/new"),
    ("POST", "/life/knowledge/{item_id}/edit"),
    ("POST", "/life/recipes/new"),
    ("POST", "/life/recipes/{recipe_id}/cook/start"),
    ("POST", "/life/recipes/{recipe_id}/edit"),
    ("POST", "/promotions/{promotion_id}/close-editor-v029"),
    ("POST", "/promotions/{promotion_id}/name-v030"),
    ("POST", "/promotions/{promotion_id}/renew"),
    ("POST", "/services/{service_id}/attributes"),
    ("POST", "/services/{service_id}/delete"),
    ("POST", "/services/{service_id}/edit"),
    ("POST", "/services/{service_id}/payment-current"),
    ("POST", "/services/{service_id}/payment-review-toggle"),
    ("POST", "/services/{service_id}/payment-status-v03"),
    ("POST", "/services/{service_id}/promotions-editor-v029"),
    ("POST", "/services/{service_id}/runtime-v0212"),
    ("POST", "/services/{service_id}/status-v03"),
    ("POST", "/services/{service_id}/toggle-fixed"),
    ("POST", "/tasks/{task_id}/toggle"),
}

TEXT_SUFFIXES = {".py", ".html", ".js", ".css", ".ps1", ".md", ".sh", ".yml", ".yaml"}



def route_inventory():
    owners = defaultdict(list)
    for route in app.router.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        module = getattr(endpoint, "__module__", "")
        name = getattr(endpoint, "__name__", "")
        for method in sorted(set(getattr(route, "methods", set())) & METHODS):
            owners[(method, path)].append((module, name))
    return owners


def static_inventory():
    referenced = set()
    for template in (ROOT / "app" / "templates").glob("*.html"):
        text = template.read_text(encoding="utf-8")
        referenced.update(match.group(1).removeprefix("/static/") for match in STATIC_REF_RE.finditer(text))
    all_assets = {
        path.name
        for path in (ROOT / "app" / "static").iterdir()
        if path.is_file() and path.suffix.lower() in {".js", ".css", ".ps1"}
    }

    mentions = defaultdict(set)
    skip_roots = {".git", ".venv", "__pycache__"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in skip_roots for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for asset in all_assets:
            if path == ROOT / "app" / "static" / asset:
                continue
            if asset in text:
                mentions[asset].add(str(path.relative_to(ROOT)))
    return all_assets, referenced, mentions


def main():
    owners = route_inventory()
    duplicates = {key: value for key, value in owners.items() if len(value) > 1}

    print("=== ROUTE DUPLICATE INVENTORY ===")
    print(f"route_signatures={len(owners)} duplicate_signatures={len(duplicates)}")
    for (method, path), values in sorted(duplicates.items()):
        rendered = " -> ".join(f"{module}:{name}" for module, name in values)
        print(f"DUP {method} {path} :: {rendered}")

    current_duplicate_signatures = set(duplicates)
    unexpected_duplicates = current_duplicate_signatures - KNOWN_DUPLICATE_SIGNATURES
    assert not unexpected_duplicates, f"new duplicate route signatures: {sorted(unexpected_duplicates)}"
    removed_duplicates = KNOWN_DUPLICATE_SIGNATURES - current_duplicate_signatures
    if removed_duplicates:
        print(f"IMPROVED_DUPLICATES {sorted(removed_duplicates)}")

    all_assets, referenced, mentions = static_inventory()
    unreferenced = sorted(all_assets - referenced)
    orphans = [asset for asset in unreferenced if not mentions.get(asset)]
    print("=== STATIC ASSET INVENTORY ===")
    print(
        f"top_level_assets={len(all_assets)} template_referenced={len(referenced)} "
        f"unreferenced={len(unreferenced)} orphan_candidates={len(orphans)}"
    )
    for asset in unreferenced:
        refs = ",".join(sorted(mentions.get(asset, set())))
        print(f"UNREF {asset} :: refs={refs or '-'}")
    for asset in orphans:
        print(f"ORPHAN_CANDIDATE {asset}")

    key_expected = {
        ("GET", "/customers/{customer_id}"): ("app.v0212_routes", "customer_workspace_v0212"),
        ("GET", "/customers/{customer_id}/payment.xlsx"): ("app.v033_payment_flow_patch", "payment_xlsx_current_workflow_v158"),
        ("GET", "/customers/{customer_id}/payment.txt"): ("app.v033_payment_flow_patch", "payment_txt_current_workflow_v033"),
        ("POST", "/services/{service_id}/payment-current"): ("app.v031_fixed_review_patch", "payment_save_preserve_reviews_v032"),
        ("POST", "/services/{service_id}/payment-review-toggle"): ("app.v031_fixed_review_patch", "payment_review_toggle_preserve_reviews_v032"),
        ("GET", "/work"): ("app.v10_routes", "work_home_v101"),
        ("GET", "/search"): ("app.v10_routes", "work_search_v101"),
        ("GET", "/global-search"): ("app.v101_workspace_routes", "global_search_v101"),
    }
    for key, expected in key_expected.items():
        actual = owners.get(key, [])
        assert actual, f"missing key route: {key}"
        assert actual[0] == expected, (key, actual[0], expected)

    print("code governance inventory passed")


if __name__ == "__main__":
    main()
