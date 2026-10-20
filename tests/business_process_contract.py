"""Real authenticated process CRUD, ordered steps, private images and conflict rollback."""
from io import BytesIO
from PIL import Image
from v162_number_inbox_contract import TestClient, app, create_session, db, init_db
from app.business_processes import ensure_business_process_schema
from app.schema import SCHEMA_STAGES


def image_bytes():
    out = BytesIO()
    Image.new('RGB', (80, 50), '#497baf').save(out, 'PNG')
    return out.getvalue()


def main():
    init_db()
    assert ('business_processes', 'ensure_business_process_schema') in SCHEMA_STAGES['runtime']
    # Borrowed migrations must not commit the caller's transaction.
    try:
        with db() as conn:
            ensure_business_process_schema(conn)
            raise RuntimeError('rollback')
    except RuntimeError:
        pass
    with db() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='business_processes'").fetchone() is None
        ensure_business_process_schema(conn)
        ensure_business_process_schema(conn)
    anonymous = TestClient(app)
    for path in ['/work/processes', '/work/processes/new', '/work/processes/images/1']:
        assert anonymous.get(path, follow_redirects=False).status_code == 303
    assert anonymous.post('/work/processes/new', data={'title':'forbidden'}, follow_redirects=False).status_code == 303
    client = TestClient(app)
    token, csrf, _ = create_session()
    client.cookies.set('session_token', token)
    assert client.post('/work/processes/new', data={'csrf':'wrong', 'title':'bad'}).status_code == 403
    assert client.post('/work/processes/new', data={'csrf':csrf, 'title':' '}).status_code == 400
    result = client.post('/work/processes/new', data={'csrf':csrf,'title':'集团成员办理','description':'准备资料\n核对号码'}, follow_redirects=False)
    assert result.status_code == 303, result.text
    url = result.headers['location']
    pid = int(url.rsplit('/', 1)[1])

    def revision():
        with db() as conn:
            return conn.execute('SELECT revision FROM business_processes WHERE id=?', (pid,)).fetchone()[0]

    def post(path, **values):
        return client.post(url+path, data={'csrf':csrf, 'revision':str(revision()), **values}, follow_redirects=False)

    payload = {'csrf':csrf,'revision':str(revision()),'title':'提交申请','description':'操作说明<script>alert(1)</script>'}
    assert client.post(url+'/steps/new', data=payload, files={'images':('proof.png',image_bytes(),'image/png')}, follow_redirects=False).status_code == 303
    with db() as conn:
        sid = conn.execute('SELECT id FROM business_process_steps WHERE process_id=?', (pid,)).fetchone()[0]
        photo_id = conn.execute('SELECT id FROM business_process_images WHERE step_id=?', (sid,)).fetchone()[0]
    detail = client.get(url)
    assert detail.status_code == 200 and '提交申请' in detail.text and '&lt;script&gt;' in detail.text
    assert '<script>alert(1)</script>' not in detail.text
    image = client.get(f'/work/processes/images/{photo_id}')
    assert image.status_code == 200 and image.headers['content-type'] == 'image/webp'
    assert 'no-store' in image.headers['cache-control'] and image.headers['x-content-type-options'] == 'nosniff'
    decoded = Image.open(BytesIO(image.content))
    assert decoded.size == (80, 50) and not decoded.getexif()
    assert client.get('/work/processes?q=操作说明').text.find('集团成员办理') >= 0
    assert '/work/processes' in client.get('/work').text
    assert post('/steps/new', title='等待审核', description='审核材料').status_code == 303
    with db() as conn:
        second = conn.execute('SELECT id FROM business_process_steps WHERE process_id=? ORDER BY id DESC', (pid,)).fetchone()[0]
    assert post(f'/steps/{second}/move', direction='up').status_code == 303
    with db() as conn:
        assert [r[0] for r in conn.execute('SELECT id FROM business_process_steps WHERE process_id=? ORDER BY sort_order,id', (pid,))] == [second, sid]
    old_revision = revision()
    assert post('/edit', title='办理流程新版', description='新版说明').status_code == 303
    stale = client.post(url+'/edit', data={'csrf':csrf,'revision':old_revision,'title':'过期编辑'}, follow_redirects=False)
    assert stale.status_code == 409 and '过期编辑' in stale.text and '其他页面更新' in stale.text
    assert '办理流程新版' in client.get(url).text
    before = revision()
    bad = client.post(url+f'/steps/{sid}/edit', data={'csrf':csrf,'revision':before,'title':'保留填写'}, files={'images':('bad.svg',b'<svg onload="alert(1)"/>','image/png')})
    assert bad.status_code == 400 and '保留填写' in bad.text and revision() == before
    too_big = client.post(url+'/steps/new', data={'csrf':csrf,'revision':before,'title':'oversize'}, files={'images':('large.png',b'x'*(8*1024*1024+1),'image/png')})
    assert too_big.status_code == 413 and revision() == before
    streamed = client.post(url+'/steps/new', headers={'Content-Type':'application/octet-stream'}, content=iter([b'x'*1024*1024]*33))
    assert streamed.status_code == 413
    wrong = post('/steps/new', title='不能越权删除', remove_images=str(photo_id))
    assert wrong.status_code == 400 and revision() == before
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM business_process_steps WHERE process_id=?', (pid,)).fetchone()[0] == 2
    other = client.post('/work/processes/new', data={'csrf':csrf,'title':'另一个流程'}, follow_redirects=False).headers['location']
    mismatch = client.get(other+f'/steps/{sid}/edit')
    assert mismatch.status_code == 404
    assert post(f'/steps/{sid}/edit', title='已修改步骤', description='新说明', remove_images=str(photo_id)).status_code == 303
    assert client.get(f'/work/processes/images/{photo_id}').status_code == 404
    assert post(f'/steps/{sid}/delete').status_code == 303
    # Deleting a flow cascades through both step and media tables.
    payload = {'csrf':csrf,'revision':revision(),'title':'最后步骤'}
    assert client.post(url+'/steps/new', data=payload, files={'images':('last.png',image_bytes(),'image/png')}).status_code == 200
    with db() as conn:
        ids = [row[0] for row in conn.execute('SELECT id FROM business_process_steps WHERE process_id=?', (pid,))]
        last_photo = conn.execute('SELECT id FROM business_process_images ORDER BY id DESC').fetchone()[0]
    assert post('/delete').status_code == 303
    assert client.get(url).status_code == 404 and client.get(f'/work/processes/images/{last_photo}').status_code == 404
    with db() as conn:
        assert not [r for r in conn.execute('SELECT id FROM business_process_steps') if r[0] in ids]
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    print('business processes passed: authenticated CRUD, ordered steps, private sanitized images, CSRF, bounded uploads, stale edits and cascade rollback')


if __name__ == '__main__':
    main()
