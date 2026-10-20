"""Private, reusable business instructions and their ordered illustrated steps."""
from io import BytesIO

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from .db import connection_scope, execute_schema, now_iso

SCHEMA = '''
CREATE TABLE IF NOT EXISTS business_processes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_process_steps (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 process_id INTEGER NOT NULL REFERENCES business_processes(id) ON DELETE CASCADE,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS business_steps_order ON business_process_steps(process_id,sort_order,id);
CREATE TABLE IF NOT EXISTS business_process_images (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 step_id INTEGER NOT NULL REFERENCES business_process_steps(id) ON DELETE CASCADE,
 content BLOB NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS business_images_step ON business_process_images(step_id,id);
'''
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def ensure_business_process_schema(conn=None):
    with connection_scope(conn) as conn:
        execute_schema(conn, SCHEMA)


def load_process(conn, process_id):
    ensure_business_process_schema(conn)
    item = conn.execute('SELECT * FROM business_processes WHERE id=?', (process_id,)).fetchone()
    if item is None:
        raise HTTPException(404, '业务流程不存在或已删除')
    return dict(item)


def load_step(conn, process_id, step_id):
    item = conn.execute('SELECT * FROM business_process_steps WHERE id=? AND process_id=?',
                        (step_id, process_id)).fetchone()
    if item is None:
        raise HTTPException(404, '流程步骤不存在或已删除')
    return dict(item)


def text_fields(form):
    title, description = str(form.get('title', '')).strip(), str(form.get('description', '')).strip()
    if not title or len(title) > 120:
        raise HTTPException(400, '请填写名称，最多120个字')
    if len(description) > 20000:
        raise HTTPException(400, '文字说明最多20000个字')
    return title, description


def revision_value(form):
    try:
        value = int(form.get('revision', ''))
        if not 1 <= value <= 9223372036854775807:
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise HTTPException(400, '页面版本无效，请重新打开编辑页面')


def claim_revision(conn, process_id, revision):
    # A conditional write serializes editors without losing newer changes.
    changed = conn.execute('''UPDATE business_processes SET revision=revision+1,updated_at=?
                              WHERE id=? AND revision=?''', (now_iso(), process_id, revision)).rowcount
    if not changed:
        raise HTTPException(409, '该流程已在其他页面更新，请保留本次填写内容，重新打开流程后再修改')


def sanitize_image(content):
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(413, '每张图片最多8MB')
    try:
        with Image.open(BytesIO(content), formats=('PNG', 'JPEG', 'WEBP')) as image:
            if image.width * image.height > 16_000_000 or getattr(image, 'n_frames', 1) != 1:
                raise HTTPException(400, '请使用不超过1600万像素的静态图片')
            image.load()
            clean = ImageOps.exif_transpose(image)
            clean = clean.convert('RGBA' if 'A' in clean.getbands() or 'transparency' in clean.info else 'RGB')
            output = BytesIO()
            clean.save(output, format='WEBP', quality=92, method=4)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, '图片无法读取，请上传有效的PNG、JPEG或WebP图片')
