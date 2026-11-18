# WireGuard 用户管理（Ubuntu 22.04）

安装或升级时，把同一版本的 `bin/` 和 `systemd/` 一起上传到 VPS。安装器使用 Ubuntu 软件源中的 wireguard、qrencode 和 microsocks（需启用 universe）。在云防火墙放行入站 UDP 51820，SOCKS5 端口只供隧道内使用。

```bash
cd ~/vps_ubuntu
sudo bash bin/wireguard-install.sh 你的VPS公网IPv4
sudo wgvps-users list
```

安装后有 25 个已启用的用户（user01 至 user25），默认全局模式。每个用户有独立的 IPv4、IPv6、密钥对和预共享密钥。一份配置分配给一台同时在线的设备。旧版安装请填原 Endpoint；安装器校验原来的单 peer 与客户端是否匹配，并将其保留为 user01，原设备可继续连接。重复安装会保留已有用户状态。

## 分发配置

手机在 WireGuard 中选择扫码添加，管理员在私密终端显示对应用户的二维码：

```bash
sudo wgvps-users qr user02
```

Windows 或其他桌面端可导入配置文件。在 VPS 上用以下命令导出到当前用户的私有目录，再用 SFTP 或 SCP 单独发给对应使用者。二维码和文件都含有该用户的完整凭据。

```bash
install -d -m 700 ~/wg-exports
(umask 077 && sudo wgvps-users export user02 > ~/wg-exports/user02.conf)
```

## 全局与代理模式

| 模式 | 客户端行为 | 应用设置 |
|---|---|---|
| global | IPv4 和 IPv6 默认路由进隧道，配置 DNS 为 1.1.1.1 和 1.0.0.1 | 使用系统网络，关闭原应用代理 |
| proxy | 仅 10.66.77.1/32 走隧道，保留本地默认路由和 DNS | 指定应用使用 SOCKS5 地址 10.66.77.1、端口 1080，按需开启代理端域名解析 |

```bash
sudo wgvps-users mode user02 proxy
sudo wgvps-users qr user02
# 切回全局
sudo wgvps-users mode user02 global
```

每次切换后，重新导出或扫码，在设备上替换旧配置并激活。模式是客户端的路由选择，不限制用户自行修改客户端配置。代理服务提供 TCP CONNECT；需要 UDP 应用经过 VPS 时选全局。全局模式需要 VPS 有 IPv6 出口才能访问 IPv6 站点。

## 禁用、恢复与密钥轮换

```bash
sudo wgvps-users disable user02
sudo wgvps-users enable user02
sudo wgvps-users rotate user02
sudo wgvps-users qr user02
```

禁用会将该 peer 从服务端持久配置与运行中的接口移除。恢复后原配置可继续使用。轮换会替换该用户的密钥对和预共享密钥，保留地址、模式及启用状态；重新分发后旧配置失效。已禁用的账号可以轮换，启用后才能导出。所有用户变更通过管理命令执行。

## 验收与运维

1. 在 VPS 执行 `sudo wg show wgvps`，检查已启用用户数、最近握手及收发计数。使用两台设备分别导入两个用户配置。
2. 全局模式下，在客户端运行 `curl --noproxy "*" -4 https://api.ipify.org`，应显示 VPS 出口 IPv4。Windows PowerShell 请使用 `curl.exe`。
3. 代理模式下，前一条命令应显示客户端网络出口。运行 `curl --noproxy "" --proxy socks5h://10.66.77.1:1080 https://api.ipify.org` 应显示 VPS 出口。检查服务可用 `systemctl status wgvps-proxy`。
4. 禁用一个用户，验证其流量停止，另一台仍可访问。轮换后验证旧配置无法握手，新配置可连接。重启服务器后再核对禁用状态与模式。
5. 同步失败时检查报错和 `sudo journalctl -u wg-quick@wgvps -u wgvps-proxy`。修复原因后运行 `sudo wgvps-users list`，它会先重试未完成的变更。

私钥及用户状态保存在 root 专用的 `/etc/wireguard/`。原客户端路径 `windows-vps.conf` 跟随 user01 更新，禁用时移除。独立导出的文件需自行保管。服务器 MTU 为 1380，使用带 wgvps 标记的 IPv4/IPv6 转发与 NAT 规则。原转发参数记录在 `wgvps-forwarding-before.txt`，持久化在 `/etc/sysctl.d/90-ssr-wireguard.conf`。

停止并取消开机启动可运行 `sudo systemctl disable --now wgvps-proxy wg-quick@wgvps`。停止服务会释放对应防火墙规则，保留用户配置。恢复全局转发参数前，应确认其他服务是否依赖这些设置。
