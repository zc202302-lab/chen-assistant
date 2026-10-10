"""Number gaps, raw dates, migration and table/XLSX parity via actual routes."""
import os
from pathlib import Path
import sys
import tempfile
from io import BytesIO
from zipfile import ZipFile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = tempfile.TemporaryDirectory()
os.environ.update({'APP_DB_PATH': str(Path(scratch.name) / 'app.db'), 'APP_USERNAME':'slot-test',
                   'APP_PASSWORD_SALT':'dGVzdHNhbHQ=', 'APP_PASSWORD_HASH':'x',
                   'APP_SESSION_SECRET':'slot-test-secret', 'APP_ENCRYPTION_KEY':'x', 'APP_SECURE_COOKIE':'0'})
from fastapi.testclient import TestClient
from app.main import app
from app.db import db, init_db, now_iso
from app.security import create_session
from app.promotions import ensure_promotion_schema, table_payload, export_table
from app.v026_routes import promotion_bucket


def seed():
    init_db()
    with db() as conn:
        now = now_iso()
        cid = conn.execute('INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)', ('编号测试',now,now)).lastrowid
        other = conn.execute('INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)', ('另一客户',now,now)).lastrowid
        ids = []
        for number, order in [('001234567890123456789',20), ('13800000002',10), ('',30)]:
            ids.append(conn.execute('INSERT INTO services(customer_id,number,sort_order) VALUES(?,?,?)', (cid,number,order)).lastrowid)
        other_sid = conn.execute('INSERT INTO services(customer_id,number) VALUES(?,?)', (other,'999')).lastrowid
        conn.execute('INSERT INTO promotions(service_id,name,expiry_date,status) VALUES(?,?,?,?)', (other_sid,'另一优惠','2030-01-01','active'))
    token, csrf, _ = create_session()
    return cid, ids, other_sid, token, csrf


def xlsx_rows(data):
    ns = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(BytesIO(data)) as archive:
        shared = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        strings = [''.join(node.itertext()) for node in shared.findall('s:si',ns)]
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        rows = []
        for row in sheet.findall('s:sheetData/s:row',ns):
            values = []
            for cell in row.findall('s:c',ns):
                assert cell.get('t') == 's'
                assert cell.find('s:f',ns) is None, 'user text must never become formula'
                values.append(strings[int(cell.find('s:v',ns).text)])
            assert len(values) == 11
            rows.append(values)
        return rows


def main():
    cid, ids, other_sid, token, csrf = seed()
    client = TestClient(app)
    client.cookies.set('session_token',token)
    def save(sid, slot, name, expiry, pid=''):
        return client.post(f'/services/{sid}/promotions-editor-v029', data={'csrf':csrf,'promotion_id':pid,'slot_number':slot,'name':name,'expiry_date':expiry})
    p2 = save(ids[0],2,'=SUM(1,2)','2026/1//2').json()
    assert p2['ok'] and p2['slot_number']==2 and p2['expiry_date']=='2026/1//2'
    p5 = save(ids[0],5,'优惠五','2027/8/9').json()
    assert p5['ok']
    assert save(ids[0],2,'重复','').status_code==400
    assert save(ids[0],6,'越界','').status_code==400
    assert save(other_sid,1,'串客户','',p2['id']).status_code==400
    payload = client.get(f'/customers/{cid}/promotions/table').json()
    assert payload['headers']==['号码','优惠1','到期时间','优惠2','到期时间','优惠3','到期时间','优惠4','到期时间','优惠5','到期时间']
    assert [r[0] for r in payload['rows']]==['001234567890123456789']
    assert payload['service_ids']==[ids[0]]
    row=payload['rows'][0]
    assert row[1:3]==['',''] and row[3:5]==['=SUM(1,2)','2026/1//2'] and row[9:11]==['优惠五','2027/8/9']
    assert xlsx_rows(client.get(f'/customers/{cid}/promotions/table.xlsx').content)==[payload['headers'],*payload['rows']]
    assert save(ids[0],4,'优惠二','2028/3/',p2['id']).status_code==200
    editor=client.get(f'/services/{ids[0]}/promotions-editor-v029').json()['promotions']
    assert [p['slot_number'] for p in editor]==[4,5]
    assert editor[0]['expiry_date']=='2028/3/'
    r=client.post(f"/promotions/{p2['id']}/expiry-v028",data={'csrf':csrf,'expiry_date':'2026/10/1'})
    assert r.status_code==200 and r.json()['expiry_date']=='2026/10/1' and r.json()['bucket']=='expired'
    r=client.post(f"/promotions/{p2['id']}/expiry-v028",data={'csrf':csrf,'expiry_date':''})
    assert r.status_code==200 and r.json()['expiry_date']==''
    assert client.post(f"/promotions/{p2['id']}/expiry-v028",data={'csrf':'bad','expiry_date':'x'}).status_code==403
    assert client.get(f'/customers/{cid}?tab=promotions').status_code==200
    html=client.get(f'/customers/{cid}?tab=promotions').text
    assert 'data-full-promotions' in html and 'data-full-promotions data-table-url' in html
    assert 'manual-date promo-expiry' not in html
    assert client.post(f"/promotions/{p5['id']}/close-editor-v029",data={'csrf':csrf}).status_code==200
    assert client.get(f'/customers/{cid}/promotions/table').json()['rows'][0][9:]==['','']
    with db() as conn:
        # Old records are assigned positions without changing IDs or stored text.
        pid=conn.execute('INSERT INTO promotions(service_id,name,expiry_date,status) VALUES(?,?,?,?)',(ids[0],'旧优惠','2030-01-01','active')).lastrowid
        ensure_promotion_schema(conn);ensure_promotion_schema(conn)
        legacy=conn.execute('SELECT * FROM promotions WHERE id=?',(pid,)).fetchone()
        assert legacy['slot_number']==1 and legacy['expiry_date']=='2030-01-01'
        conn.execute('UPDATE services SET sort_order=1 WHERE id=?',(ids[2],))
        conn.execute('INSERT INTO promotions(service_id,name,expiry_date,status,slot_number) VALUES(?,?,?,?,?)',(ids[2],'空号码优惠','','active',2))
        assert table_payload(conn,cid)['rows'][0][0]==''
        assert table_payload(conn,cid)['service_ids']==[ids[2],ids[0]]
        conn.execute("UPDATE promotions SET status='closed' WHERE service_id=?", (ids[0],))
        assert table_payload(conn,cid)['service_ids']==[ids[2]]
        conn.execute("UPDATE promotions SET status='closed' WHERE service_id=?", (ids[2],))
        empty=table_payload(conn,cid)
        assert empty['rows']==[] and empty['service_ids']==[]
        assert xlsx_rows(export_table(empty))==[empty['headers']]
    assert promotion_bucket('2026/10/1')=='expired'
    assert promotion_bucket('2026/10//1')=='later'
    client.cookies.clear()
    assert client.get(f'/customers/{cid}/promotions/table.xlsx',follow_redirects=False).status_code==303
    print('promotion slots contract passed: raw input, gaps, ordering, isolation, CSRF, migration and XLSX parity')

if __name__=='__main__':
    main()
