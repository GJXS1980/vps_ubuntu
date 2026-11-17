# Windows 全隧道 VPN

适用于 Ubuntu 22.04 VPS 与 Windows 官方 WireGuard 客户端。与 SSH SOCKS 不同，虚拟网卡可承载 TCP/UDP，不要求每个应用配置代理。使用单 peer 的 `AllowedIPs = 0.0.0.0/0, ::/0` 与配置中的 DNS，保留官方 Windows 客户端的阻止隧道外流量设置。隧道服务本身、回环与必要网络维护流量存在官方例外；不应将其描述为每一个网络包都走 VPN。

## 安装

先将更新后的 `bin/wireguard-install.sh` 上传到 VPS 项目目录，再执行：

```bash
cd ~/vps_ubuntu
sudo bash bin/wireguard-install.sh 167.179.99.196
```

脚本创建 `wgvps` 接口、UDP 51820、独立配置和带 `wgvps` 注释的 INPUT/FORWARD/NAT 规则。新增 IPv4/IPv6 转发与 IPv6 RA 设置保存在 `/etc/sysctl.d/90-ssr-wireguard.conf`，原运行值记录在 `/etc/wireguard/wgvps-forwarding-before.txt`。现有 SSR unit 和账号不修改。不要重复安装或同时在多台设备上使用同一份客户端密钥。

脚本不会修改 Vultr 云防火墙：在关联的云防火墙规则中允许入站 UDP 51820。现有防火墙中的其他规则不清空，但新增的转发允许规则会插入前部。若使用其他 nftables 基础链、策略路由或防火墙重载，仍需检查冲突；重载防火墙后可重启 `wg-quick@wgvps` 恢复自有规则。此 VPN 转发不受 SSR 管理器的 ssr UID 出口封禁规则约束。

在 Windows PowerShell 下载客户端配置：

```powershell
scp root@167.179.99.196:/etc/wireguard/windows-vps.conf "$env:USERPROFILE\Downloads\windows-vps.conf"
```

从 https://www.wireguard.com/install/ 安装 Windows 官方客户端，选择“从文件导入隧道”，选择下载的文件。先关闭 SSR 的系统代理、浏览器自定义代理和其他 VPN，再激活 WireGuard，避免代理套代理。配置含客户端私钥和预共享密钥，不要贴到聊天或公开存储。

## IPv6 与性能

IPv4 和 IPv6 都路由至隧道。服务器使用 IPv4 NAT 和 IPv6 NAT66；只有 VPS 有可用的 IPv6 出口，IPv6 网站才可通过隧道访问。没有 IPv6 出口时保留 `::/0` 阻止本地 IPv6 绕行，IPv4 TCP/UDP 仍可使用。隧道不能改善物理线路的基础 RTT，也不保证一定比 SSR/SSH 快；其 UDP 端口须能从客户端网络访问。

MTU 初始值为 1380。如果只有部分网站卡住或出现大包问题，需要在确认路径 MTU 后进一步调整，不能仅凭延迟就认定 MTU 有误。

## 验证与停止

客户端激活后，在 VPS 检查握手和双向字节数：

```bash
sudo wg show wgvps
```

在 Windows 检查出口（绕过旧的 HTTP/SOCKS 代理设置）：

```powershell
curl.exe --% -q --noproxy "*" --connect-timeout 10 --max-time 20 https://www.cloudflare.com/cdn-cgi/trace
```

应看到 `ip=167.179.99.196`。该测试只能验证出口，不代替全部 UDP 应用验收。可使用 `Resolve-DnsName example.com -Server 1.1.1.1 -DnsOnly` 测试 DNS，并观察 `wg show` 的收发计数；握手正常但打不开网页时检查转发/NAT、MTU 和防火墙。未握手先检查客户端日志、UDP 51820 放行、Endpoint 和密钥是否匹配。

停止客户端：在 Windows WireGuard 中停用隧道，恢复普通直连。服务器停止并取消开机启动：

```bash
sudo systemctl disable --now wg-quick@wgvps
```

正常停止会执行 PostDown 删除对应规则，不删除账号或密钥。系统转发设置为全局共享状态，停止服务不会擅自恢复这些值；若要移除转发持久配置，应先确认其他 VPN/容器不依赖它，再参考记录的原值恢复。安装失败不要删除现有 SSR 或盲目重跑；检查 `journalctl -u wg-quick@wgvps --no-pager`。启动钩子中途失败可能留下部分自有规则，应仅检查/移除带 wgvps 注释的规则。

本次只完成安装脚本静态检查，尚未在该 VPS 完成 WireGuard 握手、UDP 与吞吐验收。

参考：https://www.wireguard.com/quickstart/ 、https://ubuntu.com/server/docs/how-to/wireguard-vpn/vpn-as-the-default-gateway/ 、https://git.zx2c4.com/wireguard-windows/about/docs/netquirk.md 。
