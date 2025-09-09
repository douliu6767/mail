# 逗留邮箱管理平台

## 功能说明

这是一个简单的邮箱管理平台，包含前台邮件收取和后台管理功能。

### 文件结构

- `index.html` - 前台邮箱收件页面
- `login.html` - 后台登录页面  
- `admin.html` - 后台管理页面
- `api.php` - 后端API接口
- `style.css` - 样式文件

### 登录信息

- 管理员账号：`admin`
- 管理员密码：`admin123`

### 访问路径

- 前台收件：`/index.html` 或 `/`
- 后台登录：`/login.html`
- 后台管理：`/admin.html`

## Nginx 配置建议

为了实现 `/admin` 路径自动跳转到 `/admin.html`，可以在 nginx 配置中添加以下规则：

```nginx
server {
    listen 80;
    server_name your-domain.com;
    root /path/to/your/mail/project;
    index index.html;

    # 处理 /admin 路径重定向到 /admin.html
    location = /admin {
        return 301 $scheme://$server_name/admin.html;
    }
    
    # 处理 /admin/ 路径重定向到 /admin.html  
    location = /admin/ {
        return 301 $scheme://$server_name/admin.html;
    }

    # 处理 PHP 文件
    location ~ \.php$ {
        fastcgi_pass unix:/var/run/php/php7.4-fpm.sock; # 根据你的 PHP 版本调整
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }

    # 处理静态文件
    location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

### 使用前端脚本实现跳转（可选）

如果无法修改服务器配置，也可以创建一个 `admin/index.html` 文件实现客户端跳转：

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <script>
        window.location.href = '../admin.html';
    </script>
</head>
<body>
    <p>正在跳转到管理后台...</p>
</body>
</html>
```

## 使用说明

1. 部署文件到 Web 服务器
2. 确保 PHP 环境支持 SQLite 和 IMAP 扩展
3. 访问 `login.html` 进行后台登录
4. 在后台添加邮箱账号后，可在前台 `index.html` 查看邮件

## 安全提醒

- 建议修改默认管理员密码
- 在生产环境中请配置 HTTPS
- 定期备份数据库文件 `db.sqlite`