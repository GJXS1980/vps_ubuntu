# WireGuard 用户管理（Ubuntu 22.04）

安装或升级时，把同一版本的 `bin/` 和 `systemd/` 一起上传到 VPS。安装器使用 Ubuntu 软件源中的 wireguard、qrencode 和 microsocks（需启用 universe）。在云防火墙放行入站 UDP 51820，SOCKS5 端口只供隧道内使用。

```bash
cd ~/vps_ubuntu
sudo bash bin/wireguard-install.sh 你的VPS公网IPv4
sudo wgvps-users list
```

安装后有 25 个已启用的用户（user01 至 user25），默认全局模式。每个用户有独立的 IPv4、IPv6、密钥对和预共享密钥。一份配置分配给一台同时在线的设备。旧版安装请填原 Endpoint；安装器校验原来的单 peer 与客户端是否匹配，并将其保留为 user01，原设备可继续连接。重复安装会保留已有用户状态。

## 分发配置

### 内网 Web 管理与自助领取

已有 25 人版本的 VPS 只需上传新版 `bin/` 与 `systemd/`，执行 Web 安装器。下例的 `192.168.50.10` 替换为 VPS 上实际配置的内网网卡 IPv4。服务监听该地址的 HTTPS 8443，并校验连接来源属于同一网卡子网。

```bash
sudo bash bin/wireguard-web-install.sh 192.168.50.10
sudo cat /etc/wgvps-web/password
```

1. 从已验证的 SSH 连接获取 **公有 CA 证书** `/etc/wgvps-web/ca.crt`，通过可信渠道在访问设备上安装并信任。保管好服务器上的 `ca.key`。站点证书有效期一年，到期前重跑 Web 安装器续签，原 CA 和管理密码沿用。
2. 管理员打开 `https://192.168.50.10:8443/admin`，用 `admin` 和上述密码登录。选择一个已分配给该设备的用户，点击“创建分发链接”，将链接私发给使用者。管理页同时支持启用和禁用现有名额。
3. 使用者在同一可达内网打开链接并点击“领取两份配置”，分别下载或使用另一台设备扫描页面上的二维码。手机可直接选择 WireGuard 的“从文件导入”。领取页无须管理员密码。
4. 分发链接有效期 10 分钟，成功领取一次即失效。重复签发、禁用账号或轮换密钥会撤销该用户待领取的链接。关闭领取结果页前保存两份配置；未保存可请管理员重新签发。

初次入网的设备需要先能访问分发页。如果 Web 安装器绑定的是 WireGuard 地址 `10.66.77.1`，新手机还没有隧道，可由已入网的管理员在浏览器打开领取结果，让新手机扫描两份二维码。VPC 私网地址同样需要实际的内网路由。若有防火墙，应仅允许相应内网来源访问 TCP 8443。停止 Web 服务可运行 `sudo systemctl disable --now wgvps-web`。

### 命令行分发

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

**由使用者切换**：同时导入 `user02-global.conf` 和 `user02-proxy.conf`。切换时先停用当前隧道，再启用目标隧道，无需联系管理员。两份配置属于同一设备，共用一个 peer 和地址。全局模式使用默认路由；代理模式需要在目标应用内指定 SOCKS5，应用的代理开关由使用者控制。服务端的 `mode` 命令仅设定常规导出的默认模式。

Web 领取页会同时生成两份配置，也可以在命令行独立导出：

```bash
(umask 077 && sudo wgvps-users export user02 --profile-mode global > user02-global.conf)
(umask 077 && sudo wgvps-users export user02 --profile-mode proxy > user02-proxy.conf)
```

轮换密钥后两份配置都需要重新领取。代理服务提供 TCP CONNECT；需要 UDP 应用经过 VPS 时选全局。全局模式需要 VPS 有 IPv6 出口才能访问 IPv6 站点。

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
