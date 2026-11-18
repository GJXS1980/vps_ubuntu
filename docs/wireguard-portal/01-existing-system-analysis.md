# 现有系统审计
基线 e5ff00b。安装入口 bin/wireguard-install.sh 限 Ubuntu 22.04，验证公网 IPv4、端口、路由、已有文件、IPv6 NAT 后安装 wg、iptables、microsocks 等依赖，写 sysctl、双栈转发及 NAT hooks，初始化管理器，启动 wg-quick@wgvps 与 wgvps-proxy。已有安装走 init 校验或恢复；单客户端迁移要求原密钥、公钥、PSK、Endpoint、地址一致，保留 user01。

## 地址和密钥
wgvps 使用 UDP 51820、10.66.77.1/24 和 fd42:66:77::1/64。初始 userNN 使用编号加一；新增先找 2 至 254 的首个空闲 host，编号从 last_id 递增。禁用仍占地址，删除释放地址。容量 253。IPv6 主机号按十六进制。wg genkey/pubkey/genpsk 生成密钥。/etc/wireguard 下 wgvps-users.json 含客户端密钥及服务端 base；wgvps.conf、windows-vps.conf、事务临时文件同样敏感。初始目录 0700，CLI umask 0077。

## CLI 合约
以下省略 wgvps-users 前缀。常规修改成功无 stdout；CustomerError 退出 3，其他错误非零。除下列显式 stdin 输入外均由 argv 传参。

|调用|输入和输出|
|---|---|
|init ENDPOINT [--count N]|默认 1，最大 253；迁移、重建或恢复|
|list / status|逐行编号、enabled/disabled、模式、名称 / JSON 行数组 name,label,status,address,age|
|snapshot / audit|JSON 对象 rows/groups/window/time/warning，含流量、端点、指纹 / 最近 200 条日志数组|
|add / add-group|stdin 名称 / JSON label,group；输出新编号|
|rename USER|stdin 新名称|
|enable / disable / rotate USER|启停或换钥；禁用与轮换清领取码|
|delete USER|只删已禁用记录|
|mode USER global或proxy|修改默认导出模式|
|issue USER / redeem|输出 600 秒一次性码 / stdin 领取码，输出单个 bundle|
|bundle USER / bundles|单个对象 name,profiles 或全部启用客户的对象数组|
|export / qr USER [--profile-mode global或proxy]|配置原文 / ANSIUTF8 二维码|
|group-create / group-rename / group-delete|stdin JSON label 或 group,label 或 group，仅可删空组|
|batch-enable / batch-disable / batch-group|stdin JSON ids，分组时加 group；输出 count,errors，部分失败也可能退出 0|
|batch-export|stdin JSON ids，输出 bundle 数组，缺失或禁用即拒绝|

## 写入和竞争
每次 CLI（含查询）独占 .wgvps-users.lock，先恢复 wgvps-pending.json。apply_state 先写 pending，活动接口经 wg-quick strip 和 wg syncconf，再原子替换 conf、更新旧客户端文件、将 pending 移为 state。异常时尝试回滚。组和名称修改直接原子写 state。接口未运行时只更新磁盘，因此状态持久化不等于有握手。跨多次 CLI 的“检查再导出”会与旧页面的轮换竞争，必须在同一锁内检查指纹并生成结果。旧的 add 没有幂等参数，名称可改，不能以显示名确认归属。删除后编号单调增加，但地址可复用。

## Web 与权限
wireguard-web-install.sh 只接受已绑定的 RFC1918 地址，单独 CA 和 HTTPS；gunicorn 以 wgvps-web 运行，经受限 sudo 调 CLI。wgvps-web.service 默认 10.66.77.1:8443，并插入来自 .3 的 INPUT 规则。Web 检查来源网段、Host；/admin 系列使用 Basic 管理员密码和 HMAC 表单 CSRF。/、/admin、/admin/status、/admin/groups、/admin/logs 返回 HTML；JS 获取局部 HTML，没有面向用户的账号 API。issue 只持久化码摘要；redeem 在锁内消费后同时返回两个配置，global 全路由带 DNS，proxy 只路由到 .1，通过 SOCKS5 1080。两份配置共用凭据。Agent 需要独立身份、管理接口及单一受限特权入口；不应继承旧 Web 的 bundles 或任意导出权限。特别注意旧防火墙按地址授权，自动分配到 .3 的普通用户可能到达旧登录页。

## 目录与产权核对
平台创建的 Peer 会在原 JSON 记录中增加 portal_device，并以 portal_operations 字段保存请求回执。旧 CLI 的重命名、分组和启停在当前版本保留其他字段。独立管理链路不占 wgvps 的业务客户配额。新平台保留 user01/user02 编号和 .2/.3 地址，平台创建的首个 Peer 最低使用 user03，具体编号和地址仍由服务器分配。旧编号判断只用于兼容既有无 host 字段的记录。

旧服务使用 /etc/wgvps-web/password 与 systemd LoadCredential，旧 Web 自带内网 TLS 信任根；新门户使用独立 CA 和客户端证书。旧领取链接放在 URL fragment，页面 POST 一次性码并消费，管理员页面另有批量导出能力。新平台无需读取旧密码或代理旧管理页面。
