# 专用管理隧道与 Agent
在既有安装上先记录 sudo wgvps-users list、sudo wg show wgvps peers 与旧 /admin 可用性。确认基线兼容后再执行下列步骤。无需运行旧安装脚本。默认规划 wgportal 独立接口，VPS 10.203.91.1/30、本地 10.203.91.2/30、UDP 51821、Agent TCP 9443。先在两端核对路由、端口与 VPN 策略；可用 --network 和 --port 更换。两端 AllowedIPs 仅含对端 /32，无默认路由、NAT 和转发 hooks。

## 在本地生成一条管理连接
在 wireguard-portal 目录中运行（需 Python 与 cryptography>=41；可用后端虚拟环境）。输出目录必须是新的，且仅当前管理员可读。

```bash
python scripts/management-link.py 192.0.2.10 secrets/link1
```

将示例 IPv4 换成实际 VPS 公网地址。生成器分别生成两端 WireGuard 密钥、一条连接独用的 TLS CA、一年有效期的 serverAuth 和 clientAuth 证书。CA 私钥未保存。将 link1 根目录下 ca.crt、client.crt、client.key 复制到 secrets/agents/10.203.91.1/。用受保护的 SSH 文件传输仅复制 link1/vps 到 VPS 管理员的私有目录。不要将整个 link1 上传。私密传输和配置完成后按本地密钥保管策略归档。

```bash
mkdir -p secrets/agents/10.203.91.1
cp secrets/link1/{ca.crt,client.crt,client.key} secrets/agents/10.203.91.1/
chmod 600 secrets/agents/10.203.91.1/client.key
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force secrets/agents/10.203.91.1
Copy-Item secrets/link1/ca.crt,secrets/link1/client.crt,secrets/link1/client.key secrets/agents/10.203.91.1/
```

本地 Windows 用 WireGuard 客户端导入 link1/wgportal.conf 并启用；Linux 首次安装独立接口：

```bash
sudo test ! -e /etc/wireguard/wgportal.conf && sudo install -m 600 secrets/link1/wgportal.conf /etc/wireguard/wgportal.conf
sudo systemctl enable --now wg-quick@wgportal
```

## VPS 上安装
从 VPS 的完整仓库根目录执行，参数指向刚上传的 vps 子目录。脚本检查冲突、要求确认，只启动独立接口。确认云安全组和主机 INPUT 策略允许本地出口到管理 UDP 端口；如需修改，应由网络管理员单独批准执行。9443 只允许从 wgportal 接口的管理客户端 /32 访问。无需开放公网 TCP 9443。不要对生产接口使用 wg-quick down。

```bash
sudo bash wireguard-portal/deploy/vps/configure-link.sh /root/portal-upload/vps
sudo bash wireguard-portal/deploy/vps/wireguard-portal-agent-install.sh
sudo systemctl status wg-portal-agent --no-pager
sudo wg show wgportal latest-handshakes
```

安装器新建 wg-portal 系统用户，仅能无参数 sudo 固定 bridge，安装 root 所有的适配代码与旧管理器库副本。Agent 读取独立 network、服务证书和客户端 CA，来源及客户端证书均需匹配。生产升级前核对本机旧管理器是否有自定义字段或 hooks。

## 从本地容器验证
```bash
docker compose exec api python -c "from app.remote import remote; print(remote({'address':'10.203.91.1'},'health'))"
```
期望 version=1。然后在“VPS 监控”添加节点，点击“读取实时状态”。Windows Docker Desktop 的容器须能经宿主 WireGuard 路由到 VPS；用此命令检查容器实际路径。握手、管理 IP、SAN、系统时间或 CA 出错时应修复配置，保持 TLS 验证启用。

若本地没有 Python 依赖，可用已安装的后端容器生成凭据（将示例地址替换为 VPS 公网 IPv4）。Linux 从本地当前账号运行主文的 Python 命令，可让生成文件直接归该账号所有。

```bash
docker compose run --rm --no-deps -v "./secrets:/output" -v "./scripts:/scripts:ro" api python /scripts/management-link.py 192.0.2.10 /output/link1
```
