# 书刊资料库已从小助手移出

用户2026-10-17确定将书刊功能迁移为独立网站`cook.ziboxiaozhushou.cn`，并要求移除小助手中的部署内容。

本次移除隐藏菜单入口、`/cooking`子应用挂载，以及`app/cooking_library/`的阅读、OCR和离线导入代码。原业务中的生活空间、菜谱工具、客户、缴费、号码收集、Windows助手保持原职责；不按“cooking”字样删除其他成熟功能。

不删除服务器`/opt/chen-assistant/data/cooking-library`，其中数据库、原页预览、OCR记录可供新站迁移。原始PDF在青岛私有OSS，未改权限或Object。现有可下载样书ZIP与47条目录JSON保留。源代码可从Git历史合并提交`0f810227425566ca1261d88897b479efde613b1b`中的`app/cooking_library/`恢复复用；不是要求在小助手重新启用。

现有systemd drop-in里的`COOKING_LIBRARY_ENABLED`、`COOKING_LIBRARY_DIR`即使暂时保留，也不会重新挂载已经移除的功能。代码更新后无需删除数据或安装/卸载OCR依赖。此次没有部署独立新站、操作DNS、申请证书或设置新站自动部署。

验证以`tests/cooking_removal_contract.py`和`tests/assistant_navigation_acceptance.py`覆盖：即使遗留开关为1，路由也不存在、菜单没有入口、私有文件不变，原导航和健康检查保留。原书刊导入/OCR/阅读测试随功能移出主仓库，不再测试不存在的功能；所有原业务契约和完整回归保留。
