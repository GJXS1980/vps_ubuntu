# 安全边界
- 本地密码使用 argon2-cffi PasswordHasher 的 Argon2id。随机会话在登录时重新签发，数据库仅存令牌摘要；Cookie 设置 Secure、HttpOnly、SameSite=Strict，八小时过期。密码修改、重置和停用撤销会话。管理员使用 TOTP，禁止重复使用同一时间片登录。
- 登录失败按账号和入口来源计数；Nginx 对公开 API 限流，重写客户端地址，忽略外部转发头。受信 Host 与精确 Origin、会话 CSRF token 共同保护浏览器请求。前端只用文本绑定，入口设 CSP、frame-ancestors、nosniff 与 HSTS。
- 配置领取同时校验本地账号、归属、设备状态、当前指纹，Agent 在旧系统同一锁内复查绑定、enabled 与完整 SHA-256 公钥指纹。POST 返回 no-store 二进制，二维码在内存生成。密钥轮换后旧指纹不能导出；用户先前已保存的文件由远端换钥失效。
- 两个 HTTPS 系统使用独立证书。管理链路还检查来源地址和 mTLS 客户端证书。不从 Web 接受自定义 URL、命令或文件路径；地址必须位于 RFC1918。服务端适配器只接受固定动作；sudoers 仅授予无参数 bridge，bridge 再校验设备 UUID、Peer、归属和指纹。未授权历史 Peer 不自动变更。旧 .2/.3 地址不可自动分配或接管。
- root bridge 检查生产状态/配置文件属主、权限和符号链接；复用旧 flock、pending 恢复、wg syncconf 与原子替换。操作回执仅含目标、指纹、操作签名和时间。应用不记录配置、请求体、Cookie 或密码，业务审计只保留动作和目标。
- 磁盘上的 VPS 原始密钥、客户端已保存的配置、本地 MFA 文件、客户端 TLS 私钥和备份解密密钥都需要操作系统访问控制。数据库快照可以恢复账号，应只分发加密备份；backup.key 单独离线保管。测试产生的虚构密钥仅用于临时目录。

