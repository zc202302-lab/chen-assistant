"""Bounded Excel appearance extraction, without executing formulas or macros."""
import colorsys
import re
from .work_list_excel import NS, column_number

BORDER = {'thin':1,'medium':2,'dashed':3,'dotted':4,'thick':5,'double':6,'hair':7,'mediumDashed':8,'dashDot':9,'mediumDashDot':10,'dashDotDot':11,'mediumDashDotDot':12,'slantDashDot':13}
BUILTIN = {1:'0',2:'0.00',3:'#,##0',4:'#,##0.00',9:'0%',10:'0.00%',14:'yyyy-mm-dd',20:'h:mm',21:'h:mm:ss',22:'yyyy-mm-dd h:mm',49:'@'}
INDEXED = ['000000','FFFFFF','FF0000','00FF00','0000FF','FFFF00','FF00FF','00FFFF'] * 2 + ['800000','008000','000080','808000','800080','008080','C0C0C0','808080']
THEME = ['FFFFFF','000000','E7E6E6','44546A','4472C4','ED7D31','A5A5A5','FFC000','5B9BD5','70AD47','0563C1','954F72']


def bounded(value, default, minimum=12, maximum=800):
    try:
        return round(max(minimum, min(maximum, float(value))), 2)
    except (ValueError, TypeError, OverflowError):
        return default


def theme_colors(reader):
    theme = list(THEME)
    if 'xl/theme/theme1.xml' in reader.zip.namelist():
        ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
        scheme = reader._xml('xl/theme/theme1.xml').find(f'{{{ns}}}themeElements/{{{ns}}}clrScheme')
        if scheme is not None:
            for i, key in enumerate(['lt1','dk1','lt2','dk2','accent1','accent2','accent3','accent4','accent5','accent6','hlink','folHlink']):
                entry = scheme.find(f'{{{ns}}}{key}')
                if entry is not None and len(entry):
                    theme[i] = entry[0].attrib.get('lastClr', entry[0].attrib.get('val', theme[i]))
    return theme


def color(node, theme):
    if node is None:
        return None
    raw = node.attrib.get('rgb', '')[-6:]
    if 'theme' in node.attrib:
        index = int(node.attrib['theme'])
        raw = theme[index] if 0 <= index < len(theme) else ''
    elif 'indexed' in node.attrib:
        index = int(node.attrib['indexed'])
        raw = INDEXED[index] if 0 <= index < len(INDEXED) else ''
    if not re.fullmatch('[0-9A-Fa-f]{6}', raw):
        return None
    tint = float(node.attrib.get('tint', 0))
    if tint:
        rgb = [int(raw[i:i+2], 16) / 255 for i in (0,2,4)]
        hue, light, saturation = colorsys.rgb_to_hls(*rgb)
        light = light * (1 + tint) if tint < 0 else light * (1 - tint) + tint
        raw = ''.join(f'{max(0,min(255,round(c*255))):02X}' for c in colorsys.hls_to_rgb(hue,max(0,min(1,light)),saturation))
    return '#' + raw.upper()


def xlsx_styles(reader):
    if 'xl/styles.xml' not in reader.zip.namelist():
        return [{}]
    root = reader._xml('xl/styles.xml')
    theme = theme_colors(reader)
    fonts = root.findall(f'{{{NS}}}fonts/{{{NS}}}font')
    fills = root.findall(f'{{{NS}}}fills/{{{NS}}}fill')
    borders = root.findall(f'{{{NS}}}borders/{{{NS}}}border')
    formats = BUILTIN | {int(n.attrib['numFmtId']):n.attrib['formatCode'][:160] for n in root.findall(f'{{{NS}}}numFmts/{{{NS}}}numFmt')}
    result = []
    for xf in root.findall(f'{{{NS}}}cellXfs/{{{NS}}}xf'):
        style = {}
        index = int(xf.attrib.get('fontId',0))
        if index < len(fonts):
            font = fonts[index]
            for name,key in [('b','bold'),('i','italic')]:
                node = font.find(f'{{{NS}}}{name}')
                if node is not None:
                    style[key] = node.attrib.get('val','1') not in {'0','false'}
            name,size = font.find(f'{{{NS}}}name'),font.find(f'{{{NS}}}sz')
            if name is not None:
                style['font'] = name.attrib.get('val','Arial')[:80]
            if size is not None:
                style['size'] = bounded(size.attrib.get('val'),11,6,72)
            fg = color(font.find(f'{{{NS}}}color'),theme)
            if fg:
                style['color'] = fg
            underline = font.find(f'{{{NS}}}u')
            if underline is not None:
                style['underline'] = 2 if underline.attrib.get('val') == 'double' else 1
        index = int(xf.attrib.get('fillId',0))
        if index < len(fills):
            pattern = fills[index].find(f'{{{NS}}}patternFill')
            if pattern is not None and pattern.attrib.get('patternType') == 'solid':
                bg = color(pattern.find(f'{{{NS}}}fgColor'),theme)
                if bg:
                    style['background'] = bg
        index = int(xf.attrib.get('borderId',0))
        if index < len(borders):
            for edge in ('left','right','top','bottom'):
                node = borders[index].find(f'{{{NS}}}{edge}')
                if node is not None and node.attrib.get('style') in BORDER:
                    border = {'style':BORDER[node.attrib['style']]}
                    fg = color(node.find(f'{{{NS}}}color'),theme)
                    if fg:
                        border['color'] = fg
                    style['border_'+edge] = border
        alignment = xf.find(f'{{{NS}}}alignment')
        if alignment is not None:
            if alignment.attrib.get('horizontal') in {'left','center','right'}:
                style['align'] = alignment.attrib['horizontal']
            if alignment.attrib.get('vertical') in {'top','center','bottom'}:
                style['valign'] = alignment.attrib['vertical']
            style['wrap'] = alignment.attrib.get('wrapText') in {'1','true'}
        fmt = formats.get(int(xf.attrib.get('numFmtId',0)))
        if fmt and fmt != 'General':
            style['number_format'] = fmt
        result.append(style)
    return result or [{}]


def read_layout(reader, sheet_name, header, first_col, last_col, row_numbers):
    allowed_rows = set(row_numbers) | {header}
    layout = {'header':header,'widths':{},'heights':{},'cells':{},'merges':[]}
    if reader.xls:
        sheet = reader.xls.sheet_by_name(sheet_name)
        def palette(index):
            rgb = reader.xls.colour_map.get(index)
            return '#' + ''.join(f'{n:02X}' for n in rgb) if rgb else None
        for col in range(first_col,last_col+1):
            info = sheet.colinfo_map.get(col-1)
            if info:
                layout['widths'][str(col)] = bounded(info.width/256*7+5,150)
        for row in allowed_rows:
            info = sheet.rowinfo_map.get(row-1)
            if info and info.height:
                layout['heights'][str(row)] = bounded(info.height/20*4/3,32,12,500)
            for col in range(first_col,min(last_col,sheet.row_len(row-1) if row <= sheet.nrows else 0)+1):
                cell = sheet.cell(row-1,col-1)
                xf = reader.xls.xf_list[cell.xf_index]
                # Old BIFF workbooks may omit FONT records and rely on defaults.
                font = reader.xls.font_list[xf.font_index] if xf.font_index < len(reader.xls.font_list) else None
                style = {'numeric': cell.ctype == 2, 'font':font.name[:80] if font else 'Arial',
                         'size':bounded(font.height/20,11,6,72) if font else 11,
                         'bold':bool(font.bold) if font else False, 'italic':bool(font.italic) if font else False,
                         'wrap':bool(xf.alignment.text_wrapped)}
                fg,bg = palette(font.colour_index) if font else None,palette(xf.background.pattern_colour_index)
                if fg:
                    style['color'] = fg
                if bg and xf.background.fill_pattern:
                    style['background'] = bg
                if xf.alignment.hor_align in {1,2,3}:
                    style['align'] = {1:'left',2:'center',3:'right'}[xf.alignment.hor_align]
                for edge in ('left','right','top','bottom'):
                    line = getattr(xf.border,edge+'_line_style')
                    fg = palette(getattr(xf.border,edge+'_colour_index'))
                    if 0 < line < 14:
                        style['border_'+edge] = {'style':line} | ({'color':fg} if fg else {})
                fmt = reader.xls.format_map.get(xf.format_key)
                if fmt:
                    style['number_format'] = fmt.format_str[:160]
                layout['cells'][f'{row}|{col}'] = style
        areas = [(r0+1,c0+1,r1,c1) for r0,r1,c0,c1 in sheet.merged_cells]
    else:
        root = reader._xml(reader.paths[sheet_name])
        styles = xlsx_styles(reader)
        for node in root.findall(f'{{{NS}}}cols/{{{NS}}}col'):
            width = bounded(float(node.attrib.get('width',20))*7+5,150)
            for col in range(max(first_col,int(node.attrib['min'])),min(last_col,int(node.attrib['max']))+1):
                layout['widths'][str(col)] = width
        for row in root.findall(f'{{{NS}}}sheetData/{{{NS}}}row'):
            number = int(row.attrib['r'])
            if number not in allowed_rows:
                continue
            if 'ht' in row.attrib:
                layout['heights'][str(number)] = bounded(float(row.attrib['ht'])*4/3,32,12,500)
            for cell in row.findall(f'{{{NS}}}c'):
                match = re.fullmatch(r'([A-Z]+)\d+',cell.attrib.get('r',''))
                if not match:
                    continue
                col = column_number(match.group(1))
                index = int(cell.attrib.get('s',0))
                if first_col <= col <= last_col and index < len(styles):
                    layout['cells'][f'{number}|{col}'] = styles[index] | {'numeric': cell.attrib.get('t', '') in {'', 'n'} and cell.find(f'{{{NS}}}v') is not None}
        areas = []
        for node in root.findall(f'{{{NS}}}mergeCells/{{{NS}}}mergeCell'):
            match = re.fullmatch(r'([A-Z]+)(\d+):([A-Z]+)(\d+)',node.attrib.get('ref',''))
            if match:
                c0,r0,c1,r1 = match.groups()
                areas.append((int(r0),column_number(c0),int(r1),column_number(c1)))
    for r0,c0,r1,c1 in areas:
        if r1-r0 > 5000 or c1-c0 > 50 or r0 == header and r1 > header:
            continue
        if c0 >= first_col and c1 <= last_col and all(r in allowed_rows for r in range(r0,r1+1)):
            layout['merges'].append({'rows':list(range(r0,r1+1)),'cols':list(range(c0,c1+1))})
    return layout
