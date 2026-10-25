"""Manual recipes must remain visible alongside all imported standards."""
from v162_number_inbox_contract import TestClient, app, create_session, db, init_db
from app.recipe_library import recipe_count, recipe_rows, recipe_categories
from app.v101_recipe_template_patch import ensure_v101_recipe_templates
from app.v101_recipe_template_data import TEMPLATE_IMPORT_MARKER


def main():
    init_db()
    ensure_v101_recipe_templates()
    with db() as conn:
        original = [tuple(r) for r in conn.execute('SELECT * FROM recipes ORDER BY id')]
        original_versions = [tuple(r) for r in conn.execute('SELECT * FROM recipe_versions ORDER BY id')]
        assert recipe_count(conn) == 18
    guest = TestClient(app)
    assert guest.get('/life/recipes/new', follow_redirects=False).status_code == 303
    token, csrf, _ = create_session()
    client = TestClient(app)
    client.cookies.set('session_token', token)
    import re
    with db() as conn:
        seed_id = conn.execute("SELECT id FROM recipes WHERE name='糖醋排骨'").fetchone()['id']
    legacy_editor = client.get(f'/life/recipes/{seed_id}/edit').text
    raw_section = re.search(r'<section class="v10-form-card recipe-raw-section".*?</section>', legacy_editor, re.S)[0]
    assert '排骨' in raw_section and 'data-raw-material-list' in raw_section
    assert 'data-recipe-group' not in raw_section and 'data-group-name' not in raw_section
    assert '物料' not in legacy_editor
    assert 'data-recipe-raw-info' in client.get(f'/life/recipes/{seed_id}').text
    with db() as conn:
        legacy_multi = conn.execute("SELECT id FROM recipes WHERE name='尖椒干豆腐'").fetchone()['id']
    legacy_detail = client.get(f'/life/recipes/{legacy_multi}').text
    assert 'data-base-amount="450.0"' in legacy_detail
    assert 'aria-label="豆腐皮重量" value="250"' in legacy_detail
    legacy_print = client.get(f'/life/recipes/{legacy_multi}/print').text
    assert 'amount=450.0' in legacy_print
    for path in ['/life', '/life/recipes']:
        assert 'href="/life/recipes/new"' in client.get(path).text
    assert client.post('/life/recipes/new', data={'name':'not allowed','csrf':'wrong'}).status_code == 403
    for value in ['0','-1','nan','inf']:
        assert client.post('/life/recipes/new', data={'csrf':csrf,'name':'invalid-weight','base_amount':value}).status_code == 400
    assert client.post('/life/recipes/new', data={'csrf':csrf,'name':' '}).status_code == 400
    fields = {'csrf':csrf,'name':'手写鱼锅泡饼','category':'我的鱼类','tags':'个人手写','description':'准备事项<script>unsafe</script>',
              'base_amount':'1000','base_unit':'g'}
    result = client.post('/life/recipes/new', data=fields, follow_redirects=False)
    assert result.status_code == 303, result.text
    edit_url = result.headers['location']
    rid = int(edit_url.split('/')[-2])
    with db() as conn:
        record = conn.execute('SELECT * FROM recipes WHERE id=?', (rid,)).fetchone()
        assert record['source'] == 'manual'
        assert recipe_count(conn) == 19 and '我的鱼类' in recipe_categories(conn)
        assert len(recipe_rows(conn, q='个人手写')) == 1
        assert len(recipe_rows(conn, q='准备事项', category='我的鱼类')) == 1
        assert recipe_rows(conn, category='no match') == []
        assert any(r['id'] == rid for r in recipe_rows(conn, recent=True))
    assert '手写鱼锅泡饼' in client.get('/life').text
    listing = client.get('/life/recipes')
    assert '手写鱼锅泡饼' in listing.text and '手动创建' in listing.text
    assert '手写鱼锅泡饼' in client.get('/life/recipes?q=个人手写').text
    assert client.post('/life/recipes/new', data=fields).status_code == 409
    assert client.get(edit_url).status_code == 200
    edited = {**fields, 'change_summary':'首次填写配方',
              'ingredient_group':['腌肉','碗汁','腌肉'], 'ingredient_name':['鲜鱼','盐','白胡椒粉'], 'ingredient_amount':['1000','6','0.3'],
              'ingredient_unit':['g','g','g'],'ingredient_mode':['proportional','fixed','manual'],'ingredient_note':['准备干净','按需调整','少许'],
              'step_title':['准备','制作'], 'step_action':['准备原料\n核对用量','按自己的做法完成'],
              'step_principle':['记录原理','记录完成状态']}
    assert client.post(edit_url, data=edited, follow_redirects=False).status_code == 303
    import re
    editor = client.get(edit_url).text.split('<template id="recipeGroupTemplate">')[0]
    cards = re.findall(r'<article class="recipe-group" data-recipe-group>(.*?)</article>', editor, re.S)
    assert [re.search(r'data-group-name[^>]*value="([^"]*)"', card)[1] for card in cards] == ['腌肉','碗汁']
    assert re.findall(r'name="ingredient_name" value="([^"]*)"', cards[0]) == ['鲜鱼','白胡椒粉']
    assert cards[0].count('name="ingredient_group"') == 2
    assert 'name="ingredient_note" value="少许"' in cards[0]
    assert 'value="manual" selected' in cards[0]
    detail = client.get(f'/life/recipes/{rid}')
    assert detail.status_code == 200 and '准备原料' in detail.text and '记录原理' in detail.text
    assert '<script>unsafe</script>' not in detail.text and '&lt;script&gt;' in detail.text
    printed = client.get(f'/life/recipes/{rid}/print')
    assert printed.status_code == 200
    assert '准备原料' in printed.text
    import re
    print_rows = re.findall(r'<tr class="excel-ingredient-row">(.*?)</tr>', printed.text, re.S)
    assert print_rows and '<th scope="row">原料</th>' in print_rows[0]
    assert '<th scope="row" rowspan="2">腌肉</th>' in print_rows[1]
    assert '鲜鱼' in print_rows[1] and '白胡椒粉' in print_rows[1]
    assert '<th>备注</th>' not in printed.text
    assert '<th rowspan="2">原理</th>' not in printed.text
    assert '<th colspan="9" rowspan="2">方法</th>' in printed.text
    assert 'class="excel-step-method" colspan="9"' in printed.text
    assert guest.get(f'/life/recipes/{rid}/print?format=pdf', follow_redirects=False).status_code == 303
    pdf = client.get(f'/life/recipes/{rid}/print?format=pdf')
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF-')
    assert pdf.headers['content-type'] == 'application/pdf'
    assert pdf.headers['cache-control'] == 'no-store'
    assert "filename*=UTF-8''" in pdf.headers['content-disposition']
    assert len(re.findall(rb'/Type\s*/Page(?!s)\b', pdf.content)) == 1
    assert client.get('/life/recipes/999999/print?format=pdf').status_code == 404
    scaled_print = client.get(f'/life/recipes/{rid}/print?amount=2000')
    assert scaled_print.status_code == 200 and '2000g' in scaled_print.text and '6g' in scaled_print.text
    assert '0.3g' in scaled_print.text, 'manual quantities must not scale'
    assert 'format=pdf&amp;amount=2000.0' in scaled_print.text
    from unittest.mock import patch
    from app.recipe_print_pdf import recipe_pdf
    with patch('app.recipe_print_pdf.recipe_pdf', wraps=recipe_pdf) as export:
        actual_pdf = client.get(f'/life/recipes/{rid}/print?format=pdf&amount=2000')
        assert actual_pdf.status_code == 200 and actual_pdf.content.startswith(b'%PDF-')
        items = export.call_args.args[1]['ingredient_groups']
        assert items[0]['items'][0]['amount'] == '2000g'
        assert items[0]['items'][1]['amount'] == '0.3g'
        assert items[1]['items'][0]['amount'] == '6g'
    for invalid in ['nan','inf','-1','0','abc','']:
        for output in ['', '&format=pdf']:
            assert client.get(f'/life/recipes/{rid}/print?amount={invalid}{output}').status_code == 400

    # Explicit raw materials define the denominator; spices do not. Units normalize to grams.
    from app.recipe_raw_materials import raw_material_total
    from starlette.datastructures import FormData
    raw_form = FormData([('ingredient_name','面粉'),('ingredient_name','玉米粉'),('ingredient_name','盐'),
                        ('ingredient_group','原料'),('ingredient_group','原料'),('ingredient_group','调味'),
                        ('ingredient_amount','1'),('ingredient_amount','500'),('ingredient_amount','12'),
                        ('ingredient_unit','kg'),('ingredient_unit','g'),('ingredient_unit','g')])
    assert raw_material_total(raw_form, 99) == (1500, 'g')
    for invalid in ['nan','inf','-1','0','']:
        bad = FormData([('ingredient_name','面粉'),('ingredient_group','原料'),('ingredient_amount',invalid)])
        try:
            raw_material_total(bad, 99)
        except Exception as error:
            assert error.status_code == 400
        else:
            raise AssertionError('invalid raw weight accepted')
    assert client.get(f'/life/recipes/{rid}/versions', follow_redirects=False).status_code == 303
    assert '历史版本' not in detail.text and '当前标准 V' not in detail.text
    assert 'change_summary' not in client.get(edit_url).text
    assert client.post(f'/life/recipes/{rid}/versions/1/restore', data={'csrf':csrf}).status_code == 410
    with db() as conn:
        versions = conn.execute('SELECT * FROM recipe_versions WHERE recipe_id=? ORDER BY version_no', (rid,)).fetchall()
        assert [v['version_no'] for v in versions] == [1, 2]
        assert not any(v['change_summary'].startswith(TEMPLATE_IMPORT_MARKER) for v in versions)
        assert [tuple(r) for r in conn.execute('SELECT * FROM recipes WHERE id<>? ORDER BY id', (rid,))] == original
        assert [tuple(r) for r in conn.execute('SELECT * FROM recipe_versions WHERE recipe_id<>? ORDER BY id', (rid,))] == original_versions
    # Per-raw overrides must retain individual quantities and derive the denominator server-side.
    with db() as conn:
        conn.execute("UPDATE recipe_ingredients SET group_name='原料',unit='kg',amount=1 WHERE version_id=? AND name='鲜鱼'", (versions[-1]['id'],))
        conn.execute("UPDATE recipe_ingredients SET group_name='原料',unit='g',amount=500 WHERE version_id=? AND name='白胡椒粉'", (versions[-1]['id'],))
        raw_rows = conn.execute("SELECT id FROM recipe_ingredients WHERE version_id=? AND group_name='原料' ORDER BY sort_order,id", (versions[-1]['id'],)).fetchall()
        conn.execute("UPDATE recipe_versions SET base_amount=1500 WHERE id=?", (versions[-1]['id'],))
    first, second = [str(row['id']) for row in raw_rows]
    query = f'raw={first}:2.2&raw={second}:800&amount=1'
    response = client.get(f'/life/recipes/{rid}/print?{query}')
    assert response.status_code == 200 and '2.2kg' in response.text and '800g' in response.text
    assert 'amount=3000.0' in response.text, 'backend must derive total, ignoring supplied aggregate'
    assert f'raw={first}%3A2.2' in response.text and f'raw={second}%3A800' in response.text
    with patch('app.recipe_print_pdf.recipe_pdf', wraps=recipe_pdf) as export:
        assert client.get(f'/life/recipes/{rid}/print?format=pdf&{query}').status_code == 200
        assert export.call_args.args[1]['main_slots'][:4] == ['鲜鱼','2.2kg','白胡椒粉','800g']
    weights_url = f'/life/recipes/{rid}/weights'
    save = {'csrf':csrf, 'version_id':versions[-1]['id'], 'revision':'1000', 'raw':[f'{first}:2.2', f'{second}:800']}
    assert guest.post(weights_url, data=save, follow_redirects=False).status_code == 303
    assert client.post(weights_url, data={**save,'csrf':'wrong'}).status_code == 403
    assert client.post(weights_url, data={**save,'version_id':'-1'}).status_code == 409
    assert client.post(weights_url, data={**save,'raw':[f'{first}:0',f'{second}:800']}).status_code == 400
    saved = client.post(weights_url, data=save)
    assert saved.status_code == 200 and saved.json()['amount'] == 3000
    # Slower old requests cannot replace newer saved weights.
    assert client.post(weights_url, data={**save,'revision':'999','raw':[f'{first}:1',f'{second}:500']}).status_code == 200
    reopened = client.get(f'/life/recipes/{rid}').text
    assert 'v10TargetAmount' not in reopened
    assert re.search(r'aria-label="鲜鱼重量" value="2.2"', reopened)
    assert re.search(r'aria-label="白胡椒粉重量" value="800.0"', reopened)
    remembered_print = client.get(f'/life/recipes/{rid}/print').text
    assert '2.2kg' in remembered_print and '800g' in remembered_print
    assert 'amount=3000.0' in remembered_print
    with db() as conn:
        assert conn.execute('SELECT base_amount FROM recipe_versions WHERE id=?', (versions[-1]['id'],)).fetchone()[0] == 1500
        assert conn.execute('SELECT amount FROM recipe_ingredients WHERE id=?', (int(first),)).fetchone()[0] == 1
    for query in [f'raw={first}:1', f'raw={first}:1&raw={first}:2', f'raw=999999:1', f'raw={first}:nan&raw={second}:1', f'raw={first}:0&raw={second}:1']:
        for suffix in ['', '&format=pdf']:
            assert client.get(f'/life/recipes/{rid}/print?{query}{suffix}').status_code == 400
    with db() as conn:
        conn.execute('UPDATE recipes SET archived=1 WHERE id=?', (rid,))
        assert recipe_count(conn) == 18
        assert not recipe_rows(conn, q='手写鱼锅泡饼')
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    print('manual recipe creation passed: authenticated creation, validation, persistent visibility/search/category/recent, recipe editing, versions, print, escaping and unchanged imported recipes')


if __name__ == '__main__':
    main()
