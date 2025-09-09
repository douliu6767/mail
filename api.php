<?php
session_start();
header('Content-Type: application/json');

// 数据库初始化
$db = new PDO('sqlite:db.sqlite');
$db->exec("CREATE TABLE IF NOT EXISTS admin (
    username TEXT PRIMARY KEY,
    password TEXT
)");
$db->exec("CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE,
    imap_host TEXT,
    imap_port INTEGER,
    username TEXT,
    password TEXT
)");

// 初始化默认管理员账号
if (!$db->query("SELECT * FROM admin")->fetch(PDO::FETCH_ASSOC)) {
    $stmt = $db->prepare("INSERT INTO admin (username, password) VALUES (?, ?)");
    $stmt->execute(["admin", password_hash("admin123", PASSWORD_DEFAULT)]);
}

// 路由
$action = $_GET['action'] ?? '';

// 管理员登录
if ($action == 'login') {
    $data = json_decode(file_get_contents('php://input'), true);
    $admin = $db->query("SELECT * FROM admin WHERE username = " . $db->quote($data['username']))->fetch(PDO::FETCH_ASSOC);
    if ($admin && password_verify($data['password'], $admin['password'])) {
        $_SESSION['admin'] = $admin['username'];
        echo json_encode(['success' => true]);
    } else {
        echo json_encode(['success' => false, 'msg' => '账号或密码错误']);
    }
    exit;
}

// 管理员登出
if ($action == 'logout') {
    session_destroy();
    echo json_encode(['success' => true]);
    exit;
}

// 检查登录状态
if ($action == 'check_login') {
    echo json_encode(['success' => check_admin()]);
    exit;
}

// 检查是否登录
function check_admin() {
    return isset($_SESSION['admin']);
}

// 修改管理员账号
if ($action == 'change_admin' && check_admin()) {
    $data = json_decode(file_get_contents('php://input'), true);
    $new_username = $data['username'];
    $stmt = $db->prepare("UPDATE admin SET username=?");
    $ok = $stmt->execute([$new_username]);
    if ($ok) {
        $_SESSION['admin'] = $new_username;
        echo json_encode(['success' => true]);
    } else {
        echo json_encode(['success' => false, 'msg' => '修改失败']);
    }
    exit;
}

// 修改管理员密码
if ($action == 'change_password' && check_admin()) {
    $data = json_decode(file_get_contents('php://input'), true);
    $new_password = password_hash($data['password'], PASSWORD_DEFAULT);
    $stmt = $db->prepare("UPDATE admin SET password=? WHERE username=?");
    $ok = $stmt->execute([$new_password, $_SESSION['admin']]);
    echo json_encode(['success' => $ok]);
    exit;
}

// 添加邮箱账号（需登录）
if ($action == 'add_account' && check_admin()) {
    $data = json_decode(file_get_contents('php://input'), true);
    $stmt = $db->prepare("INSERT INTO accounts (email, imap_host, imap_port, username, password) VALUES (?, ?, ?, ?, ?)");
    $ok = $stmt->execute([
        $data['email'], $data['imap_host'], $data['imap_port'], $data['username'], $data['password']
    ]);
    if ($ok) {
        echo json_encode(['success' => true]);
    } else {
        echo json_encode(['success' => false, 'msg' => '添加失败，可能邮箱已存在！']);
    }
    exit;
}

// 查询所有邮箱账号（需登录）
if ($action == 'list_accounts' && check_admin()) {
    $rows = $db->query("SELECT id,email,imap_host,imap_port,username FROM accounts")->fetchAll(PDO::FETCH_ASSOC);
    echo json_encode(['success' => true, 'data' => $rows]);
    exit;
}

// 获取邮箱最新一封邮件（前端用）
if ($action == 'fetch_mail') {
    $email = $_GET['email'] ?? '';
    $row = $db->query("SELECT * FROM accounts WHERE email=" . $db->quote($email))->fetch(PDO::FETCH_ASSOC);
    if (!$row) {
        echo json_encode(['success' => false, 'msg' => '该邮箱未添加']);
        exit;
    }
    $inbox = @imap_open('{' . $row['imap_host'] . ':' . $row['imap_port'] . '/imap/ssl}INBOX', $row['username'], $row['password']);
    if ($inbox) {
        $emails = imap_search($inbox, 'ALL');
        $mail = null;
        if ($emails) {
            $latest = max($emails);
            $overview = imap_fetch_overview($inbox, $latest, 0)[0];
            $body = imap_fetchbody($inbox, $latest, 1);
            $mail = [
                'subject' => $overview->subject,
                'from' => $overview->from,
                'date' => $overview->date,
                'body' => $body
            ];
        }
        imap_close($inbox);
        echo json_encode(['success' => true, 'mail' => $mail]);
    } else {
        echo json_encode(['success' => false, 'msg' => '收件失败，IMAP连接错误或账号信息有误']);
    }
    exit;
}

echo json_encode(['success' => false, 'msg' => '未知操作']);
