# 邮件查看系统 (Mail-20250916)

一个基于 Python Flask 框架开发的现代化邮件查看系统，支持 IMAP/POP3 协议，提供完整的邮件管理和查看功能，支持多种数据库和代理连接。

## 🌟 主要特性

- 🐍 **Python Flask 3.1+**：现代化的 Python Web 框架，易于维护和扩展
- 🌐 **现代化界面**：响应式设计，完美支持桌面端和移动端访问
- 📧 **多协议支持**：完整支持 IMAP 和 POP3 协议，可选择 SSL 安全连接
- 🔧 **完整管理后台**：功能齐全的管理员控制面板，支持所有管理操作
- 🌐 **代理池支持**：集成 HTTP 和 SOCKS5 代理池，支持代理连接和智能切换
- 🔑 **卡密系统**：完整的卡密生成、管理和使用系统，支持邮箱绑定
- 🗄️ **多数据库支持**：支持 SQLite、MySQL、PostgreSQL 多种数据库
- 🛡️ **安全性**：管理员登录验证，安全的会话管理，密码加密存储
- 📱 **完美移动适配**：所有页面完美适配移动端，提供原生 APP 般的体验
- 🎨 **美观界面**：渐变背景、流畅动画、现代化 UI 设计
- 🐳 **Docker 支持**：提供完整的 Docker 化部署方案

## 🏗️ 技术栈

- **后端**：Python 3.12+、Flask 3.1+、Werkzeug 3.1+
- **前端**：HTML5、CSS3、JavaScript (ES6+)、响应式设计
- **数据库**：SQLite3 (默认) / MySQL 8.0+ / PostgreSQL 12+
- **邮件处理**：IMAPClient 3.0+、内置邮件解析器
- **代理支持**：PySocks、内置代理池管理
- **会话管理**：Flask-Session、安全会话存储
- **容器化**：Docker、Docker Compose

## 📁 项目结构

```
mail-915/
├── app.py                      # Flask 主应用文件
├── requirements.txt            # Python 依赖包
├── Dockerfile                 # Docker 镜像构建文件
├── docker-compose.yml         # Docker Compose 配置
├── .dockerignore              # Docker 构建忽略文件
├── templates/                 # Jinja2 模板文件
│   ├── base.html             # 基础模板
│   ├── frontend/             # 前端用户界面
│   │   └── index.html        # 用户邮件查看页面
│   └── admin/                # 后台管理界面
│       ├── login.html        # 管理员登录页面 
│       ├── home.html         # 管理员首页
│       ├── mailbox.html      # 邮箱管理页面
│       ├── daili.html        # 代理池管理页面
│       ├── kami.html         # 卡密管理页面
│       ├── kamirizhi.html    # 卡密日志页面
│       ├── shoujian.html     # 收件日志页面
│       └── system.html       # 系统设置页面
├── python/                   # Python 邮件处理模块
│   ├── mail_fetcher.py       # 邮件获取器（支持代理）
│   └── requirements.txt      # 邮件模块依赖
├── static/                   # 静态资源文件
│   └── img/                  # 图片资源
│       └── favicons/         # 网站图标
├── db/                       # 数据库文件
│   ├── init.sql             # 数据库初始化脚本
│   ├── mail.sqlite          # 主数据库（自动创建）
│   └── admin.sqlite         # 管理员数据库（自动创建）
└── README.md                # 项目说明文档
```

## 🚀 快速开始

### 环境要求

- **Python 版本**：3.12 或以上
- **系统**：Linux/Windows/macOS
- **包管理**：pip
- **容器运行时**：Docker 和 Docker Compose（可选）

### 方式一：Docker 部署（推荐）

#### 使用 SQLite（默认，最简单）

```bash
# 1. 克隆项目
git clone https://github.com/douliu6767/Mail.git
cd mail

# 2. 启动服务
docker-compose up -d

# 3. 访问应用
# 前端：http://localhost:8005
# 管理后台：http://localhost:8005/admin
```

#### 使用 MySQL 数据库

```bash
# 1. 启动 MySQL 和应用
docker-compose --profile mysql up -d

# 2. 修改环境变量
# 编辑 docker-compose.yml，取消注释 MySQL 相关环境变量

# 3. 重新启动
docker-compose --profile mysql up -d --force-recreate
```

#### 使用 PostgreSQL 数据库

```bash
# 1. 启动 PostgreSQL 和应用
docker-compose --profile postgres up -d

# 2. 修改环境变量
# 编辑 docker-compose.yml，取消注释 PostgreSQL 相关环境变量

# 3. 重新启动
docker-compose --profile postgres up -d --force-recreate
```

### 方式二：传统部署

#### 一键安装脚本

```bash
# 1. 克隆项目
git clone https://github.com/douliu6767/Mail.git
cd mail

# 2. 运行安装脚本
chmod +x install.sh
./install.sh

# 3. 启动应用
python app.py
```

#### 手动安装

```bash
# 1. 克隆项目
git clone https://github.com/douliu6767/Mail.git
cd mail

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 启动应用（会自动初始化数据库）
python app.py
```

### 访问系统

- **前端用户界面**：http://localhost:8005
- **管理员后台**：http://localhost:8005/admin
- **默认管理员账号**：用户名 `admin`，密码 `admin`

> ⚠️ **安全提醒**：首次登录后请立即修改默认密码！

## 🔧 功能详解

### 1. 邮箱管理

- 📫 **多协议支持**：IMAP 和 POP3 协议
- 🔐 **安全连接**：支持 SSL/TLS 加密
- 📊 **连接测试**：实时测试邮箱连接状态
- 📝 **批量导入**：支持批量添加邮箱账号
- 🔧 **配置管理**：支持各大邮箱服务商的预设配置

### 2. 代理池管理

- 🌐 **多协议支持**：HTTP、SOCKS5 代理
- ⚡ **智能切换**：自动选择最优代理
- 📊 **状态监控**：实时监控代理可用性
- 🔄 **故障切换**：自动故障切换和负载均衡
- 📈 **统计分析**：代理使用统计和性能分析

### 3. 卡密系统

- 🔑 **卡密生成**：支持单个或批量生成访问卡密
- 📊 **使用统计**：详细的使用记录和统计信息
- 🗂️ **回收站**：已删除卡密的恢复功能
- ⏰ **过期管理**：自动处理过期卡密
- 📧 **邮箱绑定**：支持卡密与邮箱绑定，提升安全性
- 🔗 **API 生成**：为每个卡密生成专用的 API 取件链接

### 4. API 功能

- 🌐 **RESTful API**：提供完整的 REST API 接口
- 🔑 **卡密验证**：基于卡密的访问控制
- 📧 **邮件获取**：通过 API 获取邮件内容
- 📊 **状态监控**：API 调用统计和监控
- 🛡️ **安全防护**：防止恶意调用和滥用

### 5. 日志系统

- 📝 **操作日志**：完整记录所有管理操作
- 📧 **邮件日志**：邮件获取记录和统计
- 🔍 **查询过滤**：支持多条件查询和筛选
- 📊 **数据分析**：日志数据的统计分析

### 6. 系统设置

- 👤 **账号管理**：管理员账号安全设置
- 🎨 **界面定制**：页面标题和样式配置
- 🔧 **系统配置**：核心参数和功能设置
- 🛡️ **安全设置**：访问控制和安全策略

## 🗄️ 数据库配置

### SQLite（默认）

```bash
# 无需额外配置，自动创建数据库文件
export DATABASE_TYPE=sqlite
python app.py
```

### MySQL

```bash
# 设置环境变量
export DATABASE_TYPE=mysql
export MYSQL_HOST=localhost
export MYSQL_USER=mail_user
export MYSQL_PASSWORD=your_password
export MYSQL_DATABASE=mail_system

# 启动应用
python app.py
```

### PostgreSQL

```bash
# 设置环境变量
export DATABASE_TYPE=postgresql
export POSTGRES_HOST=localhost
export POSTGRES_USER=mail_user
export POSTGRES_PASSWORD=your_password
export POSTGRES_DATABASE=mail_system

# 启动应用
python app.py
```

## 🌐 生产环境部署

### 使用 Docker（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/douliu6767/Mail.git
cd mail

# 2. 构建镜像
docker build -t douliu676/mail:latest .

# 3. 运行容器
docker run -d \
  --name mail \
  -p 8005:8005 \
  -v $(pwd)/db:/app/db \
  douliu676/mail:20250918-1

# 4. 使用 Docker Compose（推荐）
docker-compose up -d
```

### 使用 Gunicorn

```bash
# 1. 安装 Gunicorn
pip install gunicorn

# 2. 启动服务（4个工作进程）
gunicorn -w 4 -b 0.0.0.0:8005 app:app

# 3. 后台运行
nohup gunicorn -w 4 -b 0.0.0.0:8005 app:app > gunicorn.log 2>&1 &
```

### 使用 uWSGI

```bash
# 1. 安装 uWSGI
pip install uwsgi

# 2. 启动服务
uwsgi --http :8005 --wsgi-file app.py --callable app --processes 4
```

### Nginx 反向代理配置

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # 静态文件缓存
    location /static/ {
        alias /path/to/mail-915/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}
```

## 📧 邮箱配置参考

### 常用邮箱服务商配置

#### QQ邮箱（推荐）
```
服务器：imap.qq.com
端口：993
协议：IMAP
SSL：开启
密码：授权码（非QQ密码）
```

#### 163邮箱
```
服务器：imap.163.com
端口：993
协议：IMAP  
SSL：开启
密码：授权码
```

#### Gmail
```
服务器：imap.gmail.com
端口：993
协议：IMAP
SSL：开启
密码：应用专用密码
```

#### Outlook/Hotmail
```
服务器：outlook.office365.com
端口：993
协议：IMAP
SSL：开启
密码：账号密码或应用密码
```

#### 企业邮箱
```
服务器：mail.your-company.com
端口：993/143
协议：IMAP
SSL：根据企业配置
密码：企业邮箱密码
```

### 获取邮箱授权码步骤

1. **QQ邮箱**：设置 → 账户 → 开启IMAP服务 → 生成授权码
2. **163邮箱**：设置 → POP3/IMAP → 开启IMAP服务 → 设置客户端授权码
3. **Gmail**：Google账户 → 安全性 → 2步验证 → 应用专用密码
4. **Outlook**：账户设置 → 安全性 → 应用密码

## 🔧 API 接口文档

### 邮件获取 API

#### 基础邮件获取
```http
POST /api/get_mail
Content-Type: application/json

{
    "email": "user@example.com",
    "card_key": "your_card_key"
}
```

#### 响应格式
```json
{
    "success": true,
    "data": {
        "subject": "邮件主题",
        "from": "sender@example.com",
        "to": "recipient@example.com",
        "date": "2024-01-01 12:00:00",
        "body": "邮件内容",
        "attachments": [
            {
                "filename": "附件名.txt",
                "size": 1024,
                "mime_type": "text/plain"
            }
        ]
    },
    "card_info": {
        "remaining_uses": 9,
        "total_uses": 10
    }
}
```

### 管理员 API

#### 邮箱管理
```http
# 获取邮箱列表
GET /admin/api/mailbox

# 添加邮箱
POST /admin/api/mailbox
{
    "action": "add",
    "email": "user@example.com",
    "password": "password",
    "server": "imap.example.com",
    "port": 993,
    "protocol": "imap",
    "ssl": true
}

# 删除邮箱
DELETE /admin/api/mailbox
{
    "id": 1
}
```

#### 代理管理
```http
# 获取代理列表
GET /admin/api/proxy

# 添加代理
POST /admin/api/proxy
{
    "action": "add",
    "proxy_type": "http",
    "server": "proxy.example.com",
    "port": 8080,
    "username": "user",
    "password": "pass"
}
```

#### 卡密管理
```http
# 获取卡密列表
GET /admin/api/cards

# 生成卡密
POST /admin/api/cards
{
    "action": "generate",
    "usage_limit": 10,
    "expired_at": "2024-12-31",
    "remarks": "测试卡密"
}

# 批量生成卡密
POST /admin/api/cards
{
    "action": "batch_generate",
    "count": 100,
    "usage_limit": 5,
    "expired_at": "2024-12-31"
}
```

## 🐛 故障排除

### 常见问题及解决方案

#### 1. Python 依赖安装失败

**问题描述**：`pip install` 报错，依赖包安装失败

**解决方法**：
```bash
# 更新 pip
pip install --upgrade pip

# 使用清华源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Ubuntu/Debian 系统包
sudo apt update
sudo apt install python3-dev python3-pip libpq-dev default-libmysqlclient-dev
```

#### 2. 邮箱连接失败

**检查项目**：
- ✅ 确认已开启IMAP/POP3服务
- ✅ 使用授权码而非登录密码
- ✅ 验证服务器地址和端口
- ✅ 检查SSL设置
- ✅ 确认防火墙不阻止连接

**常见错误**：
```
[AUTHENTICATIONFAILED] Login failed
```
**解决**：检查用户名和授权码是否正确

```
[IMAP] Connection refused
```
**解决**：检查服务器地址和端口，确认防火墙设置

#### 3. 数据库连接问题

**SQLite权限问题**：
```bash
# 设置正确的文件权限
chmod 755 db/
chmod 644 db/*.sqlite

# 确保目录存在
mkdir -p db/
```

**MySQL连接问题**：
```bash
# 创建数据库和用户
mysql -u root -p -e "CREATE DATABASE mail_system;"
mysql -u root -p -e "CREATE USER 'mail_user'@'localhost' IDENTIFIED BY 'your_password';"
mysql -u root -p -e "GRANT ALL ON mail_system.* TO 'mail_user'@'localhost';"
mysql -u root -p -e "FLUSH PRIVILEGES;"
```

**PostgreSQL连接问题**：
```bash
# 创建数据库和用户
sudo -u postgres psql -c "CREATE DATABASE mail_system;"
sudo -u postgres psql -c "CREATE USER mail_user WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE mail_system TO mail_user;"
```

#### 4. Docker 部署问题

**容器启动失败**：
```bash
# 查看日志
docker logs mail-915

# 检查端口占用
netstat -tlnp | grep 8005

# 重新构建镜像
docker-compose build --no-cache
```

**数据持久化问题**：
```bash
# 确保挂载目录存在且有正确权限
mkdir -p ./db
chmod 755 ./db

# 检查挂载配置
docker-compose config
```

#### 5. 移动端显示异常

**解决方法**：
- ✅ 清除浏览器缓存
- ✅ 检查网络连接
- ✅ 更新浏览器版本
- ✅ 确认JavaScript已启用
- ✅ 检查控制台错误信息

#### 6. API 调用失败

**常见错误**：
```json
{"success": false, "message": "卡密不存在"}
```
**解决**：检查卡密是否正确且未过期

```json
{"success": false, "message": "卡密已达到使用上限"}
```
**解决**：检查卡密使用次数限制

## 🔒 安全建议

### 生产环境安全配置

1. **立即修改默认密码**
   ```bash
   # 登录管理后台后立即修改密码
   # 使用强密码：至少12位，包含大小写字母、数字和特殊字符
   ```

2. **使用HTTPS**
   ```nginx
   # Nginx SSL 配置
   server {
       listen 443 ssl http2;
       ssl_certificate /path/to/certificate.crt;
       ssl_certificate_key /path/to/private.key;
       ssl_protocols TLSv1.2 TLSv1.3;
   }
   ```

3. **配置防火墙**
   ```bash
   # Ubuntu/Debian
   sudo ufw enable
   sudo ufw allow 22  # SSH
   sudo ufw allow 80  # HTTP
   sudo ufw allow 443 # HTTPS
   sudo ufw allow 8005 # 应用端口（如果直接暴露）
   
   # CentOS/RHEL
   sudo firewall-cmd --permanent --add-service=http
   sudo firewall-cmd --permanent --add-service=https
   sudo firewall-cmd --reload
   ```

4. **定期备份数据库**
   ```bash
   # 创建备份脚本
   #!/bin/bash
   DATE=$(date +%Y%m%d_%H%M%S)
   cp -r /path/to/mail-915/db /backup/mail-915_$DATE
   
   # 添加到 crontab
   0 2 * * * /path/to/backup_script.sh
   ```

5. **环境变量安全**
   ```bash
   # 使用环境变量而非硬编码
   export SECRET_KEY="your-random-secret-key-here"
   export DATABASE_URL="your-secure-database-url"
   export ADMIN_PASSWORD="your-secure-admin-password"
   ```

6. **访问日志监控**
   ```bash
   # 设置日志轮转
   sudo logrotate -f /etc/logrotate.conf
   
   # 监控异常访问
   tail -f /var/log/nginx/access.log | grep "POST\|DELETE"
   ```

### 推荐的安全措施

```bash
# 1. 设置合适的文件权限
find /path/to/mail-915 -type d -exec chmod 755 {} \;
find /path/to/mail-915 -type f -exec chmod 644 {} \;
chmod 700 /path/to/mail-915/db/
chmod 600 /path/to/mail-915/db/*.sqlite

# 2. 使用进程管理器
pip install supervisor

# 3. 设置系统服务
sudo systemctl enable mail-915
sudo systemctl start mail-915
```

## 📈 更新日志

### 版本 2.2.0 (当前版本)
- ✅ **修复卡密错误页面**：美化了卡密不存在的错误提示页面
- ✅ **添加 Favicon 支持**：所有页面现在都正确显示网站图标
- ✅ **Docker 化支持**：提供完整的 Docker 和 Docker Compose 配置
- ✅ **文档重写**：全新的详细文档，包含部署和使用说明
- ✅ **多数据库兼容性**：确保 SQLite、MySQL、PostgreSQL 完全兼容
- 🐛 **Bug 修复**：修复了 API 取件页面中 f-string 语法错误
- 🔧 **代码优化**：改进了错误处理和日志记录

### 版本 2.1.0 (移动端完美适配版)
- ✅ **完美移动端适配**：所有管理页面支持移动端
- ✅ **响应式导航**：移动端侧边栏菜单
- ✅ **触摸优化**：按钮和交互适配触摸操作
- ✅ **性能优化**：页面加载和交互性能提升
- ✅ **UI/UX改进**：更现代化的界面设计

### 版本 2.0.0 (Python Flask 重构版)
- 🔄 **完全重构**：从PHP迁移到Python Flask
- 🆕 **新增功能**：代理池、卡密系统、多数据库支持
- 🎨 **界面升级**：现代化响应式设计
- 🚀 **性能提升**：更快的响应速度和更好的稳定性

### 版本 1.0.0 (PHP 原版)
- 📧 **基础功能**：IMAP/POP3邮件获取
- 🔧 **管理后台**：基础的邮箱管理
- 📱 **响应式设计**：基础的移动端支持

## 🤝 技术支持

### 获取帮助

遇到问题时，请按以下顺序检查：

1. **查看日志**：检查应用和系统日志
2. **验证配置**：确认邮箱和代理设置
3. **测试连接**：使用内置测试功能
4. **检查网络**：确认网络连接正常
5. **更新软件**：保持依赖包最新

### 常用诊断命令

```bash
# 检查Python环境
python --version
pip list | grep -E "(flask|imapclient)"

# 检查数据库
sqlite3 db/mail.sqlite ".tables"

# 检查端口占用
netstat -tlnp | grep 8005

# 查看应用日志
tail -f gunicorn.log

# Docker 诊断
docker logs mail-915
docker-compose ps
```

### 性能监控

```bash
# 监控系统资源
htop
iostat -x 1
iotop

# 监控应用性能
curl -w "@curl-format.txt" -o /dev/null -s "http://localhost:8005/"

# 数据库性能
# SQLite
sqlite3 db/mail.sqlite "EXPLAIN QUERY PLAN SELECT * FROM cards;"

# MySQL
mysql -u root -p -e "SHOW PROCESSLIST;"

# PostgreSQL
psql -U postgres -c "SELECT * FROM pg_stat_activity;"
```

## 🔗 相关链接

- **GitHub 仓库**：https://github.com/douliu6767/mail-915
- **问题反馈**：https://github.com/douliu6767/mail-915/issues
- **文档中心**：https://github.com/douliu6767/mail-915/wiki
- **更新日志**：https://github.com/douliu6767/mail-915/releases

## 📄 许可证

本项目基于 MIT 许可证开源，可自由使用和修改。

```
MIT License

Copyright (c) 2024 Mail-915 Project

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 🙏 致谢

感谢所有为这个项目做出贡献的开发者和用户。特别感谢：

- Flask 框架的开发团队
- IMAPClient 库的维护者
- 所有提供反馈和建议的用户
- 开源社区的支持

---

**Mail-915 v2.2.0** - 现代化邮件管理解决方案，完美支持桌面端、移动端和容器化部署。
