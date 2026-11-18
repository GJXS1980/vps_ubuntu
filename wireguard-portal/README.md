# WireGuard 用户中心

独立运行在 Windows Docker Desktop 或 Linux Docker Engine 上的中文用户门户。用户注册、管理员审核、设备申请和配置领取使用本地账号；VPS 继续由原 wgvps 管理器维护。没有 VPS 时可安装、登录和管理账号。

## 快速启动

在仓库根目录执行 Windows PowerShell：

```powershell
cd wireguard-portal
.\install-local.ps1
```

Linux：

```bash
cd wireguard-portal
bash install-local.sh
```

安装时在私密终端输入首个管理员的邮箱、密码，并用 TOTP 应用确认 MFA。默认访问 https://localhost:8444 。先核对并信任 secrets/web/tls.crt，再登录。已有管理员和密钥会保留。默认注册需要人工审核。安装详情见 [本地安装](../docs/wireguard-portal/05-local-installation.md)。

## 接入 VPS

先按[专用隧道和 Agent 安装](../docs/wireguard-portal/06-vps-agent-installation.md)生成双方凭据、配置独立接口并检查 mTLS。管理员在“VPS 监控”添加管理地址后，用户才可申请设备。平台保留旧 user01 和管理地址空间；普通用户仅访问本地平台。仓库中的脚本需随整个项目一起复制。

## 验证与运维

- [源码审计](../docs/wireguard-portal/01-existing-system-analysis.md)与[架构](../docs/wireguard-portal/02-architecture.md)
- [数据库设计](../docs/wireguard-portal/03-database-design.md)与[接口](../docs/wireguard-portal/04-api-reference.md)
- [用户手册](../docs/wireguard-portal/07-user-guide.md)与[管理员手册](../docs/wireguard-portal/08-admin-guide.md)
- [安全设计](../docs/wireguard-portal/09-security.md)、[验收记录](../docs/wireguard-portal/10-testing.md)、[升级回滚](../docs/wireguard-portal/11-upgrade-rollback.md)与[运行限制](../docs/wireguard-portal/12-open-issues.md)

