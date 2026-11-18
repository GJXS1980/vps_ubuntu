# 本地安装与 HTTPS
安装 Docker Desktop（Linux containers）或 Docker Engine 与 Compose v2。在仓库的 wireguard-portal 目录执行 install-local.ps1 或 bash install-local.sh。首次安装需要终端输入管理员凭据。脚本生成本地证书、生成备份密钥、升级数据库、初始化管理员、启动 web、api 和 worker，最后从 Compose 网络验证入口和 /api/health。失败时用 docker compose ps 和 docker compose logs --tail=100 检查服务，修复后可重跑。

默认仅将 HTTPS 发布到宿主机 127.0.0.1:8444。核对 secrets/web/tls.crt 的 SHA-256 指纹后，将其导入自己的受信任证书存储；如有私有 CA，可预置自己的证书和私钥。Windows 使用仅本人及系统管理员可读的 NTFS 目录保存 data、secrets、backups；Linux 目录应为 0700，私钥 0600。备份 data/backup.key 到离线安全位置。

## 局域网和公网
在 .env 设 PORTAL_BIND 为指定网卡 IP，PORTAL_PORT 为外部端口，PORTAL_ORIGIN 为浏览器实际使用的完整 HTTPS 源，含非默认端口。预置与域名或 IP 匹配的 secrets/web/tls.crt 和 tls.key，使用 docker compose up -d --force-recreate 应用改动。局域网证书可由组织 CA 签发。公网须使用有效公信证书、完整证书链和域名解析，开放本地入口的 TCP 端口并核对来源策略。仅暴露 web。入口终止 TLS 后向内部 API 传递 Host、重写客户端地址；API 不解析上游 X-Forwarded-*。外接代理时应限制代理到入口的来源并保持原始 Host，客户端限流将按末级直连地址计数。CORS 采用同源，所有写请求要求精确 Origin，认证写入另需 CSRF header。浏览器无需访问 VPS 管理端口。

## 邮件与离线运行
在 .env 配置 SMTP_HOST、SMTP_PORT（隐式 TLS，默认 465）、SMTP_FROM，可选 SMTP_USER；把 SMTP 密码置于 secrets/agents/smtp-password（容器内 /certs/smtp-password）。重建 api。未启用 SMTP 时可用人工审批、邀请码和控制台重置密码。VPS 离线不阻止本地服务启动。
