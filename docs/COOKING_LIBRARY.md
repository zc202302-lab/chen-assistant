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

## 真实样书验证（2026-10-16，离线验证完成）

用户提供《流行酱卤60款》电子版_579.pdf，74,757,776字节、98页，全部无PDF文字层。原180dpi Tesseract中英混合在PDF第11页出现标题和香料名乱码，不能以其作为可靠菜谱索引。300dpi RapidOCR样页能检索“北派香辣卤”，保留“62.5克”等数字，但仍将部分生僻香料名识错（例如荜拨、枳壳），不做自动纠字，不把模型置信度当准确率。整本98页已导入，保存58,772个字符，无空文字页；关键词“北派香辣卤”“烤猪手专用卤水”“正宗盐水鸭卤水”分别命中正文PDF第11/40/55页（同时命中目录第4页），网页搜索、页面文字与JPEG响应均通过。第11页小数62.5克、第40页2.5千克与第55页7.5克抽检保留，不据此推断全部用量准确。真实偏心双栏需搜索实际栏间空隙；已用保留的原始行重建阅读顺序和全文索引，新增偏心分栏回归。用户原PDF未修改，真实文本与原图不提交公开仓库。

样书体积：原件74,757,776字节；预览17,415,407字节，原始OCR行/坐标968,078字节，SQLite1,593,344字节，派生数据约19.1MiB。测试库压缩包约17.1MiB，保存为cooking_library_sample_579.zip，用户可用于空资料库初始化；没有放进公开仓库。此样本不能用于保证其他书刊的压缩比、识别准确率或检索完整率。

已有主站/隐藏菜单实现受检head476d06d69bb0d7dc7823b79ba692c5440180f6ee：validation38917223919、stability38917223982、独立资料库38917223867全部success；包含320/390/768/1440隐藏菜单点击实测。后续OCR改进另查最新head的CI；不是生产启用或真实OSS联调证据。

## 书刊阅读第一版

入口保持左上角隐藏菜单。书刊库按电子书/杂志浏览封面；点击进入书刊详情，目录显示章节标题及实际PDF页码，点击跳到原页。阅读器支持前后翻页、页码跳转、50%～250%缩放、适合宽度。上次阅读页码只保存在当前浏览器本地，不跨设备同步。关键词搜索保留，图片书未识别的正文不能搜索。

阅读不要求全文OCR。原PDF保持青岛私有OSS，当前阅读使用服务器上的110dpi JPEG衍生预览；不向浏览器泄露OSS凭据，不增加主站依赖，不启用美国worker。预览缩放不会恢复原PDF细节。目录为新增独立book_contents表，旧书库原页、识别文字和索引保留。

只生成阅读预览并自动提取PDF书签：

```bash
python -m app.cooking_library.import_book --key 'magazines/example.pdf' --title '刊物名称' --reading-only
```

OSS环境变量沿用上文。也可加`--file /path/to/source.pdf`使用本地原件；不会把原PDF复制进资料库。导入仍为显式离线CLI，尚未增加网页上传/OSS自动同步。

对已经导入的同一本书补提取书签（SHA必须一致）：

```bash
python -m app.cooking_library.contents --book-id 1 --pdf /path/to/source.pdf
```

无书签时导入UTF-8 JSON数组，各项`title`标题、`page`实际PDF页码（从1开始）、可选`level`层级1～10；例如`[{"title":"第一章","page":6}]`。印刷页码与实际PDF页码可能不同，不自动推算；允许同页多章节和非单调页码。全量校验成功后事务替换目录，失败保留旧目录；空数组明确清空。目录维护目前为管理员CLI，未提供网页编辑器。

```bash
python -m app.cooking_library.contents --book-id 1 --json /path/to/contents.json
```

现有98页样书没有PDF书签，需另行校对/导入目录；不能把有阅读器等同于真实书刊目录均已补全。下载工具webdownload的部分目录正文采集流程会写入PDF书签，新下载的这类书刊可直接提取，其他导出模式不保证有书签。
