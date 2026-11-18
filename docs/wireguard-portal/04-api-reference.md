# API 合约
本地入口 /api，默认 https://localhost:8444。字段均为 JSON，除恢复接口直接接收加密字节。GET /openapi.json 提供本地 FastAPI 的机器可读架构（直接访问 API 服务时）；入口仅代理 /api。登录回包及 GET /api/me 提供 csrf，后续带 Cookie 的写操作须附 X-CSRF-Token。所有写操作还需发送与 PORTAL_ORIGIN 一致的 Origin。普通用户仅能领取自己的配置；业务管理员也需遵守领取归属检查。未特别注明的成功写操作返回 200，空结果为 JSON null。

|方法与路径（省略 /api）|权限|输入与成功输出|
|---|---|---|
|GET /health|公开|version、smtp；数据库不可用时不报健康|
|POST /register|公开|username,email,password,invite 可选；status,message|
|POST /login|公开|username,password，管理员另传 otp；签发 sid，返回 csrf|
|GET /me|登录|id,username,email,quota,status,verified,role,csrf|
|POST /logout、/revoke-sessions|登录|撤销当前或全部会话，删除 Cookie|
|POST /profile|登录|email；更换邮箱并清空验证状态与历史凭证|
|POST /password|登录|old,password；改密并撤销会话|
|POST /forgot|公开|email；已验证账号经邮件获取重置码|
|POST /reset|公开|code,password；消费重置码并撤销会话|
|POST /verification、/verify|登录|前者发送验证码；后者传 code 完成验证|
|GET /servers|登录|可选节点 id,name,checked,health；超级管理员另见管理 IP|
|GET /devices|登录|本人设备数组，含 server_name,peer,address,fingerprint,metrics,last_download；metrics 是采样 JSON 字符串|
|POST /devices|登录|label,server；返回 device,job。可带 32 位小写十六进制 Idempotency-Key，在用户范围重用相同申请结果|
|POST /devices/{device}/{mode}/{kind}|所有者|code 为设备当前公钥指纹；mode 为 global 或 proxy，kind 为 conf 或 qr。返回附件或 PNG，均 no-store|
|GET /admin/users|业务管理员及以上|可管理用户清单，无密码摘要与 MFA 种子|
|POST /admin/users/{user}|业务管理员及以上|status 为 active、disabled 或 pending，quota 为 1–253；只允许操作普通账号|
|GET /admin/devices|业务管理员及以上|跨用户设备元数据、当前分配和最近领取|
|POST /admin/devices/{device}/{action}|业务管理员及以上|enable、disable、rotate、delete；返回任务号；正常回收要求已停用。缺失或失败资源可在确认远端无关联 Peer 且无悬挂任务后仅释放本地配额|
|GET /admin/servers/{server}/peers|业务管理员及以上|实时 Agent inventory；device 为 null 表示外部资源|
|POST /admin/servers|超级管理员|name,address；仅 RFC1918 管理地址|
|POST /admin/adopt|超级管理员|server,user,label,peer,fingerprint；返回绑定任务|
|GET /admin/logs|业务管理员及以上|audit,downloads,jobs 各返回最近 500 条；底层记录仍在数据库|
|POST /admin/jobs/{key}/retry|业务管理员及以上|唤醒最新未完成任务，下次先核查远端回执|
|POST /admin/sync|业务管理员及以上|立即执行一轮节点对账，失败节点记录健康告警|
|GET /admin/settings、POST /admin/settings|超级管理员|registration 取 closed、invite、review、auto；quota 为新账号配额，写入需同时传两项|
|POST /admin/invite|业务管理员及以上|返回一次性 code，有效 30 分钟|
|POST /admin/backup|超级管理员|加密的 application/octet-stream|
|POST /admin/restore|超级管理员|加密原始字节，另需 X-Confirm-Restore=RESTORE、X-Admin-OTP；成功后全部会话失效|

常见错误为 400 凭证或参数不符，401 无有效登录，403 权限、CSRF、来源或状态受限，404 设备不可见，409 重复、状态冲突或远端拒绝，413 备份过大，422 字段错误，429 触发限流，502/503 远端或邮件服务不可用。响应 detail 不含配置或密码。Vue 的详情、搜索与分页使用上述清单，适用小规模部署。

## VPS Agent /v1
同一条专用管理连接的客户端证书及管理源 IP 是访问前提。HTTP 版本不匹配返回 409。Agent 操作不接受管理员 Basic 密码。

|路径|输入与输出|
|---|---|
|GET /health|version=1|
|GET /capacity|version、live、capacity、可分配 free|
|GET /peers|snapshot 原有字段，另含 version,live,capacity,free，rows 带完整 fingerprint 和 portal device UUID|
|GET /peers/{peer}|单个监控行，缺失 404|
|GET /results/{key}|操作回执或 JSON null；查询也在旧 CLI 锁内先恢复 pending|
|GET /audit|最近 200 次已提交变更的键及回执；拒绝事件由系统日志保留|
|POST /operations|严格动作和参数模型；未知字段拒绝|

变更必需 action,device,key（后两者为 32 位小写十六进制）。create 另需 label；adopt、enable、disable、rotate、delete 需 peer、完整 fingerprint。所有变更在同一锁内检查并持久化，回执含签名、动作、设备、Peer、时间；仍存在的 Peer 还含指纹、地址、是否启用。export 是只读操作，需 action,device,peer,fingerprint,mode，返回 config；不会创建第二个 Peer。Agent 不提供自定义命令、批量导出或旧管理密码接口。
