# 晨的助手：客户资料远程存储节点

## 架构

- 青岛 ECS：晨的助手程序、SQLite、客户资料元数据。
- RackNerd 美国 VPS：文件本体，仅监听 `127.0.0.1:18790`。
- 两台服务器之间：SSH 本地端口转发，所有文件内容和 Token 都在 SSH 加密通道内传输。
- 浏览器永远只访问晨的助手；不会直接访问 RackNerd。

## 部署顺序

1. 晨的助手主仓库部署到青岛 ECS。
2. 从青岛 ECS 将 `storage_node/` 复制到 RackNerd，例如：
   `scp -r /opt/chen-assistant/storage_node root@172.245.54.13:/root/chen-storage-setup`
3. 登录 RackNerd：
   `ssh root@172.245.54.13`
4. 在 RackNerd 执行：
   `bash /root/chen-storage-setup/install_racknerd.sh`
   保存脚本最后打印的 Token。
5. 回到青岛 ECS，首次建立免密 SSH：
   `ssh-copy-id root@172.245.54.13`
6. 在青岛 ECS 执行：
   `bash /opt/chen-assistant/storage_node/install_qingdao_tunnel.sh '<TOKEN>' 172.245.54.13`
7. 验证：
   - 青岛：`curl http://127.0.0.1:18790/health`
   - RackNerd：`systemctl status chen-storage --no-pager`
   - 青岛：`systemctl status chen-storage-tunnel --no-pager`

## 安全边界

RackNerd 不需要开放 18790 端口。文件服务仅绑定 localhost；公网只能看到原有 SSH 端口。即使有人扫描到 RackNerd IP，也不能直接访问客户文件 API。

## 数据位置

文件本体默认位于：`/data/chen-files/`

SQLite 只保存：客户ID、分类、原文件名、随机 storage key、大小、MIME、SHA256、创建时间。
