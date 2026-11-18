# 升级、恢复与回滚
先记录代码版本、旧容器映像、服务状态和证书有效期。加密快照与单独保管的 data/backup.key 都是恢复所需材料。另行备份 .env、secrets、管理隧道配置。普通数据导出不包含这些生产凭据。

```bash
cd wireguard-portal
bash backup-local.sh
bash upgrade-local.sh
bash restore-local.sh portal-实际时间与编号.enc
```

升级脚本检查 Compose 配置、备份旧数据库、构建新镜像，再停应用执行 Alembic。失败时保持停机，检查原因。回滚时使用上次的代码和映像，恢复对应升级前快照，再启动；不要删除数据库重建。跨主机恢复先将原 backup.key 放入受保护 data 目录并恢复证书。控制台恢复会复原备份内的 MFA，远端 Peer 不随本地快照回退。启动 Worker 前应评估快照中的未完成任务及实际 VPS 变更。

Windows PowerShell 可直接用 docker compose run --rm api python -m app.maintenance backup /backups/手动备份.enc，停 web/api/worker 后用同一命令的 restore 子命令恢复，随后运行 alembic upgrade head，docker compose up -d。首次安装脚本可安全重跑。

Agent 使用 deploy/vps/wireguard-portal-agent-upgrade.sh。脚本将证书、适配器、服务文件备份到 root 私有目录，再更新 Agent。失败时恢复原代码、证书、unit 和匹配依赖版本，再 daemon-reload 和 restart wg-portal-agent。涉及依赖变更前另做 VPS 系统快照。卸载使用 wireguard-portal-agent-uninstall.sh；如需下线管理链路，再单独停用 wg-quick@wgportal。保留业务 WireGuard 接口及原 Web 服务。撤销已发客户端凭据需要独立审核和停用操作。

