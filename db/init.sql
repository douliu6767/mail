-- 邮件账号管理数据库初始化（增强版）
CREATE TABLE IF NOT EXISTS mail_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    server TEXT NOT NULL,
    port INTEGER NOT NULL,
    protocol TEXT NOT NULL DEFAULT 'imap',
    ssl INTEGER NOT NULL DEFAULT 1,
    remarks TEXT DEFAULT '',
    status INTEGER DEFAULT 1,  -- 1: 正常, 0: 禁用
    last_test DATETIME DEFAULT NULL,  -- 最后测试时间
    test_result TEXT DEFAULT '',  -- 测试结果
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 服务器地址管理表（增强版）
CREATE TABLE IF NOT EXISTS server_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_name TEXT NOT NULL,
    server_address TEXT NOT NULL,
    default_port_imap INTEGER DEFAULT 993,
    default_port_pop3 INTEGER DEFAULT 995,
    ssl_enabled INTEGER DEFAULT 1,
    remarks TEXT DEFAULT '',
    status INTEGER DEFAULT 1,  -- 1: 启用, 0: 禁用
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 插入默认服务器配置 (已移除 - 根据需求去掉所有默认的服务器地址)
-- INSERT OR IGNORE INTO server_addresses (server_name, server_address, default_port_imap, default_port_pop3, ssl_enabled, remarks) VALUES 
-- ('QQ邮箱', 'imap.qq.com', 993, 995, 1, 'QQ邮箱官方服务器'),
-- ('163邮箱', 'imap.163.com', 993, 995, 1, '网易163邮箱服务器'),
-- ('Gmail', 'imap.gmail.com', 993, 995, 1, 'Google Gmail服务器'),
-- ('Outlook', 'outlook.office365.com', 993, 995, 1, 'Microsoft Outlook服务器'),
-- ('Yahoo', 'imap.mail.yahoo.com', 993, 995, 1, 'Yahoo邮箱服务器'),
-- ('126邮箱', 'imap.126.com', 993, 995, 1, '网易126邮箱服务器'),
-- ('新浪邮箱', 'imap.sina.com', 993, 995, 1, '新浪邮箱服务器');

-- HTTP代理管理表
CREATE TABLE IF NOT EXISTS http_proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT DEFAULT '',
    password TEXT DEFAULT '',
    status INTEGER DEFAULT 1,
    last_check DATETIME DEFAULT NULL,
    response_time INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    remarks TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- SOCKS5代理管理表
CREATE TABLE IF NOT EXISTS socks5_proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT DEFAULT '',
    password TEXT DEFAULT '',
    status INTEGER DEFAULT 1,
    last_check DATETIME DEFAULT NULL,
    response_time INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    remarks TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 统一代理ID管理表
CREATE TABLE IF NOT EXISTS unified_proxy_ids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_type TEXT NOT NULL, -- 'http' or 'socks5'
    proxy_table_id INTEGER NOT NULL, -- 对应http_proxies或socks5_proxies的id
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 卡密管理表
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_key TEXT NOT NULL UNIQUE,
    card_type TEXT NOT NULL DEFAULT 'general',  -- 卡密类型
    usage_limit INTEGER DEFAULT 1,  -- 使用次数限制
    used_count INTEGER DEFAULT 0,   -- 已使用次数
    status INTEGER DEFAULT 1,       -- 1: 可用, 0: 禁用, 2: 已用完
    expired_at DATETIME DEFAULT NULL,  -- 过期时间
    bound_email_id INTEGER DEFAULT NULL,  -- 绑定的邮箱ID
    email_days_filter INTEGER DEFAULT 1,  -- 收取多少天内的邮件
    sender_filter TEXT DEFAULT '',  -- 指定发件人邮箱地址过滤 (逗号分隔多个地址)
    remarks TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bound_email_id) REFERENCES mail_accounts(id)
);

-- 卡密使用日志表
CREATE TABLE IF NOT EXISTS card_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    card_key TEXT NOT NULL,
    user_ip TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    action TEXT NOT NULL,  -- 'use', 'check', 'invalid'
    result TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (card_id) REFERENCES cards(id)
);

-- 收件日志表
CREATE TABLE IF NOT EXISTS mail_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    mail_subject TEXT DEFAULT '',
    mail_from TEXT DEFAULT '',
    mail_to TEXT DEFAULT '',
    received_at DATETIME DEFAULT NULL,
    status TEXT DEFAULT 'received',  -- 'received', 'processed', 'failed'
    error_message TEXT DEFAULT '',
    ip_address TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 系统配置表
CREATE TABLE IF NOT EXISTS system_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    config_type TEXT DEFAULT 'string',  -- 'string', 'number', 'boolean', 'json'
    description TEXT DEFAULT '',
    is_system INTEGER DEFAULT 0,  -- 1: 系统配置, 0: 用户配置
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 插入默认系统配置
INSERT OR IGNORE INTO system_config (config_key, config_value, config_type, description, is_system) VALUES 
('system_name', '邮件查看系统', 'string', '系统名称', 1),
('system_title', '邮件查看系统', 'string', '系统页面标题', 0),
('system_version', '2.0.0', 'string', '系统版本', 1),
('max_mail_accounts', '100', 'number', '最大邮箱账号数量', 0),
('enable_proxy', '0', 'boolean', '启用代理功能', 0),
('enable_card_system', '1', 'boolean', '启用卡密系统', 0),
('mail_check_interval', '300', 'number', '邮件检查间隔（秒）', 0),
('log_retention_days', '30', 'number', '日志保留天数', 0),
('enable_registration', '0', 'boolean', '启用用户注册', 0),
('site_url', 'http://localhost:8005', 'string', '站点URL', 0),
('admin_email', 'admin@example.com', 'string', '管理员邮箱', 0);

-- 代理配置管理表（统一代理设置）
CREATE TABLE IF NOT EXISTS proxy_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 插入默认代理配置
INSERT OR IGNORE INTO proxy_config (config_key, config_value, description) VALUES 
('proxy_enabled', '0', '是否启用代理功能'),
('active_proxy_type', '', '当前激活的代理类型（http/socks5）'),
('active_proxy_id', '0', '当前激活的代理ID'),
('proxy_auto_select', '1', '是否自动选择序号ID为1的代理');

-- 创建索引（增强版）
CREATE INDEX IF NOT EXISTS idx_mail_accounts_email ON mail_accounts(email);
CREATE INDEX IF NOT EXISTS idx_mail_accounts_created_at ON mail_accounts(created_at);
CREATE INDEX IF NOT EXISTS idx_mail_accounts_status ON mail_accounts(status);
CREATE INDEX IF NOT EXISTS idx_server_addresses_name ON server_addresses(server_name);
CREATE INDEX IF NOT EXISTS idx_server_addresses_address ON server_addresses(server_address);
CREATE INDEX IF NOT EXISTS idx_server_addresses_status ON server_addresses(status);
CREATE INDEX IF NOT EXISTS idx_http_proxies_host_port ON http_proxies(host, port);
CREATE INDEX IF NOT EXISTS idx_http_proxies_status ON http_proxies(status);
CREATE INDEX IF NOT EXISTS idx_socks5_proxies_host_port ON socks5_proxies(host, port);
CREATE INDEX IF NOT EXISTS idx_socks5_proxies_status ON socks5_proxies(status);
CREATE INDEX IF NOT EXISTS idx_unified_proxy_ids_type ON unified_proxy_ids(proxy_type);
CREATE INDEX IF NOT EXISTS idx_unified_proxy_ids_table_id ON unified_proxy_ids(proxy_table_id);
CREATE INDEX IF NOT EXISTS idx_cards_key ON cards(card_key);
CREATE INDEX IF NOT EXISTS idx_cards_status ON cards(status);
CREATE INDEX IF NOT EXISTS idx_card_logs_card_id ON card_logs(card_id);
CREATE INDEX IF NOT EXISTS idx_card_logs_created_at ON card_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_mail_logs_email ON mail_logs(email);
CREATE INDEX IF NOT EXISTS idx_mail_logs_created_at ON mail_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_system_config_key ON system_config(config_key);
CREATE INDEX IF NOT EXISTS idx_proxy_config_key ON proxy_config(config_key);