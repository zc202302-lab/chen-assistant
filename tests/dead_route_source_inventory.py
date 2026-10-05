from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def route_signature(route):
    path = getattr(route, "path", "")
    methods = tuple(sorted(set(getattr(route, "methods", set())) & METHODS))
    endpoint = getattr(route, "endpoint", None)
    module = getattr(endpoint, "__module__", "")
    name = getattr(endpoint, "__name__", "")
    return path, methods, module, name


def main_report():
    live_ids = {id(route) for route in main.app.router.routes}
    groups = list(main.app.state.route_source_groups.items())
    assert groups, "runtime routing registry must retain its source groups"

    print("=== ROUTE SOURCE GROUP INVENTORY ===")
    fully_dead = []
    total_source_routes = 0
    total_live = 0
    total_dead = 0

    for name, routes in sorted(groups):
        live = [route for route in routes if id(route) in live_ids]
        dead = [route for route in routes if id(route) not in live_ids]
        total_source_routes += len(routes)
        total_live += len(live)
        total_dead += len(dead)
        print(f"GROUP {name} total={len(routes)} live={len(live)} dead={len(dead)}")
        if routes and not live:
            fully_dead.append(name)
        for route in dead:
            path, methods, module, endpoint = route_signature(route)
            print(
                f"  DEAD {','.join(methods) or '-'} {path} "
                f":: {module}:{endpoint}"
            )

    print(
        f"SUMMARY source_routes={total_source_routes} live={total_live} "
        f"dead={total_dead} fully_dead_groups={len(fully_dead)}"
    )
    for name in fully_dead:
        print(f"FULLY_DEAD_GROUP {name}")

    # Guard the important premise of this inventory: the live router itself must
    # already be unique after the previous governance stage.
    signatures = set()
    duplicates = []
    for route in main.app.router.routes:
        path = getattr(route, "path", "")
        methods = tuple(sorted(set(getattr(route, "methods", set())) & METHODS))
        key = (path, methods)
        if key in signatures:
            duplicates.append(key)
        signatures.add(key)
    assert not duplicates, duplicates
    print("dead route source inventory passed")


if __name__ == "__main__":
    main_report()

