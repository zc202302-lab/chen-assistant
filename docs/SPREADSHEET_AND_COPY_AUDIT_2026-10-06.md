# 清单网页表格与页面文案审查 · 2026-10-06

## 实施范围

- 清单新建默认4个数据行、3列；列标题直接编辑，逐列筛选、清除筛选、增行增列、Excel多格纯文本粘贴、拖动或键盘调整行高列宽。
- 表格整批事务保存，保留既有记录ID、关联客户、状态、备注、隐藏字段；检查清单与每条记录revision及完整行列快照。归档只读，非法格式/数据或并发修改不部分写入。
- Excel导入归入新建菜单，原有上传/工作表范围/匹配/预览/确认及重复检查继续使用；新建导入保存所选范围的字体、颜色、边框、对齐、数字格式、行列尺寸、内部空行和完整合并区域。追加导入不覆盖已有表格布局。
- 导出真实XLSX，恢复表格布局，所有文本及公式样式文本均按安全文本输出；数字及已缓存日期按原格式写入。已有记录的状态/客户/备注有值时同时导出。
- 大表每页100行，筛选覆盖全部记录。图片、图表、宏、条件格式和公式计算引擎不属于此表格编辑器；公式导入使用Excel已保存的结果。越过所选表头/范围的合并区域不隐藏编辑区域。
- 记录详情及原字段模板保留为按需展开的兼容入口，不常驻主操作区域。新建/编辑使用同一表格组件；没有新增URL，原路由及源码所有者保持。

## 冗余文案审查

检查全部63份HTML模板和46份静态JavaScript。清理文件：
- app/templates/cooking_tools_v12.html
- app/templates/customer_detail.html
- app/templates/customer_form.html
- app/templates/customer_workspace_v028.html
- app/templates/dashboard_v027.html
- app/templates/home_v10.html
- app/templates/information_center_v160.html
- app/templates/information_edit_v160.html
- app/templates/life_home_v12.html
- app/templates/number_inbox_v162.html
- app/templates/recipe_detail_v10.html
- app/templates/recipe_detail_v12.html
- app/templates/reminders.html
- app/templates/work_home_v10.html
- app/templates/work_library_v14.html
- app/templates/work_list_import.html
- app/templates/work_list_settings.html
- app/templates/work_shell_v14.html
- app/static/v03_payment_template.js
- app/static/v033_payment_flow_patch.js
- app/static/v0212.js

删除：产品/开发背景、版本迁移解释、无须用户操作的实现机制、重复功能介绍。
缩短：列宽操作、全局属性影响、导入限制、字段隐藏说明。
保留：必填/错误/空状态、确认结果、归档只读、全局修改范围、密码及连接码边界、iPhone推送必要安装步骤、公式缓存和数字精度限制、Foxmail实际人工发送操作。仅修改展示文字，不删除业务功能或测试流程。

## 验证

本地Excel格式读取测试通过：内部空行、字体/填色/数字格式、行列尺寸与合并区域。
CI对应提交与生产验证结果记录在AI_HANDOFF顶部当前快照；WIP时不得声称已部署。
