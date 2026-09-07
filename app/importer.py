from __future__ import annotations
import re, zipfile, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from .db import db, init_db, now_iso

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RNS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def excel_date(value: str) -> str:
    if not value:
        return ''
    try:
        x = float(value)
    except Exception:
        return value.strip()
    if x < 1000:
        return value.strip()
    d = datetime(1899, 12, 30) + timedelta(days=x)
    return d.date().isoformat()


def number(value: str) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def flag(value: str) -> int:
    s = str(value).strip().lower()
    return 1 if s in {'1','true','yes','是'} else 0


def col_num(col: str) -> int:
    n = 0
    for c in col:
        n = n * 26 + ord(c) - 64
    return n


def col_name(n: int) -> str:
    out = ''
    while n:
        n, r = divmod(n-1, 26)
        out = chr(65+r) + out
    return out


class XlsmReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.z = zipfile.ZipFile(self.path)
        self.ss = []
        if 'xl/sharedStrings.xml' in self.z.namelist():
            root = ET.fromstring(self.z.read('xl/sharedStrings.xml'))
            for si in root.findall(f'{{{NS}}}si'):
                self.ss.append(''.join(t.text or '' for t in si.iter(f'{{{NS}}}t')))
        wb = ET.fromstring(self.z.read('xl/workbook.xml'))
        rel = ET.fromstring(self.z.read('xl/_rels/workbook.xml.rels'))
        relmap = {x.attrib['Id']: x.attrib['Target'] for x in rel}
        self.sheets = []
        for s in wb.find(f'{{{NS}}}sheets'):
            rid = s.attrib[f'{{{RNS}}}id']
            self.sheets.append((s.attrib['name'], 'xl/' + relmap[rid]))

    def cells(self, path: str):
        root = ET.fromstring(self.z.read(path))
        out = {}
        for c in root.iter(f'{{{NS}}}c'):
            ref = c.attrib.get('r', '')
            t = c.attrib.get('t')
            v = c.find(f'{{{NS}}}v')
            val = '' if v is None else (v.text or '')
            if t == 's' and val:
                try: val = self.ss[int(val)]
                except Exception: pass
            elif t == 'inlineStr':
                el = c.find(f'{{{NS}}}is')
                val = '' if el is None else ''.join(x.text or '' for x in el.iter(f'{{{NS}}}t'))
            out[ref] = val.strip() if isinstance(val, str) else val
        return out


def import_xlsm(path: str | Path, replace: bool = True):
    init_db()
    r = XlsmReader(path)
    now = now_iso()
    current_period = datetime.now().strftime('%Y-%m')
    stats = {'customers':0,'services':0,'promotions':0,'contacts':0,'tasks':0,'visits':0,'entities':0}
    with db() as conn:
        if replace:
            for table in ['promotions','services','contacts','tasks','visits','customer_entities','customers']:
                conn.execute(f'DELETE FROM {table}')
        for idx, (sheet_name, sheet_path) in enumerate(r.sheets):
            if idx < 6:
                continue
            c = r.cells(sheet_path)
            name = c.get('A3','').strip()
            if not name:
                continue
            group_code = c.get('B3','').strip()
            tax_id = c.get('C3','').strip()
            # 客情：保留难以结构化的自然语言记录
            relation_summary_parts = []
            contact_rows = []
            for row in range(12,16):
                kind = c.get(f'A{row}','').strip()
                nm = c.get(f'B{row}','').strip()
                rel = c.get(f'C{row}','').strip()
                if not nm and not rel:
                    continue
                if len(nm) > 15 and not rel:
                    relation_summary_parts.append(nm)
                else:
                    contact_rows.append((kind,nm,rel))
            cur = conn.execute('''INSERT INTO customers
                (source_sheet,name,group_code,tax_id,relation_summary,payment_enabled,notified,completed,payment_period,
                 employee_own,employee_share,leased_own,leased_other,other_status,created_at,updated_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                sheet_name,name,group_code,tax_id,'\n'.join(relation_summary_parts),
                flag(c.get('A5','0')), flag(c.get('B5','0')), flag(c.get('C5','0')), current_period,
                c.get('B18',''), c.get('C18',''), c.get('B20',''), c.get('C20',''), c.get('A22',''), now, now
            ))
            customer_id = cur.lastrowid
            stats['customers'] += 1
            # 关联主体：Excel 中第二组 A6:C7 等
            for label_row, data_row in [(6,7),(8,9)]:
                extra_name = c.get(f'A{data_row}','').strip()
                if extra_name and extra_name != name:
                    conn.execute('INSERT INTO customer_entities(customer_id,name,group_code,tax_id) VALUES(?,?,?,?)',
                                 (customer_id,extra_name,c.get(f'B{data_row}','').strip(),c.get(f'C{data_row}','').strip()))
                    stats['entities'] += 1
            for kind,nm,rel in contact_rows:
                conn.execute('INSERT INTO contacts(customer_id,kind,name,relationship) VALUES(?,?,?,?)',(customer_id,kind,nm,rel))
                stats['contacts'] += 1
            # 待办 26:30
            for row in range(26,31):
                title = c.get(f'A{row}','').strip()
                if not title: continue
                conn.execute('INSERT INTO tasks(customer_id,title,remind_date,note,created_at) VALUES(?,?,?,?,?)',
                             (customer_id,title,excel_date(c.get(f'B{row}','')),c.get(f'C{row}','').strip(),now))
                stats['tasks'] += 1
            # 拜访 33:37
            for row in range(33,38):
                date = c.get(f'A{row}','').strip(); result = c.get(f'B{row}','').strip(); plan = c.get(f'C{row}','').strip()
                if not any([date,result,plan]): continue
                conn.execute('INSERT INTO visits(customer_id,visit_date,result,plan,created_at) VALUES(?,?,?,?,?)',
                             (customer_id,excel_date(date),result,plan,now))
                stats['visits'] += 1
            # 业务：E 列不空即业务行，排除表头
            service_rows = []
            for ref,val in c.items():
                m = re.fullmatch(r'E(\d+)',ref)
                if m and val and val not in {'类型'}:
                    row = int(m.group(1))
                    if row >= 2:
                        service_rows.append(row)
            for row in sorted(set(service_rows)):
                stype = c.get(f'E{row}','').strip()
                if not stype: continue
                service = {
                    'service_type': stype,
                    'holder_name': c.get(f'F{row}','').strip(),
                    'number': c.get(f'G{row}','').strip(),
                    'account': c.get(f'H{row}','').strip(),
                    'monthly_fee': number(c.get(f'I{row}','')),
                    'fixed_fee': flag(c.get(f'J{row}','0')),
                    'payment_cycle': c.get(f'K{row}','').strip(),
                    'payment_method': c.get(f'L{row}','').strip(),
                    'invoice_type': c.get(f'M{row}','').strip(),
                    'package_type': c.get(f'N{row}','').strip(),
                    'last_payment_date': '',
                }
                promo_pairs = []
                for col in range(15,52,2):  # O/P ... AY/AZ
                    pcol, dcol = col_name(col), col_name(col+1)
                    pname = c.get(f'{pcol}{row}','').strip()
                    pdate = c.get(f'{dcol}{row}','').strip()
                    if not pname and not pdate: continue
                    if pname == '上次缴费':
                        service['last_payment_date'] = excel_date(pdate)
                    else:
                        promo_pairs.append((pname or '未命名优惠', excel_date(pdate)))
                scur = conn.execute('''INSERT INTO services
                    (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,payment_method,invoice_type,package_type,last_payment_date,source_row)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                    customer_id,service['service_type'],service['holder_name'],service['number'],service['account'],service['monthly_fee'],service['fixed_fee'],
                    service['payment_cycle'],service['payment_method'],service['invoice_type'],service['package_type'],service['last_payment_date'],row
                ))
                sid = scur.lastrowid; stats['services'] += 1
                # Excel I列是当前/最近一次实际缴费金额；导入时保存到当月缴费记录，后续月份非定额业务重新查询。
                if service['monthly_fee']:
                    conn.execute('''INSERT OR REPLACE INTO payment_entries(service_id,period,amount,source,created_at,updated_at)
                                    VALUES(?,?,?,?,?,?)''',(sid,current_period,service['monthly_fee'],'imported',now,now))
                for pname,pdate in promo_pairs:
                    conn.execute('INSERT INTO promotions(service_id,name,expiry_date) VALUES(?,?,?)',(sid,pname,pdate))
                    stats['promotions'] += 1
    return stats
