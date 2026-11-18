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

#### 客户表格、分组和批量操作

| 页面 | 操作 |
|---|---|
| 客户管理 `/admin` | 输入名称，选择可选分组后点 **新增客户**。每行对应一台设备。点击 **管理** 打开右侧详情，可改名、换组、启停、签发一次性领取链接、下载配置或查看二维码。 |
| 连接监控 `/admin/status` | 查看启用状态、最近握手、Endpoint 和服务器收发累计字节。点击列头切换升序或降序，IPv4、客户编号和流量按数值排序。 |
| 分组管理 `/admin/groups` | 创建或改名，查看成员数与在线数。先移出成员再删除空组。“未分组”是默认归属。组名和客户名支持中文、字母、数字、空格、下划线及短横线，最多 40 字。 |
| 操作日志 `/admin/logs` | 最近 200 条审计记录，时间为 UTC，包括来源、操作、对象、结果和脱敏原因。源文件位于 `/etc/wireguard/wgvps-audit.jsonl`，root 私有，达到 1 MiB 后在下次写入时轮转并保留一份旧文件。 |

**查找与翻页。** 输入客户名称、编号、隧道 IPv4 或组名，组合连接状态、启用状态及分组筛选。每页可选 20、50 或 100 条。点击列头排序，点击“查询 / 刷新”更新当前视图，点击“重置”恢复默认。顶部五项统计对应全部客户，底部“匹配”对应当前筛选。窄屏可在表格内横向滑动。

**批量管理。** 勾选行或用表头复选框选中当前页，可跨页累计选择。检查“已选”数量后批量启用、禁用、移组或导出 ZIP。变更查询条件时重新选择。批量禁用需确认。若选中的客户已被另一位管理员删除，启停或移组会报告失效编号并处理其余有效对象。导出时如有禁用或消失的客户，会提示原因，调整选择后重新导出。

**配置分发与 Windows 下载。** 管理员通过 HTTPS 打开客户详情，点 **配置下载与二维码**，再点全局或代理的 `.conf` 附件按钮。文件以固定编号命名，例如 `user02-global.conf`，由浏览器保存到下载目录或自选位置。也可在客户表格点击 **导出所选 ZIP** 或 **下载全部配置 ZIP**。在 Windows 解压后，从 WireGuard 选择“从文件导入隧道”；手机从管理员屏幕扫描对应模式的二维码。同一设备每次启用一份配置。文件、二维码和 ZIP 均含私钥，按客户单独分发。

**启停与轮换。** 禁用会撤销该 Peer 并清除未用领取码，重新启用可继续使用原配置。轮换密钥需二次确认，随后须重新下载并分发两种模式的配置。永久删除须先禁用，再确认删除。操作管理隧道所属客户前先切换到另一条管理连接。

#### 连接监控与自动刷新

启用状态反映管理员的设置。连接状态依据服务器最近握手估算，默认 180 秒内为在线，超时为离线；当前 Peer 的握手值为零时显示“尚无握手”。运行数据不可用时显示“状态未知”或字段缺失标记。握手不能证明端到端业务连通。Endpoint 是服务器看到的远端地址，收发均为**服务器视角的累计量**，按 KiB、MiB 等单位显示。接口重建或重新添加 Peer 后计数可能重置。

客户页和监控页默认每 30 秒局部刷新，保留筛选、排序和页码。后台标签、正在操作或编辑的视图会暂停自动刷新；手工查询可立即更新。读取失败时查看页面提示和最后采样时间。修改在线窗口（秒，1–86400）后在下一次查询生效：

```bash
printf '%s\n' 180 | sudo tee /etc/wireguard/wgvps-online-window >/dev/null
sudo wgvps-users snapshot
```

#### 数据兼容、备份及代码回滚

客户数据沿用 `/etc/wireguard/wgvps-users.json`。旧客户读取时使用“未分组”，历史创建时间未知；分组 ID 与稳定客户编号关联。改名或移组只更新管理元数据。编辑器使用原有文件锁、原子替换及 pending 恢复机制。运行中的接口先解析候选配置并同步，成功后替换磁盘配置。已安装环境同步失败会尝试恢复上一个已提交版本；回滚失败时保留恢复记录，下次管理命令会重试。已有部署运行 Web 升级脚本时无需重新运行 WireGuard 初始化。现有 IPv4 地址池最多容纳 253 个客户，禁用继续保留地址，删除释放地址。

已有 Web 部署升级前，在 VPS 上执行以下备份。升级验收期间暂停其他管理写操作。归档含私钥、CA 及管理密码，仅由 root 持有。

```bash
sudo bash <<'BACKUP'
set -euo pipefail
umask 077
backup=$(mktemp -d /root/wgvps-backup.XXXXXXXX)
flock /etc/wireguard/.wgvps-users.lock tar -C / -czf "$backup/data.tgz" etc/wireguard etc/wgvps-web
tar -C / -czf "$backup/web.tgz" usr/local/lib/wgvps-web usr/local/sbin/wgvps-users etc/sudoers.d/wgvps-web etc/systemd/system/wgvps-web.service
tar -tzf "$backup/data.tgz" >/dev/null
tar -tzf "$backup/web.tgz" >/dev/null
echo "$backup"
BACKUP
sudo bash bin/wireguard-web-install.sh 10.66.77.1
sudo systemctl is-active wgvps-web
```

若升级验收失败且尚未开放新写入，可回退应用及权限文件。把第一行换成上一步输出的目录。此流程保留当前客户数据、TLS 证书与 CA。

```bash
backup=/root/wgvps-backup.XXXXXXXX
sudo tar -tzf "$backup/web.tgz" >/dev/null &&
sudo systemctl stop wgvps-web &&
sudo tar -C / -xzf "$backup/web.tgz" &&
sudo visudo -cf /etc/sudoers.d/wgvps-web &&
sudo systemctl daemon-reload &&
sudo systemctl start wgvps-web
```

若升级后已有客户增删或轮换密钥，直接恢复旧数据会撤销这些操作。数据恢复应在维护窗口核对归档、当前状态及 pending 文件后协调进行。

#### 排查与验收

```bash
sudo systemctl status wgvps-web wg-quick@wgvps wgvps-proxy
sudo journalctl -u wgvps-web -n 50 --no-pager
sudo wg show wgvps latest-handshakes
sudo wg show wgvps endpoints
sudo wg show wgvps transfer
sudo wgvps-users list
sudo wgvps-users snapshot
python3 -m unittest discover -s tests
```

| 验收项目 | 在测试 VPS / Windows 上操作 | 预期结果 |
|---|---|---|
| 页面和下载 | 用具备管理入口访问权限的设备连入隧道，登录 HTTPS 后用两个测试账号下载单文件和 ZIP，再在 Windows 导入；手机扫描其中一份二维码。 | 浏览器保存正确编号和模式的文件，二维码与对应配置连到同一 Peer。若旧表单返回“请重新打开管理页”，重新打开管理入口并按 Ctrl + F5。 |
| 分组和批量隔离 | 创建两个测试组，选两人移组，只禁用其中一人；同时用另一台未选设备持续访问测试业务。 | 成员数、在线数和审计记录与操作一致，未选客户继续工作；有成员的组无法删除。 |
| 握手与流量 | 测试设备传输数据，对照上面的三条 wg 命令，等待下一次刷新，再停用客户端并等待超过在线窗口。 | IP、Endpoint、收发方向和握手时间一致，在线状态随窗口变化。 |
| 禁用、启用、轮换、删除 | 在独立测试账号上依次执行，分别用旧配置和新配置连接。 | 禁用后旧 Peer 消失，启用后可恢复；轮换后原密钥无法建立新握手，新配置可用；删除后不会在重启时重新出现。 |
| 重启与升级 | 在测试机记录客户编号、地址及握手，重新执行 Web 升级脚本，重启 Web 服务，维护窗口再重启测试 VPS。 | 现有配置可继续连接，分组、编号、地址、客户数量及权限保留；元数据操作不触发隧道重启。 |

默认网关的服务单元为 `10.66.77.3/32` 提供定向管理端口放行。若使用限制性 INPUT 策略，请从获准的管理设备登录；首次安装示例创建的 `user02` 对应该地址。页面超时先核对来源地址、隧道路由与防火墙。状态读取异常时核对接口名、服务权限以及在线窗口文件中的整数。更多代理模式和首次分发操作见 [WireGuard 用户管理](docs/WIREGUARD.md)。

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
