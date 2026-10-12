"""Spreadsheet integrity: atomic edits, compatibility, formats, export and stale clients."""
import copy
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

from cryptography.fernet import Fernet
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix='chen-sheet-contract-')
os.environ.update(APP_DB_PATH=str(Path(TMP.name)/'app.db'), APP_USERNAME='sheet-test',
    APP_PASSWORD_SALT='dGVzdHNhbHQ=', APP_PASSWORD_HASH='x', APP_SESSION_SECRET='sheet-contract',
    APP_ENCRYPTION_KEY=Fernet.generate_key().decode(), APP_SECURE_COOKIE='0')
from fastapi.testclient import TestClient
from app.main import app
from app.db import db, init_db
from app.security import create_session
from app.work_lists import ensure_work_lists_schema
from app.work_list_sheet import get_layout
from app.work_list_excel import ExcelTable


def blank():
    return {'fields':[{'id':f'new_c{i}','label':f'列{i+1}'} for i in range(3)],
        'rows':[{'id':f'new_r{i}','values':['','','']} for i in range(4)],
        'layout':{'widths':{},'heights':{},'cells':{},'merges':[]}}


def state(client, path):
    page = client.get(path)
    assert page.status_code == 200
    return json.loads(re.search(r'<script id="work-sheet-data" type="application/json">(.*?)</script>', page.text, re.S)[1])


def main():
    init_db(); ensure_work_lists_schema()
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        assert client.post('/work/lists/1/settings', json={'csrf':csrf}, follow_redirects=False).status_code == 303
        client.cookies.set('session_token',token)
        result = client.post('/work/lists', data={'csrf':csrf,'title':'网页表格','sheet_payload':json.dumps(blank())}, follow_redirects=False)
        assert result.status_code == 303, result.text
        path = result.headers['location']
        data = state(client,path)
        assert len(data['fields'])==3 and len(data['rows'])==4
        assert client.post(path+'/settings',json=data).status_code == 403
        data['csrf']=csrf
        data['rows'][0]['values'][0]='000123'
        data['rows'][1]['values'][0]='=SUM(1,2)'
        data['rows'][0]['values'][1]='  保留空格  '
        data['fields'][0]['label']='号码'
        r,c=data['rows'][0]['id'],data['fields'][0]['id']
        data['layout'].update(widths={c:240},heights={r:64},cells={'h|'+c:{'bold':True,'background':'#225588','color':'#FFFFFF'}})
        result=client.post(path+'/settings',json=data)
        assert result.status_code==200,result.text
        saved=result.json()
        assert saved['rows'][0]['values'][0]=='000123'
        assert saved['rows'][0]['values'][1]=='  保留空格  '
        assert saved['layout']['widths'][c]==240 and saved['layout']['heights'][r]==64
        assert client.post(path+'/settings',json=data).status_code==409
        broken=copy.deepcopy(saved)|{'csrf':csrf}
        broken['rows'][0]['values'][0]='should rollback'
        broken['layout']['cells'][r+'|'+c]={'background':'url(https://example.com)'}
        assert client.post(path+'/settings',json=broken).status_code==400
        assert state(client,path)['rows'][0]['values'][0]=='000123'
        broken=copy.deepcopy(saved)|{'csrf':csrf}
        broken['rows'][0],broken['rows'][1]=broken['rows'][1],broken['rows'][0]
        assert client.post(path+'/settings',json=broken).status_code==409
        broken=copy.deepcopy(saved)|{'csrf':csrf}
        broken['fields'][0]['id']='999999'
        assert client.post(path+'/settings',json=broken).status_code==409
        exported=client.get(path+'/export.xlsx')
        assert exported.status_code==200
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            xml=archive.read('xl/worksheets/sheet1.xml').decode()
            assert '<f>' not in xml
            assert 'autoFilter' in xml and 'customHeight="1"' in xml
            assert 'FF225588' in archive.read('xl/styles.xml').decode()
        reader=ExcelTable(exported.content,'export.xlsx')
        table=reader.read('清单',preserve_format=True);reader.close()
        assert table['columns'][0]['label']=='号码'
        assert table['rows'][0]['cells'][0]=='000123'
        assert table['layout']['heights']['2']==64
        # A legacy record form writes independently; stale whole-sheet edits must fail.
        current=state(client,path)
        with db() as conn:
            record_id=int(current['rows'][0]['id'])
            conn.execute('UPDATE work_list_records SET note=?,status=?,revision=revision+1 WHERE id=?',('保留备注','done',record_id))
        assert client.post(path+'/settings',json=current|{'csrf':csrf}).status_code==409
        current=state(client,path)
        current['rows'][0]['values'][1]='保留关联项'
        assert client.post(path+'/settings',json=current|{'csrf':csrf}).status_code==200
        with db() as conn:
            record=conn.execute('SELECT note,status FROM work_list_records WHERE id=?',(record_id,)).fetchone()
            assert record['note']=='保留备注' and record['status']=='done'
        current=state(client,path)
        removed_field=current['fields'][1]['id']
        removed_row=current['rows'][-1]['id']
        current['layout']['widths'][removed_field]=180
        current['layout']['heights'][removed_row]=44
        current['layout']['cells']['h|'+removed_field]={'bold':True}
        current['layout']['cells'][current['rows'][0]['id']+'|'+removed_field]={'italic':True}
        current['layout']['merges']=[{'rows':[current['rows'][0]['id']],
                                      'cols':[current['fields'][0]['id'],removed_field]}]
        result=client.post(path+'/settings',json=current|{'csrf':csrf})
        assert result.status_code==200,result.text
        current=state(client,path)
        removed_field=current['fields'].pop(1)['id']
        removed_row=current['rows'].pop()['id']
        for row in current['rows']:
            row['values'].pop(1)
        del current['layout']['widths'][removed_field]
        del current['layout']['heights'][removed_row]
        del current['layout']['cells']['h|'+removed_field]
        del current['layout']['cells'][current['rows'][0]['id']+'|'+removed_field]
        current['layout']['merges']=[]
        result=client.post(path+'/settings',json=current|{'csrf':csrf})
        assert result.status_code==200,result.text
        reduced=state(client,path)
        assert len(reduced['fields'])==2 and len(reduced['rows'])==3
        assert reduced['rows'][0]['values'][0]=='000123'
        assert reduced['layout']['merges']==[]
        assert removed_field not in reduced['layout']['widths']
        assert removed_row not in reduced['layout']['heights']
        with db() as conn:
            assert conn.execute('SELECT 1 FROM work_list_fields WHERE id=?',(int(removed_field),)).fetchone() is None
            assert conn.execute('SELECT 1 FROM work_list_records WHERE id=?',(int(removed_row),)).fetchone() is None
            assert all(removed_field not in json.loads(row['values_json']) for row in conn.execute(
                'SELECT values_json FROM work_list_records WHERE list_id=?',(int(path.rsplit('/',1)[1]),)))
        current=state(client,path)
        assert client.post(path+'/archive',data={'csrf':csrf,'revision':current['revision']},follow_redirects=False).status_code==303
        assert client.post(path+'/settings',json=current|{'csrf':csrf}).status_code==409
        # Invalid creation must roll back the list and every field/row.
        with db() as conn:
            count=conn.execute('SELECT COUNT(*) FROM work_lists').fetchone()[0]
        bad=blank();bad['rows'][3]['values'][0]='x'*4001
        result=client.post('/work/lists',data={'csrf':csrf,'title':'拒绝半张表','sheet_payload':json.dumps(bad)})
        assert result.status_code==400,result.text
        with db() as conn:
            assert conn.execute('SELECT COUNT(*) FROM work_lists').fetchone()[0]==count
    print('Spreadsheet integrity contract passed')


if __name__=='__main__':
    main()
