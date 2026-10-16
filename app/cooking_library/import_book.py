"""Explicit CLI importer; never run during web requests. Requires optional deps."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from .store import database, root


def import_pdf(path, key, title, ocr=False):
    import fitz
    kind = key.split('/')[0]
    if kind not in {'ebooks', 'magazines'} or not key.lower().endswith('.pdf'):
        raise ValueError('仅允许ebooks/或magazines/下的PDF')
    with open(path, 'rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    with database() as conn:
        existing = conn.execute('SELECT id FROM books WHERE sha256=? OR object_key=?', (digest,key)).fetchone()
        if existing:
            return existing['id'], False
    previews = root() / 'previews' / digest
    previews.mkdir(parents=True, exist_ok=True)
    texts = []
    with fitz.open(path) as doc:
        if doc.needs_pass or not 0 < len(doc) <= 5000:
            raise ValueError('加密PDF或页数超限')
        for number, page in enumerate(doc, 1):
            if page.rect.width > 3000 or page.rect.height > 3000:
                raise ValueError(f'第{number}页尺寸超限')
            text = page.get_text(sort=True)
            method = 'pdf'
            if len(text.strip()) < 20:
                if not ocr:
                    raise ValueError(f'第{number}页需要OCR，请安装中文Tesseract后添加--ocr；未写入半本书')
                pix = page.get_pixmap(dpi=180)
                with tempfile.TemporaryDirectory() as tmp:
                    image_path = Path(tmp)/'page.png'
                    pix.save(image_path)
                    text = subprocess.run(['tesseract',str(image_path),'stdout','-l','chi_sim+eng'], capture_output=True,text=True,check=True,timeout=180).stdout
                method = 'ocr'
            target = previews / f'{number}.jpg'
            page.get_pixmap(dpi=110).save(target)
            texts.append((number,text,method))
    with database() as conn:
        # Recheck under the write transaction; UNIQUE also protects concurrent imports.
        existing = conn.execute('SELECT id FROM books WHERE sha256=? OR object_key=?',(digest,key)).fetchone()
        if existing:
            return existing['id'], False
        book_id = conn.execute('INSERT INTO books(title,kind,object_key,sha256,pages) VALUES(?,?,?,?,?)',(title,kind,key,digest,len(texts))).lastrowid
        for number,text,method in texts:
            conn.execute('INSERT INTO pages VALUES(?,?,?,?)',(book_id,number,text,method))
            conn.execute('INSERT INTO page_search(text,book_id,page) VALUES(?,?,?)',(text,book_id,number))
    return book_id, True


def main():
    parser = argparse.ArgumentParser(description='导入一本电子书或杂志；独立于主站运行')
    parser.add_argument('--key',required=True,help='OSS完整Object名称，含ebooks/或magazines/')
    parser.add_argument('--title',required=True)
    parser.add_argument('--file',type=Path,help='已有本地PDF；省略时从配置的OSS下载')
    parser.add_argument('--ocr',action='store_true')
    args = parser.parse_args()
    if args.key.split('/')[0] not in {'ebooks', 'magazines'} or not args.key.lower().endswith('.pdf'):
        parser.error('仅允许ebooks/或magazines/下的PDF')
    if args.file:
        print(import_pdf(args.file,args.key,args.title,args.ocr))
        return
    import oss2
    # Credentials only come from the importer environment. Never print signed URLs/keys.
    bucket = oss2.Bucket(oss2.Auth(os.environ['COOKING_OSS_ACCESS_KEY_ID'],os.environ['COOKING_OSS_ACCESS_KEY_SECRET']),os.environ['COOKING_OSS_ENDPOINT'],os.environ['COOKING_OSS_BUCKET'],connect_timeout=30)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'source.pdf'
        size = bucket.head_object(args.key).content_length
        if size > 1024**3:
            raise ValueError('单文件超过1GiB限制')
        response = bucket.get_object(args.key)
        received = 0
        try:
            with path.open('wb') as output:
                while chunk := response.read(1024*1024):
                    received += len(chunk)
                    if received > 1024**3:
                        raise ValueError('文件超过1GiB限制')
                    output.write(chunk)
        finally:
            response.close()
        if received != size:
            raise ValueError('下载长度不符，请重试')
        print(import_pdf(path,args.key,args.title,args.ocr))


if __name__ == '__main__':
    main()
