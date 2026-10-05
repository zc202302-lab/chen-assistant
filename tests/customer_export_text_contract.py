"""Customer text must round-trip as literal XLSX strings, never formulas/links."""
import io
import os
from pathlib import Path
import sys
import tempfile
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temp = tempfile.TemporaryDirectory()
os.environ['APP_DB_PATH'] = str(Path(temp.name) / 'app.db')
from app.db import db, init_db, now_iso
from app.main import app
from app.v032_customer_exchange_routes import _build_export

init_db()
with db() as conn:
    conn.execute('INSERT INTO customers(name,group_code,relation_summary,created_at,updated_at) VALUES(?,?,?,?,?)',
                 ('=1+1', '00123', 'https://example.invalid/literal', now_iso(), now_iso()))
payload = _build_export()
ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    strings = ET.fromstring(archive.read('xl/sharedStrings.xml'))
    texts = [''.join(node.itertext()) for node in strings.findall(ns + 'si')]
    assert '=1+1' in texts and '00123' in texts and 'https://example.invalid/literal' in texts
    for path in archive.namelist():
        if path.startswith('xl/worksheets/') and path.endswith('.xml'):
            sheet = ET.fromstring(archive.read(path))
            assert not list(sheet.iter(ns + 'f')), 'customer text was exported as a formula'
            assert not list(sheet.iter(ns + 'hyperlink')), 'customer text became a hyperlink'
print('customer export literal-text contract passed')
