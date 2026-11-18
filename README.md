# Ubuntu 22.04 双版本代理服务部署工程（SSR + Shadowsocks-Rust）

版本：2.0.0 | 目标系统：Ubuntu Server 22.04 LTS | 管理方式：systemd

## 1. 工程定位与协议边界

本工程提供两个互不依赖的服务实例：

- **SSR 兼容服务**：Python SSR 服务端，目标是延续旧 SSR 客户端的连接参数（method / protocol / obfs）。SSR 上游代码较旧，Python 3 兼容性取决于选定分支/补丁；安装器会做语法和启动检查，不能保证所有旧协议组合均可运行。SSR 与现代 SS 并非同一协议。
- **现代 SS 服务**：官方 `shadowsocks-rust` 的 `ssserver`，安装固定版本 v1.25.0 的官方发布二进制。只支持 Shadowsocks 协议，不支持 SSR 的 `auth_*` 协议或 SSR 混淆。

两服务默认端口分别为 SSR 8388、Rust 8389。可以只装其中一个，也可以都装。两套服务各自独立配置、systemd unit、运行用户及管理命令。

## 2. 来源、版本与风险说明

- SSR 源码默认来自 `https://github.com/shadowsocksrr/shadowsocksr.git` 的 `manyuser` 分支（与原脚本使用的多用户分支方向一致）。这是历史项目，不应视为仍在积极维护的现代实现。
- Shadowsocks-Rust 固定版本 v1.25.0，官方发布说明与二进制资产见 `https://github.com/shadowsocks/shadowsocks-rust/releases`。
- v1.25.0 发布说明要求 MSRV Rust 1.91（这是源码构建要求）；本工程下载官方预编译二进制，不在目标机上编译 Rust。
- 上游二进制在安装时从 GitHub 下载。安装器校验 GitHub Release API 提供的 SHA256 sidecar（若该资产缺失则停止安装，不降级为无校验安装）。
- 本项目不内置第三方服务端二进制或源码。部署前请自行审查上游许可证、发布资产和代码。
- 本工程只完成静态脚本/配置检查，未在真实 Ubuntu 22.04 VPS 上完成端到端客户端验收。务必按 `docs/ACCEPTANCE.md` 执行实机测试。

### WireGuard 客户管理与 Windows 下载

**首次安装**　在 Ubuntu 22.04 VPS 的项目根目录执行以下命令。将示例公网 IP 换成自己的 VPS 地址，将 `3` 换成初始客户数（1–253，省略时创建 1 个）。在云防火墙放行入站 UDP 51820。

```bash
sudo bash bin/wireguard-install.sh 203.0.113.10 3
sudo bash bin/wireguard-web-install.sh 10.66.77.1
sudo cat /etc/wgvps-web/password
```

**从旧版升级**　把同一版本的 `bin/` 和 `systemd/` 上传到 VPS，在项目根目录重跑上面的 **Web 安装命令**。它会同步更新管理页、用户管理器和 sudo 权限，并重启 Web 服务。已有 25 人版保留全部客户、地址、密钥和启停状态。原来绑定其他内网地址的部署，请传入原地址。

**Windows 首次登录**　通过可信 SSH/SFTP 取回管理员自己的配置（首次安装可取 `/etc/wireguard/windows-vps.conf`）及公有 CA 证书 `/etc/wgvps-web/ca.crt`。在 Windows 的 WireGuard 中导入并启用隧道，将 CA 证书导入当前用户的“受信任的根证书颁发机构”。打开 [WireGuard 管理页](https://10.66.77.1:8443/admin)，使用 `admin` 和上面查到的密码登录。升级后已打开的旧页面按 **Ctrl + F5** 刷新。

| 要做的事 | 管理页操作与结果 |
|---|---|
| 增加客户 | 填写“新增客户名称”，点击“新增客户”。系统分配独立编号、地址和密钥，立即启用。名称可用中文、字母、数字、空格、短横线和下划线，最多 40 字，不能重名。 |
| 修改名称 | 选中客户，填写“新名称”，点击“保存名称”。列表显示名称与固定编号，例如“上海办公室（user26）”。原配置继续有效。 |
| 下载到 Windows | 选择已启用客户 → **生成配置并分发** → 点击对应的 `.conf` 下载按钮。文件保存到浏览器下载目录或所选位置。全局与代理文件按固定编号命名，例如 `user26-global.conf`、`user26-proxy.conf`。在 WireGuard 中从文件导入，同一设备每次启用一份。 |
| 批量下载或手机导入 | **下载全部配置 ZIP** 会按编号打包所有已启用客户，每人两份文件。按人分发自己的文件。手机也可在分发页展开对应二维码扫码导入。 |
| 暂停、删除或轮换密钥 | 暂停使用选“禁用用户”，恢复选“启用用户”。永久移除时先禁用，再选“删除已禁用客户…”并确认。轮换密钥后需重新分发配置。保留当前用于管理的隧道，或先切换到另一条可用连接。 |

当前 IPv4 网段最多容纳 **253 个客户**，禁用的客户仍保留地址，删除后释放地址。命令行可运行 `sudo wgvps-users list` 核对编号、状态、模式与名称。代理模式设置和一次性领取链接见 [WireGuard 用户管理](docs/WIREGUARD.md)。

## 3. 快速开始

```bash
cd ~/vps_ubuntu

# 统一 文件的换行格式
sed -i 's/\r$//' \
  bin/ssr-admin.py bin/admin-install.sh \
  bin/ssr_paths.py bin/ssr_backend.py \
  systemd/ssr-admin.service

sudo bash manage.sh admin-install &&
sudo systemctl restart ssr &&
sudo bash manage.sh admin
```

交互菜单：
1. 安装 SSR
2. 安装 Shadowsocks-Rust
3. 安装双版本
4. 运行环境检查
5. 退出

安装成功后：

```bash
sudo ./manage.sh status
sudo ./manage.sh rust status
sudo ./manage.sh ssr logs
sudo ./manage.sh check
```

也可以分别运行：

```bash
sudo ./bin/ssr-install.sh
sudo ./bin/rust-install.sh
```

## 4. 目录和系统路径

| 组件 | 程序目录 | 配置 | systemd |
|---|---|---|---|
| SSR | `/opt/ssr` | `/etc/ssr/config.json` | `ssr.service` |
| Rust SS | `/opt/shadowsocks-rust` | `/etc/shadowsocks-rust/config.json` | `shadowsocks-rust.service` |

运行用户分别为 `ssr` 和 `ssrust`，均不允许交互登录。配置文件权限为 0640，所有者 root，所属组为对应服务组（仅服务进程可读）。

## 5. 防火墙和云安全组

安装器不会擅自覆盖 UFW、iptables 或 nftables 规则。部署后按实际启用的服务端口，分别开放 TCP 和 UDP；并在云厂商安全组中配置相同规则。

例如只部署默认双服务：

```bash
sudo ufw allow 8388/tcp
sudo ufw allow 8388/udp
sudo ufw allow 8389/tcp
sudo ufw allow 8389/udp
sudo ufw status verbose
```

若系统未使用 UFW，不要为了执行示例而盲目启用 UFW；应按现有防火墙管理方式放行端口。

## 6. 管理

```bash
sudo ./manage.sh status
sudo ./manage.sh ssr start|stop|restart|status|logs
sudo ./manage.sh rust start|stop|restart|status|logs
sudo ./manage.sh check
sudo ./manage.sh uninstall ssr
sudo ./manage.sh uninstall rust
```

配置修改后分别重启对应服务：

```bash
sudo systemctl restart ssr
sudo systemctl restart shadowsocks-rust
```

## 7. 更新策略

Rust 更新当前采用受控人工升级流程；`bin/rust-update.sh` 是提示/保护入口，不会自动替换正在运行的二进制。先备份配置和旧二进制，再下载目标版本官方 release、校验 SHA256、替换并重启。正式生产环境建议先在测试机验证，再升级生产机。

SSR 不提供盲目自动更新。由于上游长期缺少活跃维护，更新前应检查 commit、变更和 Python 兼容性，并在维护窗口备份后手工更新。

## 8. 安全基线

- 不使用 `--no-check-certificate`。
- 不向公网暴露本机管理接口；Rust 服务仅监听代理端口。
- 不将密码写入命令行历史；配置文件权限限制为 root 可读写。
- 不覆盖已有 `/etc/ssr`、`/etc/shadowsocks-rust` 或 `/opt` 目录；安装器检测到冲突会退出。
- 基础代理安装不改动 SSH、防火墙、内核或 BBR；管理器仅在显式操作时修改其自有防火墙链和 BBR 配置。
- 日志可能包含客户端 IP 等元数据，按最小留存原则管理。

## 9. 验收入口

请按 `docs/DEPLOYMENT.md` 部署，按 `docs/TEST_PLAN.md` 测试，按 `docs/ACCEPTANCE.md` 签署验收。测试脚本 `tests/smoke-test.sh` 只做服务状态、配置、端口监听和 systemd unit 的本机检查；真实客户端握手必须另行验证。

## 10. Web / 终端账号管理

若需要 Windows 全局 TCP/UDP VPN，可独立部署 WireGuard，见 [docs/WIREGUARD.md](docs/WIREGUARD.md)。

```bash
sudo bash manage.sh admin-install  # 先安装 SSR
sudo systemctl restart ssr       # 让后端适配生效
sudo bash manage.sh admin        # 终端交互菜单
```

支持端口账号增删、独立限速、协议设备限制、当前 TCP IP、连接链接和本地二维码、单/多端口切换、BBR 启用/恢复、SMTP 与 BT/PT 出口封禁。Web 通过 SSH 隧道访问，安装器创建开机启动服务和独立管理令牌。

**范围说明**：限速与设备限制要求单 worker，启用这些限制的账号仅提供 TCP；设备限制目前支持 auth_sha1_v4，按客户端标识统计。BT/PT 为端口和明文特征拦截，不保证识别加密流量。锐速提供内核/架构/SHA256 校验后的本地包安装入口，尚无经验证兼容 Ubuntu 22.04 的内置安装包。

安装、Web 访问、完整命令、配置回退和锐速接入说明见 [docs/ADMIN.md](docs/ADMIN.md)。自动测试与实机验收见 [docs/TEST_PLAN.md](docs/TEST_PLAN.md)。
