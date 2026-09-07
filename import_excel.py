import argparse
from app.importer import import_xlsm

p = argparse.ArgumentParser(description='把客户管理.xlsm导入晨的助手数据库')
p.add_argument('file')
p.add_argument('--append', action='store_true', help='不清空现有客户数据（一般不建议）')
a = p.parse_args()
print(import_xlsm(a.file, replace=not a.append))
