"""Bounded workbook parsing and permanent relay content, without browser access."""
import io
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from member_models import MemberTask

XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _xml_text(root: ET.Element) -> str:
    return "".join(node.text or "" for node in root.iter(f"{{{XLSX_NS}}}t"))


def _column_number(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return 0
    value = 0
    for char in letters.group(0):
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def read_member_tasks_xlsx(path: Path, allow_empty: bool = False) -> list[MemberTask]:
    """Read the no-header A=service number, B=group search value workbook."""
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("任务文件不能超过5 MB")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("任务文件不是有效的 .xlsx 工作簿") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > 4000 or sum(i.file_size for i in infos) > 64 * 1024 * 1024 or any(i.file_size > 32 * 1024 * 1024 for i in infos):
            raise ValueError("任务表展开后过大，请拆分文件")
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("任务文件缺少工作簿内容")
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relations.findall(f"{{{PKG_REL_NS}}}Relationship")}
        sheets = workbook.findall(f"{{{XLSX_NS}}}sheets/{{{XLSX_NS}}}sheet")
        if not sheets:
            raise ValueError("任务文件没有工作表")
        relation_id = sheets[0].attrib.get(f"{{{REL_NS}}}id", "")
        target = relmap.get(relation_id, "")
        if not target:
            raise ValueError("无法定位任务工作表")
        sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        if sheet_path not in names:
            raise ValueError("任务工作表文件不存在")

        shared_strings = []
        if "xl/sharedStrings.xml" in names:
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [_xml_text(si) for si in shared_root.findall(f"{{{XLSX_NS}}}si")]

        sheet = ET.fromstring(archive.read(sheet_path))
        tasks: list[MemberTask] = []
        for row in sheet.findall(f".//{{{XLSX_NS}}}sheetData/{{{XLSX_NS}}}row"):
            row_number = int(row.attrib.get("r", "0") or 0)
            values: dict[int, str] = {}
            for cell in row.findall(f"{{{XLSX_NS}}}c"):
                column = _column_number(cell.attrib.get("r", ""))
                if column not in (1, 2):
                    continue
                cell_type = cell.attrib.get("t", "")
                if cell_type == "inlineStr":
                    value = _xml_text(cell.find(f"{{{XLSX_NS}}}is")) if cell.find(f"{{{XLSX_NS}}}is") is not None else ""
                else:
                    raw = cell.find(f"{{{XLSX_NS}}}v")
                    value = raw.text or "" if raw is not None else ""
                    if cell_type == "s" and value:
                        try:
                            value = shared_strings[int(value)]
                        except (ValueError, IndexError):
                            raise ValueError(f"第 {row_number} 行共享字符串索引无效")
                values[column] = value.strip()

            service_number = values.get(1, "")
            group_search = values.get(2, "")
            if not service_number and not group_search:
                continue
            if not re.fullmatch(r"\d{5,20}", service_number):
                raise ValueError(f"第 {row_number} 行 A 列不是 5 至 20 位数字号码")
            if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", group_search):
                raise ValueError(f"第 {row_number} 行 B 列集团搜索值格式无效")
            if len(tasks) >= 5000:
                raise ValueError("每批号码不能超过5000行")
            tasks.append(MemberTask(row_number, service_number, group_search))
        if not tasks and not allow_empty:
            raise ValueError("任务文件中没有可执行号码")
        return tasks


EMPTY_RELAY_MARKER = b"CHEN_EMPTY_RELAY_V1"


def empty_relay_workbook() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{XLSX_NS}" xmlns:r="{REL_NS}"><sheets><sheet name="号码加集团" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{PKG_REL_NS}"><Relationship Id="rId1" Type="{REL_NS}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{XLSX_NS}"><sheetData/></worksheet>')
        archive.comment = EMPTY_RELAY_MARKER
    return output.getvalue()


