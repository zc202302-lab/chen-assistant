# 厨艺资料库（独立首版，尚未生产启用）

只收录电子书和杂志，不导入爆款菜谱。原PDF留在私有OSS；独立数据库保存文字、PDF页序和OSS Object名称。当前支持原文关键词检索和逐页预览，不声称已实现语义搜索或AI研究。

## 隔离边界

- `app/cooking_library/`拥有实现、模板、样式和可选导入依赖。
- `COOKING_LIBRARY_ENABLED=1`才挂载`/cooking`；默认关闭，无启动迁移、worker、OSS连接或额外web依赖。
- 使用主站原有登录验证，不开放公共读；独立子应用也拒绝没有父级会话的请求。
- 独立目录`COOKING_LIBRARY_DIR`（默认`data/cooking-library`），数据库`catalogue.sqlite3`；不接触客户、缴费、号码收集数据表。备份本目录与OSS原件分别进行。
- OCR通过手动CLI运行，不能在主站进程执行。建议电脑或单独进程/受限服务运行，限制CPU、内存和磁盘；同机仍共享机器资源，不能保证绝对零影响。
- 首版保存110dpi预览JPEG到服务器，会额外占空间；这是本地缓存，不是另一套原始PDF。批量导入前测算大小。当前没有自动淘汰策略。

## 先导入一本本地PDF（无需OSS密钥）

在仓库根目录，为导入器单独安装`app/cooking_library/requirements-import.txt`；默认OCR为RapidOCR（中文ONNX模型随可选包安装），在独立进程离线运行；Web只需现有requirements。可选`--ocr-engine tesseract`需要另外安装Tesseract及`chi_sim`、`eng`语言数据。

```bash
export COOKING_LIBRARY_DIR=/path/to/cooking-library
python -m app.cooking_library.import_book --file '/path/to/book.pdf' --key 'ebooks/book.pdf' --title '流行酱卤60款' --ocr
```

`--key`必须使用真实OSS Object名称（可包含中文），不是临时签名URL。文字型PDF可不加`--ocr`；图片页不允许在未启用OCR时悄悄空白入库。默认300dpi识别，中文引擎按单线程初始化，逐页打印进度。RapidOCR原始行、四角坐标、置信度及阅读顺序保存在`ocr-audit/<SHA256>/<页码>.json`，不以低置信度为由丢弃返回行；检测器本身仍可能漏检。双栏采用保守几何排序，跨页菜谱尚未自动合并。整本完成后事务提交，失败不生成可检索的半本书。已完成原件按SHA256和Object名称查重。OCR可能错认数字/用量，原页是核查依据；空白页OCR结果允许为空。失败导入可能遗留预览文件，重试会覆盖相同内容预览，暂不自动删除。

## 从私有OSS读取

仅导入器进程需要以下环境变量，不写入仓库、网页或聊天：

- `COOKING_OSS_BUCKET=chen-cooking-library`
- `COOKING_OSS_ENDPOINT=https://oss-cn-qingdao.aliyuncs.com`
- `COOKING_OSS_ACCESS_KEY_ID`、`COOKING_OSS_ACCESS_KEY_SECRET`

使用仅允许该Bucket的`ebooks/*`、`magazines/*`执行GetObject的RAM身份，不需要公共读、删除或管理员权限。若账号访问要求自定义域名，按控制台提示配置Endpoint；尚未实测此账号。

省略`--file`将下载指定Object到临时目录，再导入；单文件限1GiB、5000页。单本下载会产生适用的请求/流量费用。本地导入无需重新从OSS下载。

## 启用与回退

完成离线与主站回归后，设置主站服务`COOKING_LIBRARY_ENABLED=1`及相同`COOKING_LIBRARY_DIR`并重启，然后登录访问`/cooking/`。启用后左上角☰隐藏菜单显示“厨艺资料库”，关闭时隐藏；顶部首页/工作/资料不变。模块内部也提供折叠菜单返回首页与生活。关闭开关并重启即撤下新模块，原数据保留。

不得把本地合成PDF测试描述为真实书刊OCR、OSS联调或生产部署通过。下一步：真实样书导入、OCR质量抽检、手机页面验证、资源测量；随后增加批量任务状态、语义检索和带出处的AI研究。

## 真实样书验证（2026-10-16，进行中）

用户提供《流行酱卤60款》电子版_579.pdf，74,757,776字节、98页，全部无PDF文字层。原180dpi Tesseract中英混合在PDF第11页出现标题和香料名乱码，不能以其作为可靠菜谱索引。300dpi RapidOCR样页能检索“北派香辣卤”，保留“62.5克”等数字，但仍将部分生僻香料名识错（例如荜拨、枳壳），不做自动纠字，不把模型置信度当准确率。完整导入与搜索/空间测量结果待完成后记录。用户原PDF未修改，真实文本与原图不提交公开仓库。
