# SSR Web 与终端管理

## 安装和访问

先按 README 安装 SSR，再在项目目录执行：

```bash
sudo bash manage.sh admin-install
sudo systemctl restart ssr
sudo cat /etc/ssr-admin/admin.env
```

安装器安装 Python 3、qrencode、iptables、iproute2、kmod 等依赖，将管理程序复制到 `/opt/ssr-admin`，校验并适配 `/opt/ssr/shadowsocks/server.py`，创建两个 systemd 服务。重复安装会拒绝覆盖；失败后先查看输出和现有文件，不能直接删除 SSR 配置重试。

本地电脑执行：

```bash
ssh -L 9080:127.0.0.1:9080 ubuntu@your-server
```

浏览器访问 `http://127.0.0.1:9080`，输入 admin.env 中 `SSR_ADMIN_TOKEN=` 后的值。管理器只监听回环地址，不需要开放公网管理端口。令牌允许修改账号及网络设置，保存在 root 专属文件中，页面不写入浏览器存储。不要将 admin.env 发给其他人。

终端菜单：

```bash
sudo bash manage.sh admin
# 安装后也可不依赖原项目目录：
sudo python3 /opt/ssr-admin/bin/ssr-admin.py menu
```

## 功能范围

| 功能 | 实现与边界 |
|---|---|
| 账号管理 | 一个监听端口对应一个账号；增删端口、生成密码、切换单/多端口。切换单端口前必须只保留一个账号 |
| 独立限速 | 每端口独立设置 `speed_limit_per_user`，单位 KiB/s（界面简写 KB/s），0 不限；TCP 上下行分别限速，不是双向总和 |
| 设备限制 | `auth_sha1_v4` 的活跃客户端标识计数；仅严格协议，拒绝 compatible、origin 等会绕过限制的协议。1–4096，0 恢复协议默认上限 64。约三分钟不活动后释放 |
| IPv4/IPv6 限额 | 适配补丁让同一端口的两类 TCP 监听共享限速器和客户端注册表；限速/设备限制都要求 workers=1 |
| UDP 边界 | **启用限速或设备限制的账号仅提供 TCP**，避免未受限的 UDP 绕过配额。两项均关闭后重启才恢复 UDP；客户端若需要 DNS，可配置 TCP DNS/DoH |
| 当前 IP | 按监听端口显示当前已建立的 TCP 对端 IP，去重并规范化 IPv4-mapped IPv6；不是设备身份，也不记录历史或 UDP |
| 分享 | 按账号实际协议、混淆和密码生成 SSR 链接；origin/plain 同时生成 SS 链接；IPv6 地址使用方括号 |
| 二维码 | qrencode 在本机生成；Web 显示 PNG，终端显示 ANSIUTF8；不使用外部二维码网站 |
| BBR | 检测和加载当前内核模块、设置 fq 默认队列与 bbr；保留原设置，支持恢复；不替换内核，不调整已有接口 qdisc |
| 锐速 | 受控本地安装包入口：核对完整内核版本、架构、SHA256 与 root 文件权限后执行；没有匹配安装包就停止，**不代表已验证 Ubuntu 22.04 可安装锐速** |
| 垃圾邮件 | 针对 ssr UID 出口封禁 TCP 25/465/587；合法 SMTP 同样会受影响，不是邮件内容过滤 |
| BT/PT | 拦截常见端口 6881–6999/51413 和单包明文特征；任意端口、加密、跨包及 HTTPS tracker 不能保证拦截，PT 使用同类机制 |

客户端标识可以被客户端实现影响；这不是不可伪造的物理设备认证。本版本管理 SSR，不改变 Shadowsocks-Rust 的账号配置。

## 常用命令

```bash
sudo bash manage.sh admin list
sudo bash manage.sh admin add --data '{"port":8390}'
sudo bash manage.sh admin speed --data '{"port":8390,"value":1024}'
sudo bash manage.sh admin devices --data '{"port":8390,"value":3}'
sudo bash manage.sh admin devices --data '{"port":8390,"value":0}'
sudo bash manage.sh admin ips
sudo bash manage.sh admin share --data '{"host":"your-server.example","terminal_qr":true}'
sudo bash manage.sh admin mode --data '{"value":"multi"}'
sudo bash manage.sh admin restart
sudo bash manage.sh admin bbr --data '{"action":"enable"}'
sudo bash manage.sh admin bbr --data '{"action":"status"}'
sudo bash manage.sh admin bbr --data '{"action":"disable"}'
sudo bash manage.sh admin firewall --data '{"action":"enable","feature":"all"}'
sudo bash manage.sh admin firewall --data '{"action":"disable","feature":"bt"}'
sudo bash manage.sh admin firewall --data '{"action":"status"}'
```

`feature` 可为 `smtp`、`bt` 或 `all`。设置密码建议使用菜单隐藏输入，或 `--data -` 从标准输入读取，避免密码进入 shell 历史。分享链接与二维码也包含密码。

账号配置在文件锁内更新，原子替换并保留原属主、权限；上一份配置保存到 `/etc/ssr/config.json.backup`，权限 0600。保存和重启分开，便于先审核再中断连接。新增端口仍需自行配置主机防火墙和云安全组。

手工回退上次账号配置（先确认备份内容，随后恢复原服务组权限）：

```bash
sudo install -o root -g ssr -m 0640 /etc/ssr/config.json.backup /etc/ssr/config.json
sudo systemctl restart ssr
```

## 后端适配与回退

安装器识别 manyuser `server.py` 的两处配置复制和 UDP 监听结构，在副本中进行 AST 语法校验后替换。未知源码结构会拒绝修改。补丁为每端口传递限速字段，合并 IPv4/IPv6 TCP 的状态，并关闭受限制账号的 UDP。它依赖上游 TCPRelay 的内部接口，因此更换 SSR 分支前必须实机复测。

源码原文件备份为 `/opt/ssr/shadowsocks/server.py.before-ssr-admin`。独立设置限速和设备限制前会检查适配标记，未适配时拒绝保存。单独安装适配：

```bash
sudo bash manage.sh admin backend-patch
sudo systemctl restart ssr
```

回退源码前先移除独立限制，或同时恢复适配前的配置，否则原上游可能忽略已配置的限速字段：

```bash
sudo systemctl stop ssr
sudo cp -p /opt/ssr/shadowsocks/server.py.before-ssr-admin /opt/ssr/shadowsocks/server.py
sudo systemctl start ssr
```

## 防火墙持久化

仅管理 filter 表中的 `SSR_ADMIN_EGRESS` 自有链和带 `ssr-admin` 注释的 OUTPUT 跳转；不清空全局表、不修改 INPUT/SSH 规则。每条拒绝规则都匹配 ssr 用户 UID。先测试 IPv4/IPv6 规则，再应用；某一族失败时恢复自有链的旧规则，政策文件仅成功后更新。两族的提交无法跨内核事务原子化，中途存在短暂窗口。

策略保存在 `/etc/ssr-admin/firewall.json`；`ssr-admin-firewall.service` 开机恢复，状态命令同时给出保存策略与实时链信息。若其他防火墙工具重载覆盖规则，请执行：

```bash
sudo systemctl restart ssr-admin-firewall
```

禁用规则使用 firewall disable，保留空链和跳转；不要仅停掉 oneshot 服务期待内核规则自动消失。服务必须使用独立的 ssr UID，不能以 root 运行代理。

## 锐速受控安装

目前未取得可以核实兼容当前 Ubuntu 22.04 内核的可信锐速包，因此不内置“下载即执行”的第三方地址。若供应商提供了匹配当前内核、架构和许可的安装脚本，由管理员审查后放入 root 专属目录，例如 `/opt/serverspeeder-vendor/install.sh`。脚本必须自行完成离线安装或校验其后续下载；本项目只校验该入口脚本。

创建 `/etc/ssr-admin/serverspeeder.json`（将示例值换为供应商实际参数，不能通过随意填写当前内核来绕过供应商兼容性要求）：

```json
{
  "kernel": "完整且经供应商验证的 uname -r 值",
  "architecture": "uname -m 值，例如 x86_64",
  "installer": "/opt/serverspeeder-vendor/install.sh",
  "sha256": "经可信渠道核对的安装脚本 SHA256"
}
```

manifest、安装脚本及其父目录须归 root 所有，不允许组或其他用户写入；不能使用符号链接。状态和一键执行：

```bash
sudo bash manage.sh admin ruisu --data '{"action":"status"}'
sudo bash manage.sh admin ruisu --data '{"action":"install"}'
```

此操作仅终端开放，不允许 Web 上传脚本或选择任意路径执行。BBR 与锐速不能同时启用；安装锐速前先关闭 BBR。锐速安装结束只表示供应商脚本成功退出，仍需按供应商文档检查模块、授权、吞吐与稳定性。

## 验证与更新

```bash
python3 -m unittest discover -s tests -p 'test_admin.py' -v
bash -n bin/admin-install.sh
sudo systemd-analyze verify systemd/ssr-admin.service systemd/ssr-admin-firewall.service
```

自动测试覆盖配置、独立限速、设备协议限制、分享/二维码输入、IPv4/IPv6 统计、适配状态共享、网络操作失败回退及 HTTP 认证。网络命令与 QR 编码器在单元测试中模拟，不代替真实 Linux 内核、扫码客户端或吞吐验收。必须按 TEST_PLAN 中的管理器验收场景在 Ubuntu VPS 执行。

更新管理程序前备份 `/opt/ssr-admin` 和 `/etc/ssr-admin`，停止 ssr-admin，复制新的 bin 文件与 templates/admin.html 后重启；不要覆盖 admin.env。源码适配补丁如果版本变化，先审核新旧差异，再在测试机升级。

参考：[SSR 多端口入口](https://github.com/shadowsocksrr/shadowsocksr/blob/manyuser/shadowsocks/server.py)、[auth_sha1_v4 客户端计数](https://github.com/shadowsocksrr/shadowsocksr/blob/manyuser/shadowsocks/obfsplugin/auth.py)、[BBR 官方说明](https://github.com/google/bbr/blob/master/Documentation/bbr-quick-start.md)、[Ubuntu iptables-restore 手册](https://manpages.ubuntu.com/manpages/jammy/man8/iptables-restore.8.html)。
