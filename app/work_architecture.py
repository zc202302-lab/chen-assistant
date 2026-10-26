from __future__ import annotations

# Work module architecture
#
# The work space is intentionally split into two user-facing domains:
# 1) customer management: customer-scoped instance data;
# 2) work library: reusable public work knowledge/materials.
#
# Shared templates/rules are a third internal layer. They are not a top-level
# navigation module because they define structure and defaults rather than
# day-to-day records. Future features should keep these boundaries explicit.

WORK_DOMAINS = (
    {
        'key': 'customers',
        'title': '客户管理',
        'description': '围绕一个个客户组织缴费、业务、联系人、资料、待办与跟进。客户数据彼此隔离。',
        'href': '/customers',
    },
    {
        'key': 'library',
        'title': '工作资料',
        'description': '存放可跨客户重复使用的产品、资费、流程、操作截图、制度规范与模板资料。',
        'href': '/work/library',
    },
)

WORK_LIBRARY_CATEGORIES = (
    {'key': 'product', 'title': '产品资料', 'description': '产品介绍、能力说明、适用场景等通用资料。'},
    {'key': 'pricing', 'title': '资费资料', 'description': '专线、云、ICT 等业务的价格、政策与版本化资费。'},
    {'key': 'process', 'title': '开通流程', 'description': '业务受理、审批、开通、交付和变更流程。'},
    {'key': 'guide', 'title': '操作指南', 'description': '系统操作步骤、注意事项和常见问题。'},
    {'key': 'screenshot', 'title': '系统截图', 'description': '后台界面、关键字段位置和操作过程截图。'},
    {'key': 'policy', 'title': '制度规范', 'description': '业务规则、制度文件、内部规范和执行口径。'},
    {'key': 'template', 'title': '模板文件', 'description': '报价、方案、合同、通知等可复用文件模板。'},
    {'key': 'other', 'title': '其他资料', 'description': '暂不属于以上分类但需要长期保存的通用工作资料。'},
)

CUSTOMER_INSTANCE_DATA = (
    '客户基础信息',
    '客户业务实例',
    '缴费数据与流程状态',
    '联系人',
    '客户资料',
    '待办与跟进',
    '客户个性化属性设置',
)

SHARED_RULE_LAYERS = (
    '业务模板',
    '业务属性模板',
    '缴费模板',
    '客户属性模板',
    '产品定义',
    '分类与标签',
)

ARCHITECTURE_RULES = (
    '客户实例数据必须归属于明确的 customer_id，不在客户之间共享实际值。',
    '公共模板只定义结构、默认值和规则，不拥有或覆盖客户实例数据。',
    '工作资料是跨客户复用的知识资产，不复制到每个客户名下。',
    '模板升级默认向前兼容；新增字段不得覆盖已有客户实例值。',
    '客户业务可以关联工作资料，但关联不等于复制文件。',
)


# Stable entry keys also own saved ordering; display labels may change independently.
WORK_ENTRIES = (
    {'key': 'todos', 'title': '待办事项', 'href': '/work/todos', 'icon': 'list', 'color': 'purple', 'description': '独立待办、定时提醒与结办'},
    {'key': 'processes', 'title': '业务流程', 'href': '/work/processes', 'icon': 'process', 'color': 'teal', 'description': '分步说明、操作配图与办理指南'},
    {'key': 'customers', 'title': '客户管理', 'href': '/work/customers', 'icon': 'customers', 'color': 'blue', 'description': '缴费、业务与客户资料'},
    {'key': 'library', 'title': '工作资料', 'href': '/work/library', 'icon': 'folder', 'color': 'green', 'description': '产品、资费与流程'},
    {'key': 'lists', 'title': '清单', 'href': '/work/lists', 'icon': 'list', 'color': 'purple', 'description': '欠费、商机与自由记录'},
    {'key': 'all_customers', 'title': '全部客户', 'href': '/customers', 'icon': 'customers', 'color': 'blue', 'description': '查找、新建与导入客户'},
    {'key': 'products', 'title': '产品汇总', 'href': '/products', 'icon': 'product', 'color': 'orange', 'description': '业务类型与客户分布'},
    {'key': 'search', 'title': '工作搜索', 'href': '/search', 'icon': 'search', 'color': 'slate', 'description': '查询客户、号码与账号'},
    {'key': 'numbers', 'title': '号码收集', 'href': '/work/number-inbox', 'icon': 'phone', 'color': 'teal', 'description': '收集与批量录入号码'},
    {'key': 'payment', 'title': '缴费', 'href': '/work/customers?home=payment', 'icon': 'wallet', 'color': 'blue', 'description': '缴费查询与流程处理'},
    {'key': 'promos', 'title': '优惠', 'href': '/work/customers?home=promos', 'icon': 'tag', 'color': 'orange', 'description': '优惠到期与客户跟进'},
)
DEFAULT_ENTRY_LAYOUT = {'common': ['customers', 'todos', 'library', 'lists', 'processes'],
                        'auxiliary': ['all_customers', 'products', 'search', 'numbers', 'payment', 'promos']}
LAYOUT_KEY = 'work_entry_layout_v1'


def validate_entry_layout(layout):
    if not isinstance(layout, dict) or set(layout) != {'common', 'auxiliary'}:
        raise ValueError('入口布局格式无效')
    values = list(layout.values())
    if any(not isinstance(v, list) for v in values):
        raise ValueError('入口布局格式无效')
    keys = layout['common'] + layout['auxiliary']
    if any(not isinstance(k, str) for k in keys) or sorted(keys) != sorted(e['key'] for e in WORK_ENTRIES):
        raise ValueError('每个入口必须且只能出现一次')
    return layout


def entry_layout(conn):
    import json
    row = conn.execute('SELECT value FROM app_meta WHERE key=?', (LAYOUT_KEY,)).fetchone()
    try:
        if not row:
            return DEFAULT_ENTRY_LAYOUT
        layout = json.loads(row['value'])
        # Add new entries without discarding saved ordering from any known generation.
        if isinstance(layout, dict) and set(layout) == {'common', 'auxiliary'} and all(isinstance(v, list) for v in layout.values()):
            keys = layout['common'] + layout['auxiliary']
            known = {e['key'] for e in WORK_ENTRIES}
            if all(isinstance(k, str) for k in keys) and len(keys) == len(set(keys)) and set(keys) <= known:
                for key in ('payment', 'promos'):
                    if key not in keys:
                        layout['auxiliary'].append(key)
                for key in ('processes', 'todos'):
                    if key not in keys:
                        layout['common'].append(key)
        return validate_entry_layout(layout)
    except (ValueError, TypeError):
        return DEFAULT_ENTRY_LAYOUT


def entry_sections(conn):
    entries = {e['key']: e for e in WORK_ENTRIES}
    return [{'key': key, 'title': title, 'entries': [entries[k] for k in entry_layout(conn)[key]]}
            for key, title in [('common', '常用入口'), ('auxiliary', '辅助入口')]]
