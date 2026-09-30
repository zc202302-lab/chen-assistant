"""Bounded Excel reading only: no macros, links or formulas are executed."""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import xlrd

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RNS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLS = 50


def column_number(value):
    value = str(value).strip().upper()
    if not re.fullmatch('[A-Z]{1,3}', value):
        raise ValueError('列范围请填写 Excel 列字母，例如 D、G')
    result = 0
    for char in value:
        result = result * 26 + ord(char) - 64
    if result > 16384:
        raise ValueError('列范围超出 Excel 列数')
    return result


def column_name(number):
    result = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _numeric(value, fmt=''):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > Decimal('1e100'):
            raise InvalidOperation()
        text = format(number, 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        if re.fullmatch('0{1,30}', fmt) and number == number.to_integral_value() and number >= 0:
            return text.zfill(len(fmt))
        return text
    except InvalidOperation:
        raise ValueError('表格包含无效或过大的数字')


def _date_format(fmt):
    clean = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', '', fmt).lower()
    return bool(re.search('[yd]', clean) or ('h' in clean and 'm' in clean))


class ExcelTable:
    def __init__(self, content, filename):
        if not content or len(content) > MAX_BYTES:
            raise ValueError('文件不能为空，且不能超过5 MB')
        self.zip = None
        self.xls = None
        extension = filename.lower().rsplit('.', 1)[-1]
        if extension == 'xls':
            try:
                self.xls = xlrd.open_workbook(file_contents=content, formatting_info=True, on_demand=True, ragged_rows=True, logfile=io.StringIO())
                self.sheets = self.xls.sheet_names()
            except Exception:
                raise ValueError('无法读取 XLS 文件，请用 Excel 另存为 XLSX 后重试')
        elif extension in {'xlsx', 'xlsm'}:
            try:
                self.zip = zipfile.ZipFile(io.BytesIO(content))
                infos = self.zip.infolist()
                if len(infos) > 4000 or sum(i.file_size for i in infos) > 64 * 1024 * 1024:
                    raise ValueError('表格展开后过大，请拆分文件')
                if any(i.file_size > 32 * 1024 * 1024 for i in infos):
                    raise ValueError('表格中的单个文件过大，请拆分文件')
                workbook = self._xml('xl/workbook.xml')
                relationships = self._xml('xl/_rels/workbook.xml.rels')
                targets = {r.attrib['Id']: r.attrib['Target'] for r in relationships if r.attrib.get('TargetMode') != 'External'}
                self.paths = {}
                for sheet in workbook.findall(f'{{{NS}}}sheets/{{{NS}}}sheet'):
                    target = targets.get(sheet.attrib.get(f'{{{RNS}}}id'), '')
                    path = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
                    if not path.startswith('xl/worksheets/') or path not in self.zip.namelist():
                        continue
                    self.paths[sheet.attrib['name']] = path
                self.sheets = list(self.paths)
                properties = workbook.find(f'{{{NS}}}workbookPr')
                self.date1904 = properties is not None and properties.attrib.get('date1904') in {'1', 'true'}
            except (zipfile.BadZipFile, KeyError, ET.ParseError):
                raise ValueError('无法读取 Excel 文件，请确认文件格式且未加密')
        else:
            raise ValueError('支持 .xlsx、.xlsm 和 .xls 文件')
        if not self.sheets or len(self.sheets) > 500:
            raise ValueError('文件没有可用工作表或工作表数量超过500')

    def close(self):
        if self.zip:
            self.zip.close()
        if self.xls:
            self.xls.release_resources()

    def _xml(self, path):
        content = self.zip.read(path)
        if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
            raise ValueError('文件包含不支持的 XML 定义')
        return ET.fromstring(content)

    def read(self, sheet_name, header=1, first='A', last='', end=0):
        try:
            return self._read(sheet_name, header, first, last, end)
        except (KeyError, IndexError, ET.ParseError, zipfile.BadZipFile, OverflowError, xlrd.XLRDError):
            raise ValueError('工作表数据损坏或格式不支持，请在 Excel 中另存后重试')

    def _read(self, sheet_name, header=1, first='A', last='', end=0):
        if sheet_name not in self.sheets:
            raise ValueError('工作表不存在')
        if not 1 <= header <= 1000 or end and end <= header:
            raise ValueError('表头行须为1至1000，结束行须大于表头行')
        first_col = column_number(first)
        last_col = column_number(last) if last.strip() else 0
        if last_col and (last_col < first_col or last_col - first_col + 1 > MAX_COLS):
            raise ValueError('列范围无效，一次最多导入50列')
        selected = {}
        missing = []
        if self.xls:
            sheet = self.xls.sheet_by_name(sheet_name)
            for row in range(header - 1, min(sheet.nrows, end or sheet.nrows)):
                values = {}
                for col in range(first_col - 1, min(sheet.row_len(row), last_col or sheet.row_len(row))):
                    cell = sheet.cell(row, col)
                    if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                        continue
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        dt = xlrd.xldate_as_datetime(cell.value, self.xls.datemode)
                        value = dt.date().isoformat() if dt.time() == datetime.min.time() else dt.isoformat(timespec='seconds')
                    elif cell.ctype == xlrd.XL_CELL_NUMBER:
                        xf = self.xls.xf_list[cell.xf_index]
                        fmt = self.xls.format_map.get(xf.format_key)
                        value = _numeric(cell.value, fmt.format_str if fmt else '')
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        value = '是' if cell.value else '否'
                    elif cell.ctype == xlrd.XL_CELL_ERROR:
                        value = xlrd.error_text_from_code.get(cell.value, '#ERROR!')
                    else:
                        value = str(cell.value)
                    if value.strip():
                        values[col + 1] = value
                if values or row == header - 1:
                    selected[row + 1] = values
                    if len(selected) > MAX_ROWS + 1:
                        raise ValueError('数据超过5000行，请指定结束行或拆分导入')
        else:
            shared = []
            if 'xl/sharedStrings.xml' in self.zip.namelist():
                shared = [''.join(t.text or '' for t in node.iter(f'{{{NS}}}t')) for node in self._xml('xl/sharedStrings.xml').findall(f'{{{NS}}}si')]
            formats = {}
            styles = []
            if 'xl/styles.xml' in self.zip.namelist():
                style_root = self._xml('xl/styles.xml')
                formats = {int(n.attrib['numFmtId']): n.attrib['formatCode'] for n in style_root.findall(f'{{{NS}}}numFmts/{{{NS}}}numFmt')}
                styles = [int(n.attrib.get('numFmtId', 0)) for n in style_root.findall(f'{{{NS}}}cellXfs/{{{NS}}}xf')]
            root = self._xml(self.paths[sheet_name])
            for row in root.findall(f'{{{NS}}}sheetData/{{{NS}}}row'):
                row_number = int(row.attrib['r'])
                if row_number < header or end and row_number > end:
                    continue
                values = {}
                for cell in row.findall(f'{{{NS}}}c'):
                    ref = cell.attrib.get('r', '')
                    match = re.fullmatch(r'([A-Z]+)\d+', ref)
                    if not match:
                        raise ValueError('单元格坐标无效')
                    col = column_number(match.group(1))
                    if col < first_col or last_col and col > last_col:
                        continue
                    kind = cell.attrib.get('t', '')
                    node = cell.find(f'{{{NS}}}v')
                    value = node.text or '' if node is not None else ''
                    if cell.find(f'{{{NS}}}f') is not None and node is None:
                        missing.append(ref)
                    if kind == 's':
                        try:
                            value = shared[int(value)]
                        except (ValueError, IndexError):
                            raise ValueError(f'{ref}文本索引无效')
                    elif kind == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.iter(f'{{{NS}}}t'))
                    elif kind == 'b':
                        value = '是' if value == '1' else '否'
                    elif kind in {'', 'n'} and value:
                        style = int(cell.attrib.get('s', 0))
                        fmt_id = styles[style] if style < len(styles) else 0
                        fmt = formats.get(fmt_id, '')
                        if fmt_id in set(range(14, 23)) | {45, 46, 47} or _date_format(fmt):
                            dt = datetime(1904, 1, 1) if self.date1904 else datetime(1899, 12, 30)
                            try:
                                dt += timedelta(days=float(value))
                            except (ValueError, OverflowError):
                                raise ValueError(f'{ref}日期无效')
                            value = dt.date().isoformat() if dt.time() == datetime.min.time() else dt.isoformat(timespec='seconds')
                        else:
                            value = _numeric(value, fmt)
                    if len(value) > 20000:
                        raise ValueError(f'{ref}内容超过20000个字符')
                    if value.strip():
                        values[col] = value
                if values or row_number == header:
                    selected[row_number] = values
                    if len(selected) > MAX_ROWS + 1:
                        raise ValueError('数据超过5000行，请指定结束行或拆分导入')
            if missing:
                raise ValueError('以下公式没有已保存的结果，请先在 Excel 中计算并保存：' + '、'.join(missing[:10]))
        last_col = last_col or max((max(v, default=0) for v in selected.values()), default=0)
        if last_col < first_col or last_col - first_col + 1 > MAX_COLS:
            raise ValueError('没有有效列或超过50列，请指定开始列和结束列')
        headings = selected.get(header, {})
        columns, used = [], set()
        for col in range(first_col, last_col + 1):
            label = headings.get(col, '').strip() or f'列{column_name(col)}'
            label = label[:70]
            if label in used:
                label += f'（{column_name(col)}）'
            used.add(label)
            columns.append({'key': str(col), 'letter': column_name(col), 'label': label})
        rows = [{'row': number, 'cells': [values.get(col, '') for col in range(first_col, last_col + 1)]}
                for number, values in sorted(selected.items()) if number > header and any(values.values())]
        if not rows:
            raise ValueError('所选范围没有数据行，请检查工作表、表头及列范围')
        return {'columns': columns, 'rows': rows}
