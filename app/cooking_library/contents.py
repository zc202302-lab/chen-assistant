"""Explicit directory maintenance; never guesses printed-to-PDF page mappings."""
import argparse
import json
from pathlib import Path
from .store import database


def replace_contents(book_id, entries):
    with database() as conn:
        book = conn.execute('SELECT pages FROM books WHERE id=?',(book_id,)).fetchone()
        if not book:
            raise ValueError('书刊不存在')
        if not isinstance(entries,list) or len(entries)>5000:
            raise ValueError('目录必须是数组，最多5000项')
        rows=[]
        for position, entry in enumerate(entries,1):
            if not isinstance(entry,dict):
                raise ValueError('目录项格式错误')
            title,page,level=entry.get('title'),entry.get('page'),entry.get('level',1)
            if not isinstance(title,str) or not title.strip() or len(title)>500:
                raise ValueError('目录标题须为1至500字')
            if type(page) is not int or not 1<=page<=book['pages'] or type(level) is not int or not 1<=level<=10:
                raise ValueError('目录页码或层级超限；page须为实际PDF页码，从1开始')
            rows.append((book_id,position,title.strip(),page,level))
        conn.execute('DELETE FROM book_contents WHERE book_id=?',(book_id,))
        conn.executemany('INSERT INTO book_contents VALUES(?,?,?,?,?)',rows)
    return len(rows)


def main():
    parser=argparse.ArgumentParser(description='为已有书刊导入目录；仅更新独立书刊库')
    parser.add_argument('--book-id',type=int,required=True)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--json',type=Path,help='[{"title":"章节","page":1,"level":1}]')
    source.add_argument('--pdf',type=Path,help='从同一本PDF提取书签；核对SHA后更新')
    args=parser.parse_args()
    if args.json:
        if args.json.stat().st_size>2*1024*1024:
            parser.error('目录文件超过2MiB')
        entries=json.loads(args.json.read_text(encoding='utf-8'))
    else:
        import hashlib
        import fitz
        with args.pdf.open('rb') as source_file:
            digest=hashlib.file_digest(source_file,'sha256').hexdigest()
        with database() as conn:
            row=conn.execute('SELECT sha256 FROM books WHERE id=?',(args.book_id,)).fetchone()
        if not row or row['sha256']!=digest:
            parser.error('PDF与书刊不匹配')
        with fitz.open(args.pdf) as doc:
            entries=[{'title':title,'page':page,'level':min(level,10)} for level,title,page in doc.get_toc() if page>0]
        if not entries:
            parser.error('PDF没有书签目录，原目录未修改；请使用JSON目录')
    print(f'已更新{replace_contents(args.book_id,entries)}条目录')


if __name__=='__main__':
    main()
