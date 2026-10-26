import json
from v162_number_inbox_contract import TestClient, app, create_session, db, init_db
from app.v162_number_inbox import ensure_number_inbox_schema
from app.work_architecture import DEFAULT_ENTRY_LAYOUT, LAYOUT_KEY, entry_layout


def main():
    init_db()
    with db() as conn:
        ensure_number_inbox_schema(conn)
    client = TestClient(app)
    assert client.post('/work/entry-layout', data={'csrf':'x','layout':'{}'}, follow_redirects=False).status_code == 303
    token, csrf, _ = create_session(); client.cookies.set('session_token',token)
    assert client.post('/work/entry-layout', data={'csrf':'wrong','layout':'{}'}).status_code == 403
    for invalid in ({}, {'common':['customers'],'auxiliary':[]}, {'common':[1],'auxiliary':[]},
                    {'common':DEFAULT_ENTRY_LAYOUT['common']*2,'auxiliary':DEFAULT_ENTRY_LAYOUT['auxiliary']}):
        assert client.post('/work/entry-layout',data={'csrf':csrf,'layout':json.dumps(invalid)}).status_code == 400
    layout = {'common':['numbers', 'lists', 'processes', 'todos'], 'auxiliary':['search','products','library','customers','all_customers','payment','promos']}
    result = client.post('/work/entry-layout', data={'csrf':csrf,'layout':json.dumps(layout)})
    assert result.json()['ok']
    fresh = TestClient(app);fresh.cookies.set('session_token',token)
    page = fresh.get('/work').text
    assert page.index('data-entry-key="numbers"') < page.index('data-entry-key="lists"') < page.index('data-entry-key="search"')
    assert '常用入口' in page and '辅助入口' in page
    assert page.index('reminder-entry') < page.index('data-history-nav') < page.index('global-primary-nav')
    with db() as conn:
        assert entry_layout(conn) == layout
    legacy = {'common':['numbers','lists'], 'auxiliary':['search','products','library','customers','all_customers']}
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)', (LAYOUT_KEY,json.dumps(legacy)))
        assert entry_layout(conn) == layout
    assert '/work/customers?home=payment' in page and '/work/customers?home=promos' in page
    assert '/work/processes' in page
    previous = {'common':['numbers','lists'], 'auxiliary':['search','products','library','customers','all_customers','payment','promos']}
    with db() as conn:
        conn.execute('UPDATE app_meta SET value=? WHERE key=?', (json.dumps(previous), LAYOUT_KEY))
        assert entry_layout(conn) == layout
    print('work entry authenticated layout persistence, exact-key validation, ordering and left header passed')


if __name__ == '__main__':main()
