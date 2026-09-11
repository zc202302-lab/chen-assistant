from __future__ import annotations

from .v101_recipe_template_data_a import TEMPLATE_RECIPES as _A
from .v101_recipe_template_data_b import TEMPLATE_RECIPES as _B
from .v101_recipe_template_data_c import TEMPLATE_RECIPES as _C

TEMPLATE_IMPORT_MARKER = '[excel-template-v101]'
TEMPLATE_RECIPES = {**_A, **_B, **_C}

TEMPLATE_CATEGORIES = {
    '糖醋排骨': '肉类', '尖椒干豆腐': '家常', '西红柿鸡蛋汤': '汤', '红烧肉': '肉类',
    '锅包肉': '肉类', '水饺': '主食', '照烧鸡腿': '肉类', '红烧鲈鱼': '鱼类',
    '糖醋里脊': '肉类', '姜丝炸鸡': '肉类', '宫保虾球': '海鲜', '萝卜丸子': '家常',
    '酥锅': '家常', 'Sheet2': '其他', '椒盐鸡翅': '肉类', '空气炸锅鸡翅': '肉类',
    '寿司': '主食', '砸鱼汤': '汤',
}

# 与“糖醋排骨”Sheet结构一致的有效菜谱Sheet；不含空白“模板”Sheet。
TEMPLATE_SHEET_NAMES = tuple(TEMPLATE_RECIPES.keys())
