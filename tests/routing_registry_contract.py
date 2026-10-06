"""Preserve every pre-refactor runtime owner, order and static-vs-ID match."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = tempfile.TemporaryDirectory()
os.environ['APP_DB_PATH'] = str(Path(scratch.name) / 'app.db')
from app.main import app
from app.routing import route_inventory, configure_routes
from starlette.routing import Match

expected = json.loads((ROOT / 'docs/RUNTIME_ROUTES.json').read_text())
# PR #128 adds exactly this independent interface. Permit its reviewed addition
# without changing the ownership/order baseline of any of the 186 existing routes.
# Other new routes still require a deliberate contract update.
optional_batch_route = {
    'path': '/work/number-inbox/export-group-batch', 'methods': ['POST'],
    'module': 'app.v162_number_inbox', 'name': 'number_inbox_export_group_batch',
}
actual = route_inventory(app)
known = {(row['path'], tuple(row['methods'])) for row in expected}
extra = [row for row in actual if (row['path'], tuple(row['methods'])) not in known]
assert extra in ([], [optional_batch_route]), 'unreviewed additional routes'
retained = [row for row in actual if (row['path'], tuple(row['methods'])) in known]
assert retained == expected, 'existing runtime route ownership/order changed'
for path, owner in [('/customers/new', 'app.v032_customer_import_routes'),
                    ('/customers/123', 'app.v0212_routes'),
                    ('/work', 'app.v10_routes'), ('/life', 'app.v10_routes')]:
    scope = {'type': 'http', 'path': path, 'method': 'GET'}
    winner = next(r for r in app.routes if r.matches(scope)[0] == Match.FULL)
    assert winner.endpoint.__module__ == owner, path
try:
    configure_routes(app)
except RuntimeError:
    pass
else:
    raise AssertionError('duplicate configuration must be rejected')
assert route_inventory(app) == actual
print('routing registry contract passed: 186 existing routes and match boundaries; additions:', len(extra))
