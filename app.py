#!/usr/bin/env python3
"""
邮件查看系统 - Flask 应用主文件（完整增强版）
基于原有 PHP 版本完全重构，保持所有功能和 UI 一致
支持多数据库、完整的邮箱管理、代理池、卡密系统等功能
"""

import os
import sqlite3
import secrets
import json
import subprocess
import sys
import time
import requests
import threading
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify, g
from werkzeug.security import check_password_hash, generate_password_hash

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Beijing timezone helper function
def get_beijing_time():
    """获取北京时间 (UTC+8)"""
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')

app = Flask(__name__)

# 配置
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), 'db', 'mail.sqlite')
app.config['DATABASE_TYPE'] = os.environ.get('DATABASE_TYPE', 'sqlite')  # sqlite, mysql, postgresql

# 确保数据库目录存在
os.makedirs(os.path.dirname(app.config['DATABASE']), exist_ok=True)

def get_db():
    """获取数据库连接（支持多数据库）- 优化版本"""
    db = getattr(g, '_database', None)
    if db is None:
        db_type = app.config['DATABASE_TYPE']
        
        try:
            if db_type == 'sqlite':
                db = g._database = sqlite3.connect(
                    app.config['DATABASE'],
                    timeout=30.0,  # 30秒超时
                    check_same_thread=False
                )
                db.row_factory = sqlite3.Row
                # 启用WAL模式提高并发性能
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('PRAGMA synchronous=NORMAL')
                db.execute('PRAGMA cache_size=10000')
                db.execute('PRAGMA temp_store=MEMORY')
            elif db_type == 'mysql':
                # MySQL连接池优化（需要安装 mysql-connector-python）
                import mysql.connector
                from mysql.connector import pooling
                
                config = {
                    'host': os.environ.get('MYSQL_HOST', 'localhost'),
                    'user': os.environ.get('MYSQL_USER', 'root'),
                    'password': os.environ.get('MYSQL_PASSWORD', ''),
                    'database': os.environ.get('MYSQL_DATABASE', 'mail_system'),
                    'charset': 'utf8mb4',
                    'use_unicode': True,
                    'autocommit': False,
                    'connect_timeout': 30,
                    'sql_mode': 'STRICT_TRANS_TABLES',
                }
                
                # 创建连接池（如果不存在）
                if not hasattr(app, '_mysql_pool'):
                    app._mysql_pool = pooling.MySQLConnectionPool(
                        pool_name="mail_pool",
                        pool_size=5,
                        pool_reset_session=True,
                        **config
                    )
                
                db = g._database = app._mysql_pool.get_connection()
                
            elif db_type == 'postgresql':
                # PostgreSQL连接优化（需要安装 psycopg2-binary）
                import psycopg2
                from psycopg2.extras import RealDictCursor
                from psycopg2 import pool
                
                # 创建连接池（如果不存在）
                if not hasattr(app, '_postgres_pool'):
                    app._postgres_pool = psycopg2.pool.SimpleConnectionPool(
                        1, 10,  # 最小1个，最大10个连接
                        host=os.environ.get('POSTGRES_HOST', 'localhost'),
                        user=os.environ.get('POSTGRES_USER', 'postgres'),
                        password=os.environ.get('POSTGRES_PASSWORD', ''),
                        database=os.environ.get('POSTGRES_DATABASE', 'mail_system'),
                        cursor_factory=RealDictCursor
                    )
                
                db = g._database = app._postgres_pool.getconn()
        
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise Exception(f"数据库连接失败: {str(e)}")
            
    return db

def init_db():
    """初始化数据库（支持多数据库）- 优化版本"""
    with app.app_context():
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        try:
            # 使用事务确保原子性
            if db_type != 'sqlite':
                db.autocommit = False
                
            # 读取并执行初始化SQL
            init_sql_path = os.path.join(os.path.dirname(__file__), 'db', 'init.sql')
            if os.path.exists(init_sql_path):
                with open(init_sql_path, 'r', encoding='utf-8') as f:
                    sql_content = f.read()
                    
                    # 根据数据库类型调整SQL语句
                    if db_type == 'mysql':
                        sql_content = sql_content.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'INT AUTO_INCREMENT PRIMARY KEY')
                        sql_content = sql_content.replace('DATETIME DEFAULT CURRENT_TIMESTAMP', 'DATETIME DEFAULT CURRENT_TIMESTAMP')
                        sql_content = sql_content.replace('INSERT OR IGNORE', 'INSERT IGNORE')
                        sql_content = sql_content.replace('INSERT OR REPLACE', 'INSERT INTO ... ON DUPLICATE KEY UPDATE')
                    elif db_type == 'postgresql':
                        sql_content = sql_content.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
                        sql_content = sql_content.replace('DATETIME', 'TIMESTAMP')
                        sql_content = sql_content.replace('INSERT OR IGNORE', 'INSERT ... ON CONFLICT DO NOTHING')
                        sql_content = sql_content.replace('INSERT OR REPLACE', 'INSERT ... ON CONFLICT ... DO UPDATE SET')
                    
                    # 执行SQL
                    if db_type == 'sqlite':
                        db.executescript(sql_content)
                    else:
                        cursor = db.cursor()
                        # 分割并执行每个语句
                        statements = [stmt.strip() for stmt in sql_content.split(';') if stmt.strip()]
                        for statement in statements:
                            try:
                                cursor.execute(statement)
                            except Exception as e:
                                logger.warning(f"SQL statement failed (continuing): {statement[:100]}... Error: {e}")
                        cursor.close()
            
            # 数据库迁移：为现有代理表添加unified_id列
            migrate_proxy_tables(db, db_type)
            
            # 数据库迁移：为cards表添加新字段
            migrate_cards_table(db, db_type)
            
            # 创建管理员用户表（兼容原有PHP版本）
            create_admin_table(db, db_type)
            
            # 创建管理员邮件访问日志表
            create_admin_mail_logs_table(db, db_type)
            
            # 创建卡密回收站表
            create_recycle_bin_table(db, db_type)
            
            # 创建系统配置表
            create_system_config_table(db, db_type)
            
            # 数据库迁移：确保系统标题配置存在
            migrate_system_title_config(db, db_type)
            
            # 检查是否有默认管理员，如果没有则创建
            create_default_admin(db, db_type)
            
            # 提交事务
            if db_type != 'sqlite':
                db.commit()
            else:
                db.commit()
                
            logger.info("Database initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            # 回滚事务
            if db_type != 'sqlite':
                try:
                    db.rollback()
                except:
                    pass
            raise

def create_recycle_bin_table(db, db_type):
    """创建卡密回收站表"""
    try:
        if db_type == 'sqlite':
            db.execute('''
                CREATE TABLE IF NOT EXISTS card_recycle_bin (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_card_id INTEGER NOT NULL,
                    card_key TEXT NOT NULL,
                    usage_limit INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    expired_at DATETIME DEFAULT NULL,
                    bound_email_id INTEGER DEFAULT NULL,
                    email_days_filter INTEGER DEFAULT 1,
                    sender_filter TEXT DEFAULT '',
                    remarks TEXT DEFAULT '',
                    status INTEGER NOT NULL DEFAULT 1,
                    recycle_type TEXT NOT NULL DEFAULT 'deleted',
                    reason TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    deleted_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        elif db_type == 'mysql':
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS card_recycle_bin (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    original_card_id INT NOT NULL,
                    card_key VARCHAR(255) NOT NULL,
                    usage_limit INT NOT NULL DEFAULT 1,
                    used_count INT NOT NULL DEFAULT 0,
                    expired_at DATETIME DEFAULT NULL,
                    bound_email_id INT DEFAULT NULL,
                    email_days_filter INT DEFAULT 1,
                    sender_filter TEXT DEFAULT '',
                    remarks TEXT DEFAULT '',
                    status INT NOT NULL DEFAULT 1,
                    recycle_type ENUM('deleted', 'expired') NOT NULL DEFAULT 'deleted',
                    reason TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    deleted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_recycle_type (recycle_type),
                    INDEX idx_card_key (card_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            ''')
            cursor.close()
        elif db_type == 'postgresql':
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS card_recycle_bin (
                    id SERIAL PRIMARY KEY,
                    original_card_id INTEGER NOT NULL,
                    card_key VARCHAR(255) NOT NULL,
                    usage_limit INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    expired_at TIMESTAMP DEFAULT NULL,
                    bound_email_id INTEGER DEFAULT NULL,
                    email_days_filter INTEGER DEFAULT 1,
                    sender_filter TEXT DEFAULT '',
                    remarks TEXT DEFAULT '',
                    status INTEGER NOT NULL DEFAULT 1,
                    recycle_type VARCHAR(50) NOT NULL DEFAULT 'deleted',
                    reason TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_recycle_type ON card_recycle_bin (recycle_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_card_key ON card_recycle_bin (card_key)')
            cursor.close()
    except Exception as e:
        logger.error(f"Failed to create recycle bin table: {e}")
        raise

def create_admin_mail_logs_table(db, db_type):
    """创建管理员邮件访问日志表"""
    try:
        if db_type == 'sqlite':
            db.execute('''
                CREATE TABLE IF NOT EXISTS admin_mail_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_username TEXT NOT NULL,
                    email TEXT NOT NULL,
                    user_ip TEXT DEFAULT '',
                    action TEXT DEFAULT 'admin_get_mail',
                    result TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        elif db_type == 'mysql':
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_mail_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    admin_username VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    user_ip VARCHAR(255) DEFAULT '',
                    action VARCHAR(255) DEFAULT 'admin_get_mail',
                    result TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            ''')
            cursor.close()
        elif db_type == 'postgresql':
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_mail_logs (
                    id SERIAL PRIMARY KEY,
                    admin_username VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    user_ip VARCHAR(255) DEFAULT '',
                    action VARCHAR(255) DEFAULT 'admin_get_mail',
                    result TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.close()
    except Exception as e:
        logger.error(f"Failed to create admin mail logs table: {e}")
        raise

def create_system_config_table(db, db_type):
    """创建系统配置表"""
    try:
        if db_type == 'sqlite':
            db.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_key TEXT NOT NULL UNIQUE,
                    config_value TEXT NOT NULL,
                    config_type TEXT DEFAULT 'string',
                    description TEXT DEFAULT '',
                    is_system INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        elif db_type == 'mysql':
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    config_key VARCHAR(255) NOT NULL UNIQUE,
                    config_value TEXT NOT NULL,
                    config_type VARCHAR(50) DEFAULT 'string',
                    description TEXT DEFAULT '',
                    is_system TINYINT DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_config_key (config_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            ''')
            cursor.close()
        elif db_type == 'postgresql':
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    id SERIAL PRIMARY KEY,
                    config_key VARCHAR(255) NOT NULL UNIQUE,
                    config_value TEXT NOT NULL,
                    config_type VARCHAR(50) DEFAULT 'string',
                    description TEXT DEFAULT '',
                    is_system INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_config_key ON system_config (config_key)')
            cursor.close()
    except Exception as e:
        logger.error(f"Failed to create system config table: {e}")
        raise

def migrate_system_title_config(db, db_type):
    """迁移系统标题配置：确保system_title配置项存在"""
    try:
        # 检查是否已存在system_title配置
        if db_type == 'sqlite':
            result = db.execute('SELECT COUNT(*) FROM system_config WHERE config_key = ?', ('system_title',)).fetchone()
            exists = result[0] > 0
        else:
            cursor = db.cursor()
            cursor.execute('SELECT COUNT(*) FROM system_config WHERE config_key = %s', ('system_title',))
            result = cursor.fetchone()
            exists = result[0] > 0
            cursor.close()
        
        if not exists:
            # 插入默认的system_title配置
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if db_type == 'sqlite':
                db.execute('''
                    INSERT INTO system_config 
                    (config_key, config_value, config_type, description, is_system, created_at, updated_at)
                    VALUES ('system_title', '邮件查看系统', 'string', '系统页面标题', 0, ?, ?)
                ''', (now, now))
            else:
                cursor = db.cursor()
                cursor.execute('''
                    INSERT INTO system_config 
                    (config_key, config_value, config_type, description, is_system, created_at, updated_at)
                    VALUES ('system_title', %s, 'string', '系统页面标题', 0, %s, %s)
                ''', ('邮件查看系统', now, now))
                cursor.close()
            
            logger.info("Added system_title configuration to system_config table")
        else:
            logger.info("System_title configuration already exists")
            
    except Exception as e:
        logger.error(f"Failed to migrate system_title config: {e}")
        raise

def create_admin_table(db, db_type):
    """创建管理员用户表"""
    try:
        if db_type == 'sqlite':
            db.execute('''
                CREATE TABLE IF NOT EXISTS admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        elif db_type == 'mysql':
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            ''')
            cursor.close()
        elif db_type == 'postgresql':
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.close()
    except Exception as e:
        logger.error(f"Failed to create admin table: {e}")
        raise

def create_default_admin(db, db_type):
    """创建默认管理员用户"""
    try:
        if db_type == 'sqlite':
            admin = db.execute('SELECT * FROM admin_users WHERE username = ?', ('admin',)).fetchone()
            if not admin:
                db.execute('INSERT INTO admin_users (username, password) VALUES (?, ?)', 
                          ('admin', 'admin'))  # 简单密码，生产环境应使用hash
        else:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM admin_users WHERE username = %s', ('admin',))
            admin = cursor.fetchone()
            if not admin:
                cursor.execute('INSERT INTO admin_users (username, password) VALUES (%s, %s)', 
                              ('admin', 'admin'))
            cursor.close()
    except Exception as e:
        logger.error(f"Failed to create default admin: {e}")
        raise

def migrate_proxy_tables(db, db_type):
    """迁移代理表，添加unified_id字段"""
    try:
        # 检查http_proxies表是否有unified_id列
        if db_type == 'sqlite':
            result = db.execute("PRAGMA table_info(http_proxies)").fetchall()
            columns = [col[1] for col in result]
            
            if 'unified_id' not in columns:
                db.execute('ALTER TABLE http_proxies ADD COLUMN unified_id INTEGER DEFAULT 0')
                logger.info("Added unified_id column to http_proxies table")
                
        else:
            cursor = db.cursor()
            try:
                if db_type == 'mysql':
                    cursor.execute("SHOW COLUMNS FROM http_proxies LIKE 'unified_id'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE http_proxies ADD COLUMN unified_id INT DEFAULT 0')
                        logger.info("Added unified_id column to http_proxies table")
                elif db_type == 'postgresql':
                    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='http_proxies' AND column_name='unified_id'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE http_proxies ADD COLUMN unified_id INTEGER DEFAULT 0')
                        logger.info("Added unified_id column to http_proxies table")
            except Exception as e:
                logger.error(f"Error checking/adding unified_id to http_proxies: {e}")
        
        # 检查socks5_proxies表是否有unified_id列
        if db_type == 'sqlite':
            result = db.execute("PRAGMA table_info(socks5_proxies)").fetchall()
            columns = [col[1] for col in result]
            
            if 'unified_id' not in columns:
                db.execute('ALTER TABLE socks5_proxies ADD COLUMN unified_id INTEGER DEFAULT 0')
                logger.info("Added unified_id column to socks5_proxies table")
                
        else:
            cursor = db.cursor()
            try:
                if db_type == 'mysql':
                    cursor.execute("SHOW COLUMNS FROM socks5_proxies LIKE 'unified_id'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE socks5_proxies ADD COLUMN unified_id INT DEFAULT 0')
                        logger.info("Added unified_id column to socks5_proxies table")
                elif db_type == 'postgresql':
                    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='socks5_proxies' AND column_name='unified_id'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE socks5_proxies ADD COLUMN unified_id INTEGER DEFAULT 0')
                        logger.info("Added unified_id column to socks5_proxies table")
            except Exception as e:
                logger.error(f"Error checking/adding unified_id to socks5_proxies: {e}")
        
        # 为现有代理分配统一ID
        assign_unified_ids_to_existing_proxies(db, db_type)
        
        if db_type != 'sqlite':
            db.commit()
        else:
            db.commit()
            
    except Exception as e:
        logger.error(f"Error during proxy table migration: {e}")

def migrate_cards_table(db, db_type):
    """迁移cards表，添加新的邮件管理字段"""
    try:
        # 检查cards表是否有新字段
        new_columns = [
            ('bound_email_id', 'INTEGER DEFAULT NULL'),
            ('email_days_filter', 'INTEGER DEFAULT 1'),
            ('sender_filter', 'TEXT DEFAULT \'\''),
            ('keyword_filter', 'TEXT DEFAULT \'\'')
        ]
        
        for column_name, column_def in new_columns:
            if db_type == 'sqlite':
                # 检查列是否存在
                result = db.execute("PRAGMA table_info(cards)").fetchall()
                existing_columns = [col[1] for col in result]
                
                if column_name not in existing_columns:
                    if db_type == 'sqlite':
                        if column_name == 'bound_email_id':
                            db.execute('ALTER TABLE cards ADD COLUMN bound_email_id INTEGER DEFAULT NULL')
                        elif column_name == 'email_days_filter':
                            db.execute('ALTER TABLE cards ADD COLUMN email_days_filter INTEGER DEFAULT 1')
                        elif column_name == 'sender_filter':
                            db.execute('ALTER TABLE cards ADD COLUMN sender_filter TEXT DEFAULT \'\'')
                        elif column_name == 'keyword_filter':
                            db.execute('ALTER TABLE cards ADD COLUMN keyword_filter TEXT DEFAULT \'\'')
                    logger.info(f"Added {column_name} column to cards table")
                    
            else:
                cursor = db.cursor()
                try:
                    if db_type == 'mysql':
                        cursor.execute(f"SHOW COLUMNS FROM cards LIKE '{column_name}'")
                        if not cursor.fetchone():
                            mysql_def = column_def.replace('INTEGER', 'INT').replace('TEXT', 'TEXT')
                            cursor.execute(f'ALTER TABLE cards ADD COLUMN {column_name} {mysql_def}')
                            logger.info(f"Added {column_name} column to cards table")
                    elif db_type == 'postgresql':
                        cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='cards' AND column_name='{column_name}'")
                        if not cursor.fetchone():
                            pg_def = column_def.replace('INTEGER', 'INTEGER').replace('TEXT', 'TEXT')
                            cursor.execute(f'ALTER TABLE cards ADD COLUMN {column_name} {pg_def}')
                            logger.info(f"Added {column_name} column to cards table")
                except Exception as e:
                    logger.error(f"Error checking/adding {column_name} to cards: {e}")
        
        if db_type != 'sqlite':
            db.commit()
        else:
            db.commit()
            
        logger.info("Cards table migration completed successfully")
        
    except Exception as e:
        logger.error(f"Error during cards table migration: {e}")

def assign_unified_ids_to_existing_proxies(db, db_type):
    """为现有代理分配统一ID（按创建时间顺序，确保ID连续）"""
    try:
        # 获取所有需要分配unified_id的代理，按创建时间排序
        all_proxies = []
        
        if db_type == 'sqlite':
            # 获取HTTP代理
            http_proxies = db.execute('SELECT id, created_at FROM http_proxies WHERE unified_id = 0 ORDER BY created_at ASC, id ASC').fetchall()
            for proxy in http_proxies:
                all_proxies.append(('http', proxy['id'], proxy['created_at']))
            
            # 获取SOCKS5代理
            socks5_proxies = db.execute('SELECT id, created_at FROM socks5_proxies WHERE unified_id = 0 ORDER BY created_at ASC, id ASC').fetchall()
            for proxy in socks5_proxies:
                all_proxies.append(('socks5', proxy['id'], proxy['created_at']))
        else:
            cursor = db.cursor()
            # 获取HTTP代理
            cursor.execute('SELECT id, created_at FROM http_proxies WHERE unified_id = 0 ORDER BY created_at ASC, id ASC')
            http_proxies = cursor.fetchall()
            for proxy in http_proxies:
                all_proxies.append(('http', proxy[0], proxy[1]))
                
            # 获取SOCKS5代理
            cursor.execute('SELECT id, created_at FROM socks5_proxies WHERE unified_id = 0 ORDER BY created_at ASC, id ASC')
            socks5_proxies = cursor.fetchall()
            for proxy in socks5_proxies:
                all_proxies.append(('socks5', proxy[0], proxy[1]))
        
        # 按创建时间排序所有代理，确保ID是连续的
        all_proxies.sort(key=lambda x: (x[2], x[1]))  # 按创建时间，然后按ID排序
        
        # 为每个代理分配统一ID
        for proxy_type, proxy_id, created_at in all_proxies:
            unified_id = get_next_unified_proxy_id(db, proxy_type, proxy_id)
            table_name = f'{proxy_type}_proxies'
            update_proxy_unified_id(db, table_name, proxy_id, unified_id)
        
        logger.info(f"Assigned unified IDs to {len(all_proxies)} existing proxies")
        
    except Exception as e:
        logger.error(f"Error assigning unified IDs to existing proxies: {e}")

@app.teardown_appcontext
def close_db(exception):
    """关闭数据库连接 - 优化版本"""
    db = getattr(g, '_database', None)
    if db is not None:
        db_type = app.config['DATABASE_TYPE']
        try:
            if db_type == 'sqlite':
                db.close()
            elif db_type == 'mysql':
                if hasattr(app, '_mysql_pool'):
                    # 返回连接到连接池
                    db.close()
                else:
                    db.close()
            elif db_type == 'postgresql':
                if hasattr(app, '_postgres_pool'):
                    # 返回连接到连接池
                    app._postgres_pool.putconn(db)
                else:
                    db.close()
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")
        finally:
            g._database = None

def get_account_count():
    """获取邮箱账号总数"""
    try:
        db = get_db()
        result = db.execute('SELECT COUNT(*) as count FROM mail_accounts').fetchone()
        return result['count'] if result else 0
    except:
        return 0

def get_card_count():
    """获取卡密总数"""
    try:
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        if db_type == 'sqlite':
            result = db.execute('SELECT COUNT(*) as count FROM cards').fetchone()
            return result['count'] if result else 0
        else:
            cursor = db.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM cards')
            result = cursor.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting card count: {e}")
        return 0

def get_available_proxy_count():
    """获取代理池中可用代理数量（HTTP + SOCKS5）"""
    try:
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        if db_type == 'sqlite':
            # 统计启用状态的HTTP代理
            http_result = db.execute('SELECT COUNT(*) as count FROM http_proxies WHERE status = 1').fetchone()
            http_count = http_result['count'] if http_result else 0
            
            # 统计启用状态的SOCKS5代理
            socks5_result = db.execute('SELECT COUNT(*) as count FROM socks5_proxies WHERE status = 1').fetchone()
            socks5_count = socks5_result['count'] if socks5_result else 0
            
            return http_count + socks5_count
        else:
            cursor = db.cursor()
            # 统计启用状态的HTTP代理
            cursor.execute('SELECT COUNT(*) as count FROM http_proxies WHERE status = 1')
            http_result = cursor.fetchone()
            http_count = http_result[0] if http_result else 0
            
            # 统计启用状态的SOCKS5代理
            cursor.execute('SELECT COUNT(*) as count FROM socks5_proxies WHERE status = 1')
            socks5_result = cursor.fetchone()
            socks5_count = socks5_result[0] if socks5_result else 0
            
            return http_count + socks5_count
    except Exception as e:
        logger.error(f"Error getting available proxy count: {e}")
        return 0

def get_next_unified_proxy_id(db, proxy_type, proxy_table_id):
    """获取下一个统一代理ID"""
    try:
        db_type = app.config['DATABASE_TYPE']
        
        # 插入到统一ID管理表
        if db_type == 'sqlite':
            db.execute('''
                INSERT INTO unified_proxy_ids (proxy_type, proxy_table_id)
                VALUES (?, ?)
            ''', (proxy_type, proxy_table_id))
            # 获取刚插入的ID
            result = db.execute('SELECT last_insert_rowid() as id').fetchone()
            unified_id = result['id']
        else:
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO unified_proxy_ids (proxy_type, proxy_table_id)
                VALUES (%s, %s)
            ''', (proxy_type, proxy_table_id))
            unified_id = cursor.lastrowid
        
        return unified_id
    except Exception as e:
        logger.error(f"Error getting unified proxy ID: {e}")
        raise

def reorder_unified_proxy_ids(db, db_type):
    """重新排序统一代理ID，确保删除后ID连续"""
    try:
        # 首先为没有unified_id的代理分配ID
        assign_unified_ids_to_existing_proxies(db, db_type)
        
        # 获取所有有效的统一ID记录，按创建时间和ID排序
        if db_type == 'sqlite':
            unified_records = db.execute('''
                SELECT upi.id, upi.proxy_type, upi.proxy_table_id, upi.created_at
                FROM unified_proxy_ids upi
                WHERE EXISTS (
                    SELECT 1 FROM http_proxies hp WHERE hp.id = upi.proxy_table_id AND upi.proxy_type = 'http'
                    UNION
                    SELECT 1 FROM socks5_proxies sp WHERE sp.id = upi.proxy_table_id AND upi.proxy_type = 'socks5'
                )
                ORDER BY upi.created_at, upi.id
            ''').fetchall()
        else:
            cursor = db.cursor()
            cursor.execute('''
                SELECT upi.id, upi.proxy_type, upi.proxy_table_id, upi.created_at
                FROM unified_proxy_ids upi
                WHERE EXISTS (
                    SELECT 1 FROM http_proxies hp WHERE hp.id = upi.proxy_table_id AND upi.proxy_type = 'http'
                    UNION
                    SELECT 1 FROM socks5_proxies sp WHERE sp.id = upi.proxy_table_id AND upi.proxy_type = 'socks5'
                )
                ORDER BY upi.created_at, upi.id
            ''')
            unified_records = cursor.fetchall()
        
        # 如果没有记录，直接返回
        if not unified_records:
            logger.info("No proxy records to reorder")
            return
        
        # 创建一个临时表来重新分配ID
        temp_table = 'unified_proxy_ids_temp'
        
        if db_type == 'sqlite':
            # 创建临时表
            db.execute(f'''
                CREATE TABLE {temp_table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proxy_type TEXT NOT NULL,
                    proxy_table_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 按顺序重新插入数据（自动分配新的连续ID）
            for record in unified_records:
                proxy_type = record[1]
                proxy_table_id = record[2]
                created_at = record[3]
                
                db.execute(f'''
                    INSERT INTO {temp_table} (proxy_type, proxy_table_id, created_at)
                    VALUES (?, ?, ?)
                ''', (proxy_type, proxy_table_id, created_at))
            
            # 删除原表并重命名
            db.execute('DROP TABLE unified_proxy_ids')
            db.execute(f'ALTER TABLE {temp_table} RENAME TO unified_proxy_ids')
            
            # 更新代理表中的unified_id
            http_records = db.execute('''
                SELECT upi.id, upi.proxy_table_id 
                FROM unified_proxy_ids upi 
                WHERE upi.proxy_type = 'http'
            ''').fetchall()
            
            for unified_id, proxy_table_id in http_records:
                db.execute('UPDATE http_proxies SET unified_id = ? WHERE id = ?', (unified_id, proxy_table_id))
            
            socks5_records = db.execute('''
                SELECT upi.id, upi.proxy_table_id 
                FROM unified_proxy_ids upi 
                WHERE upi.proxy_type = 'socks5'
            ''').fetchall()
            
            for unified_id, proxy_table_id in socks5_records:
                db.execute('UPDATE socks5_proxies SET unified_id = ? WHERE id = ?', (unified_id, proxy_table_id))
                
        else:
            # MySQL/PostgreSQL处理（类似逻辑）
            cursor = db.cursor()
            
            # 创建临时表
            if db_type == 'mysql':
                cursor.execute(f'''
                    CREATE TABLE {temp_table} (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        proxy_type VARCHAR(50) NOT NULL,
                        proxy_table_id INT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                ''')
            else:  # PostgreSQL
                cursor.execute(f'''
                    CREATE TABLE {temp_table} (
                        id SERIAL PRIMARY KEY,
                        proxy_type VARCHAR(50) NOT NULL,
                        proxy_table_id INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
            # 重新插入数据
            for record in unified_records:
                proxy_type = record[1]
                proxy_table_id = record[2]
                created_at = record[3]
                
                cursor.execute(f'''
                    INSERT INTO {temp_table} (proxy_type, proxy_table_id, created_at)
                    VALUES (%s, %s, %s)
                ''', (proxy_type, proxy_table_id, created_at))
            
            # 删除原表并重命名
            cursor.execute('DROP TABLE unified_proxy_ids')
            cursor.execute(f'ALTER TABLE {temp_table} RENAME TO unified_proxy_ids')
            
            # 更新代理表
            cursor.execute('''
                UPDATE http_proxies hp 
                SET unified_id = (
                    SELECT upi.id FROM unified_proxy_ids upi 
                    WHERE upi.proxy_type = 'http' AND upi.proxy_table_id = hp.id
                )
                WHERE EXISTS (
                    SELECT 1 FROM unified_proxy_ids upi 
                    WHERE upi.proxy_type = 'http' AND upi.proxy_table_id = hp.id
                )
            ''')
            
            cursor.execute('''
                UPDATE socks5_proxies sp 
                SET unified_id = (
                    SELECT upi.id FROM unified_proxy_ids upi 
                    WHERE upi.proxy_type = 'socks5' AND upi.proxy_table_id = sp.id
                )
                WHERE EXISTS (
                    SELECT 1 FROM unified_proxy_ids upi 
                    WHERE upi.proxy_type = 'socks5' AND upi.proxy_table_id = sp.id
                )
            ''')
        
        if db_type != 'sqlite':
            db.commit()
        else:
            db.commit()
            
        logger.info("Proxy unified IDs reordered successfully")
        
    except Exception as e:
        logger.error(f"Error reordering proxy unified IDs: {e}")
        if db_type != 'sqlite':
            try:
                db.rollback()
            except:
                pass

def reorder_mailbox_ids(db, db_type):
    """重新排序邮箱ID，确保删除后ID连续"""
    try:
        # 获取所有邮箱记录，按ID排序确保稳定的顺序
        if db_type == 'sqlite':
            mailboxes = db.execute('SELECT * FROM mail_accounts ORDER BY id ASC').fetchall()
        else:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM mail_accounts ORDER BY id ASC')
            mailboxes = cursor.fetchall()
        
        if not mailboxes:
            return
        
        # 创建临时表来重新插入数据
        temp_table_name = f'mail_accounts_temp_{int(time.time())}'
        
        if db_type == 'sqlite':
            # 创建临时表
            db.execute(f'''
                CREATE TABLE {temp_table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL,
                    server TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    protocol TEXT NOT NULL DEFAULT 'imap',
                    ssl INTEGER NOT NULL DEFAULT 1,
                    remarks TEXT DEFAULT '',
                    status INTEGER DEFAULT 1,
                    last_test DATETIME DEFAULT NULL,
                    test_result TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 重新插入数据（ID将自动重新排序）
            for mailbox in mailboxes:
                mailbox_dict = dict(mailbox)
                db.execute(f'''
                    INSERT INTO {temp_table_name} 
                    (email, username, password, server, port, protocol, ssl, remarks, status, last_test, test_result, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    mailbox_dict['email'], mailbox_dict['username'], mailbox_dict['password'],
                    mailbox_dict['server'], mailbox_dict['port'], mailbox_dict['protocol'],
                    mailbox_dict['ssl'], mailbox_dict['remarks'], mailbox_dict['status'],
                    mailbox_dict['last_test'], mailbox_dict['test_result'],
                    mailbox_dict['created_at'], mailbox_dict['updated_at']
                ))
            
            # 删除原表并重命名临时表
            db.execute('DROP TABLE mail_accounts')
            db.execute(f'ALTER TABLE {temp_table_name} RENAME TO mail_accounts')
            
        else:
            # MySQL/PostgreSQL处理方式
            cursor = db.cursor()
            
            # 创建临时表
            if db_type == 'mysql':
                cursor.execute(f'''
                    CREATE TABLE {temp_table_name} (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        email VARCHAR(255) NOT NULL UNIQUE,
                        username TEXT NOT NULL,
                        password TEXT NOT NULL,
                        server TEXT NOT NULL,
                        port INT NOT NULL,
                        protocol VARCHAR(50) NOT NULL DEFAULT 'imap',
                        ssl TINYINT NOT NULL DEFAULT 1,
                        remarks TEXT DEFAULT '',
                        status TINYINT DEFAULT 1,
                        last_test DATETIME DEFAULT NULL,
                        test_result TEXT DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                ''')
            else:  # PostgreSQL
                cursor.execute(f'''
                    CREATE TABLE {temp_table_name} (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) NOT NULL UNIQUE,
                        username TEXT NOT NULL,
                        password TEXT NOT NULL,
                        server TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        protocol VARCHAR(50) NOT NULL DEFAULT 'imap',
                        ssl INTEGER NOT NULL DEFAULT 1,
                        remarks TEXT DEFAULT '',
                        status INTEGER DEFAULT 1,
                        last_test TIMESTAMP DEFAULT NULL,
                        test_result TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
            # 重新插入数据
            for mailbox in mailboxes:
                cursor.execute(f'''
                    INSERT INTO {temp_table_name} 
                    (email, username, password, server, port, protocol, ssl, remarks, status, last_test, test_result, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', mailbox[1:])  # 跳过原有的ID
            
            # 删除原表并重命名临时表
            cursor.execute('DROP TABLE mail_accounts')
            cursor.execute(f'ALTER TABLE {temp_table_name} RENAME TO mail_accounts')
            
        if db_type != 'sqlite':
            db.commit()
        else:
            db.commit()
            
        logger.info("Mailbox IDs reordered successfully")
        
    except Exception as e:
        logger.error(f"Error reordering mailbox IDs: {e}")
        if db_type != 'sqlite':
            try:
                db.rollback()
            except:
                pass

def update_proxy_unified_id(db, table_name, proxy_id, unified_id):
    """更新代理的统一ID"""
    try:
        db_type = app.config['DATABASE_TYPE']
        
        if db_type == 'sqlite':
            db.execute(f'''
                UPDATE {table_name} SET unified_id = ? WHERE id = ?
            ''', (unified_id, proxy_id))
        else:
            cursor = db.cursor()
            cursor.execute(f'''
                UPDATE {table_name} SET unified_id = %s WHERE id = %s
            ''', (unified_id, proxy_id))
            
    except Exception as e:
        logger.error(f"Error updating proxy unified ID: {e}")
        raise

# ===============================
# 前端页面路由
# ===============================

@app.route('/')
def index():
    """前端首页 - 邮件查看"""
    frontend_title = get_system_config('frontend_page_title', '邮件查看系统')
    return render_template('frontend/index.html', page_title=frontend_title)

# ===============================
# 管理员认证相关路由
# ===============================

@app.route('/admin')
@app.route('/admin/')
def admin_index():
    """管理员后台入口"""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_home'))
    return redirect(url_for('admin_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """管理员登录"""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_home'))
    
    error = ''
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if username and password:
            try:
                db = get_db()
                admin = db.execute('SELECT * FROM admin_users WHERE username = ?', (username,)).fetchone()
                
                # 密码验证（支持兼容性检查）
                if admin:
                    # 检查是否为新的加密密码格式
                    if admin['password'].startswith('pbkdf2:') or admin['password'].startswith('scrypt:'):
                        # 使用werkzeug验证加密密码
                        if check_password_hash(admin['password'], password):
                            session['admin_logged_in'] = True
                            session['admin_id'] = admin['id']
                            session['admin_username'] = admin['username']
                            return redirect(url_for('admin_home'))
                        else:
                            error = '用户名或密码错误'
                    else:
                        # 兼容原有明文密码
                        if admin['password'] == password:
                            session['admin_logged_in'] = True
                            session['admin_id'] = admin['id']
                            session['admin_username'] = admin['username']
                            return redirect(url_for('admin_home'))
                        else:
                            error = '用户名或密码错误'
                else:
                    error = '用户名或密码错误'
            except Exception as e:
                error = f'数据库连接失败：{str(e)}'
        else:
            error = '请输入用户名和密码'
    
    return render_template('admin/login.html', error=error, page_title=get_system_config('admin_login_title', '管理员登录'))

@app.route('/admin/logout')
def admin_logout():
    """管理员退出登录"""
    session.clear()
    return redirect(url_for('admin_login'))

def admin_required(f):
    """管理员权限装饰器"""
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def get_system_config(key, default_value=''):
    """获取系统配置值"""
    try:
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        if db_type == 'sqlite':
            result = db.execute('SELECT config_value FROM system_config WHERE config_key = ?', (key,)).fetchone()
            return result['config_value'] if result else default_value
        else:
            cursor = db.cursor()
            cursor.execute('SELECT config_value FROM system_config WHERE config_key = %s', (key,))
            result = cursor.fetchone()
            return result[0] if result else default_value
    except Exception as e:
        logger.error(f"Failed to get system config for key {key}: {e}")
        return default_value

@app.context_processor
def inject_system_title():
    """注入系统标题到所有模板"""
    return {
        'system_title': get_system_config('system_title', '邮件查看系统')
    }

# ===============================
# 管理员后台页面路由
# ===============================

@app.route('/admin/home')
@admin_required
def admin_home():
    """管理员首页"""
    account_count = get_account_count()
    card_count = get_card_count()
    available_proxy_count = get_available_proxy_count()
    return render_template('admin/home.html', 
                         admin_username=session.get('admin_username'),
                         account_count=account_count,
                         card_count=card_count,
                         available_proxy_count=available_proxy_count)

@app.route('/admin/mailbox')
@admin_required
def admin_mailbox():
    """邮箱管理页面"""
    return render_template('admin/mailbox.html',
                         admin_username=session.get('admin_username'))

@app.route('/admin/daili')
@admin_required
def admin_daili():
    """代理池管理页面"""
    return render_template('admin/daili.html',
                         admin_username=session.get('admin_username'))

@app.route('/admin/kami')
@admin_required
def admin_kami():
    """卡密管理页面"""
    return render_template('admin/kami.html',
                         admin_username=session.get('admin_username'))

@app.route('/admin/kamirizhi')
@admin_required
def admin_kamirizhi():
    """卡密日志页面"""
    return render_template('admin/kamirizhi.html',
                         admin_username=session.get('admin_username'))

@app.route('/admin/shoujian')
@admin_required
def admin_shoujian():
    """收件日志页面"""
    return render_template('admin/shoujian.html',
                         admin_username=session.get('admin_username'))

@app.route('/admin/system')
@admin_required
def admin_system():
    """系统设置页面"""
    return render_template('admin/system.html',
                         admin_username=session.get('admin_username'))

# ===============================
# API 接口路由
# ===============================

@app.route('/api/check_login', methods=['GET'])
def api_check_login():
    """检查管理员登录状态 API"""
    try:
        logged_in = session.get('admin_logged_in', False)
        admin_username = session.get('admin_username', '')
        
        return jsonify({
            'success': True,
            'logged_in': logged_in,
            'admin_username': admin_username
        })
    except Exception as e:
        logger.error(f"Check login error: {e}")
        return jsonify({
            'success': False,
            'logged_in': False,
            'message': f'检查登录状态失败: {str(e)}'
        })

@app.route('/api/get_mail', methods=['POST'])
def api_get_mail():
    """获取邮件 API（增强版本 - 支持卡密验证和管理员免卡密访问）"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据无效'
            })
            
        email = data.get('email', '').strip()
        card_key = data.get('card_key', '') or request.headers.get('X-Card-Key', '')
        admin_access = data.get('admin_access', False)
        
        # 验证请求参数
        if not email:
            return jsonify({
                'success': False,
                'message': '请提供邮箱地址'
            })
        
        # 检查是否为管理员访问
        is_admin = session.get('admin_logged_in', False) and admin_access
        
        if not is_admin and not card_key:
            return jsonify({
                'success': False,
                'message': '请提供卡密或使用管理员登录'
            })
        
        # 获取数据库连接
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        if is_admin:
            # 管理员访问：直接调用邮件获取器，无需卡密验证
            try:
                # 调用Python邮件获取器脚本
                script_args = [
                    sys.executable, 
                    os.path.join(os.path.dirname(__file__), 'python', 'mail_fetcher.py'),
                    email,
                    '--admin-access'  # 标记为管理员访问
                ]
                
                result = subprocess.run(script_args, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    # 解析JSON输出
                    response_data = json.loads(result.stdout)
                    
                    if response_data.get('success'):
                        # 记录管理员访问日志
                        user_ip = request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR') or 'unknown'
                        admin_username = session.get('admin_username', 'unknown')
                        
                        if db_type == 'sqlite':
                            db.execute('''
                                INSERT INTO admin_mail_logs (admin_username, email, user_ip, action, result, created_at)
                                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                            ''', (admin_username, email, user_ip, 'admin_get_mail', 
                                  f'管理员获取邮件: {response_data.get("mail", {}).get("subject", "无主题")}'))
                            db.commit()
                        else:
                            cursor = db.cursor()
                            cursor.execute('''
                                INSERT INTO admin_mail_logs (admin_username, email, user_ip, action, result, created_at)
                                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                            ''', (admin_username, email, user_ip, 'admin_get_mail', 
                                  f'管理员获取邮件: {response_data.get("mail", {}).get("subject", "无主题")}'))
                            db.commit()
                    
                    return jsonify(response_data)
                else:
                    return jsonify({
                        'success': False,
                        'message': f'邮件获取失败: {result.stderr or "未知错误"}'
                    })
                    
            except subprocess.TimeoutExpired:
                return jsonify({
                    'success': False,
                    'message': '邮件获取超时，请稍后重试'
                })
            except json.JSONDecodeError:
                return jsonify({
                    'success': False,
                    'message': '邮件服务响应格式错误'
                })
            except Exception as e:
                logger.error(f"Admin mail access error: {e}")
                return jsonify({
                    'success': False,
                    'message': f'管理员邮件获取错误: {str(e)}'
                })
        else:
            # 原有的卡密验证逻辑保持不变
            try:
                # 查询卡密信息
                if db_type == 'sqlite':
                    card_result = db.execute('''
                        SELECT c.*, e.email as bound_email, e.server, e.username, e.password, 
                               e.port, e.protocol, e.ssl
                        FROM cards c 
                        LEFT JOIN mail_accounts e ON c.bound_email_id = e.id 
                        WHERE c.card_key = ?
                    ''', (card_key,)).fetchone()
                else:
                    cursor = db.cursor()
                    cursor.execute('''
                        SELECT c.*, e.email as bound_email, e.server, e.username, e.password, 
                               e.port, e.protocol, e.ssl
                        FROM cards c 
                        LEFT JOIN mail_accounts e ON c.bound_email_id = e.id 
                        WHERE c.card_key = %s
                    ''', (card_key,))
                    card_result = cursor.fetchone()
                
                if not card_result:
                    return jsonify({
                        'success': False,
                        'message': '卡密不存在或已失效'
                    })
                
                # 转换为字典
                if db_type == 'sqlite':
                    card_info = dict(card_result)
                else:
                    columns = [desc[0] for desc in cursor.description]
                    card_info = dict(zip(columns, card_result))
                
                # 验证卡密状态
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # 检查卡密是否启用
                if card_info['status'] != 1:
                    return jsonify({
                        'success': False,
                        'message': '卡密已被禁用'
                    })
                
                # 检查是否已过期
                if card_info['expired_at'] and card_info['expired_at'] <= now:
                    return jsonify({
                        'success': False,
                        'message': '卡密已过期'
                    })
                
                # 检查使用次数是否已用完
                if card_info['used_count'] >= card_info['usage_limit']:
                    return jsonify({
                        'success': False,
                        'message': '卡密使用次数已用完'
                    })
                
                # 如果卡密绑定了邮箱，检查邮箱是否匹配
                if card_info['bound_email_id'] and card_info['bound_email']:
                    if email != card_info['bound_email']:
                        return jsonify({
                            'success': False,
                            'message': f'此卡密只能用于邮箱: {card_info["bound_email"]}'
                        })
                    # 使用绑定邮箱信息直接获取邮件
                    use_bound_email = True
                else:
                    # 如果没有绑定邮箱，需要在数据库中查找邮箱配置
                    use_bound_email = False
                
                # 调用Python邮件获取器脚本，传递卡密过滤参数
                script_args = [
                    sys.executable, 
                    os.path.join(os.path.dirname(__file__), 'python', 'mail_fetcher.py'),
                    email
                ]
                
                # 添加卡密过滤参数
                if card_info.get('email_days_filter'):
                    script_args.extend(['--days-filter', str(card_info['email_days_filter'])])
                
                if card_info.get('sender_filter'):
                    script_args.extend(['--sender-filter', card_info['sender_filter']])
                
                if card_info.get('keyword_filter'):
                    script_args.extend(['--keyword-filter', card_info['keyword_filter']])
                
                # 添加卡密标识用于后续处理
                script_args.extend(['--card-key', card_key])
                
                result = subprocess.run(script_args, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    # 解析JSON输出
                    response_data = json.loads(result.stdout)
                    
                    # 如果邮件获取成功，更新卡密使用次数
                    if response_data.get('success') and response_data.get('mail'):
                        # 增加使用次数
                        new_used_count = card_info['used_count'] + 1
                        
                        # 记录使用日志
                        user_ip = request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR') or 'unknown'
                        user_agent = request.headers.get('User-Agent', 'unknown')
                        
                        if db_type == 'sqlite':
                            # 更新卡密使用次数
                            db.execute('''
                                UPDATE cards SET used_count = ?, updated_at = CURRENT_TIMESTAMP 
                                WHERE id = ?
                            ''', (new_used_count, card_info['id']))
                            
                            # 检查卡密是否已用完，如果用完则移动到回收站
                            if new_used_count >= card_info['usage_limit']:
                                # 将卡密移动到回收站
                                move_card_to_recycle_bin(db, db_type, card_info['id'], 'expired', '使用次数已用完')
                                logger.info(f"Card {card_key} moved to recycle bin (usage limit reached)")
                            else:
                                # 插入使用日志（仅在未过期时）
                                db.execute('''
                                    INSERT INTO card_logs (card_id, card_key, user_ip, user_agent, action, result, created_at)
                                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                                ''', (card_info['id'], card_key, user_ip, user_agent, 'use', 
                                      f'成功获取邮件: {response_data["mail"]["subject"]}'))
                            
                            db.commit()
                        else:
                            cursor = db.cursor()
                            # 更新卡密使用次数
                            cursor.execute('''
                                UPDATE cards SET used_count = %s, updated_at = CURRENT_TIMESTAMP 
                                WHERE id = %s
                            ''', (new_used_count, card_info['id']))
                            
                            # 检查卡密是否已用完，如果用完则移动到回收站
                            if new_used_count >= card_info['usage_limit']:
                                # 将卡密移动到回收站
                                move_card_to_recycle_bin(db, db_type, card_info['id'], 'expired', '使用次数已用完')
                                logger.info(f"Card {card_key} moved to recycle bin (usage limit reached)")
                            else:
                                # 插入使用日志（仅在未过期时）
                                cursor.execute('''
                                    INSERT INTO card_logs (card_id, card_key, user_ip, user_agent, action, result, created_at)
                                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                                ''', (card_info['id'], card_key, user_ip, user_agent, 'use', 
                                      f'成功获取邮件: {response_data["mail"]["subject"]}'))
                            
                            db.commit()
                        
                        # 更新响应数据，包含剩余使用次数
                        response_data['card_info'] = {
                            'remaining_uses': card_info['usage_limit'] - new_used_count,
                            'total_uses': card_info['usage_limit'],
                            'used_count': new_used_count
                        }
                    
                    return jsonify(response_data)
                else:
                    return jsonify({
                        'success': False,
                        'message': f'邮件获取失败: {result.stderr or "未知错误"}'
                    })
                    
            except subprocess.TimeoutExpired:
                return jsonify({
                    'success': False,
                    'message': '邮件获取超时，请稍后重试'
                })
            except json.JSONDecodeError:
                return jsonify({
                    'success': False,
                    'message': '邮件服务响应格式错误'
                })
            except Exception as e:
                logger.error(f"Database or processing error in get_mail: {e}")
                return jsonify({
                    'success': False,
                    'message': f'邮件服务错误: {str(e)}'
                })
                
    except Exception as e:
        logger.error(f"General error in get_mail: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        })

def move_card_to_recycle_bin(db, db_type, card_id, recycle_type='deleted', reason=''):
    """将卡密移动到回收站"""
    try:
        # 获取卡密信息
        if db_type == 'sqlite':
            card = db.execute('SELECT * FROM cards WHERE id = ?', (card_id,)).fetchone()
        else:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM cards WHERE id = %s', (card_id,))
            card = cursor.fetchone()
        
        if not card:
            return False, '卡密不存在'
        
        # 转换为字典
        if db_type == 'sqlite':
            card_data = dict(card)
        else:
            columns = [desc[0] for desc in cursor.description]
            card_data = dict(zip(columns, card))
        
        # 插入到回收站
        now = get_beijing_time()  # 使用北京时间
        if db_type == 'sqlite':
            db.execute('''
                INSERT INTO card_recycle_bin (original_card_id, card_key, usage_limit, used_count, 
                                            expired_at, bound_email_id, email_days_filter, sender_filter, 
                                            remarks, status, recycle_type, reason, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (card_data['id'], card_data['card_key'], card_data['usage_limit'], 
                  card_data['used_count'], card_data['expired_at'], card_data['bound_email_id'],
                  card_data['email_days_filter'], card_data['sender_filter'], card_data['remarks'],
                  card_data['status'], recycle_type, reason, card_data['created_at'], 
                  card_data['updated_at'], now))
            
            # 从主表删除
            db.execute('DELETE FROM cards WHERE id = ?', (card_id,))
        else:
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO card_recycle_bin (original_card_id, card_key, usage_limit, used_count, 
                                            expired_at, bound_email_id, email_days_filter, sender_filter, 
                                            remarks, status, recycle_type, reason, created_at, updated_at, deleted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (card_data['id'], card_data['card_key'], card_data['usage_limit'], 
                  card_data['used_count'], card_data['expired_at'], card_data['bound_email_id'],
                  card_data['email_days_filter'], card_data['sender_filter'], card_data['remarks'],
                  card_data['status'], recycle_type, reason, card_data['created_at'], 
                  card_data['updated_at'], now))
            
            # 从主表删除
            cursor.execute('DELETE FROM cards WHERE id = %s', (card_id,))
        
        return True, '成功移动到回收站'
        
    except Exception as e:
        logger.error(f"Move card to recycle bin error: {e}")
        return False, f'移动到回收站失败: {str(e)}'

def process_expired_cards():
    """处理过期的卡密，将其移动到回收站"""
    try:
        with app.app_context():
            db = get_db()
            db_type = app.config['DATABASE_TYPE']
            now = get_beijing_time()  # 使用北京时间
            
            # 查找所有过期的卡密
            if db_type == 'sqlite':
                expired_cards = db.execute('''
                    SELECT id, card_key FROM cards 
                    WHERE expired_at IS NOT NULL AND expired_at <= ?
                ''', (now,)).fetchall()
            else:
                cursor = db.cursor()
                cursor.execute('''
                    SELECT id, card_key FROM cards 
                    WHERE expired_at IS NOT NULL AND expired_at <= %s
                ''', (now,))
                expired_cards = cursor.fetchall()
            
            if expired_cards:
                moved_count = 0
                for card in expired_cards:
                    card_id = card['id'] if db_type == 'sqlite' else card[0]
                    card_key = card['card_key'] if db_type == 'sqlite' else card[1]
                    
                    success, message = move_card_to_recycle_bin(db, db_type, card_id, 'expired', '到期时间已过')
                    if success:
                        moved_count += 1
                        logger.info(f"Expired card {card_key} moved to recycle bin")
                    else:
                        logger.error(f"Failed to move expired card {card_key}: {message}")
                
                if moved_count > 0:
                    db.commit()
                    logger.info(f"Moved {moved_count} expired cards to recycle bin")
            
    except Exception as e:
        logger.error(f"Process expired cards error: {e}")

@app.route('/admin/api/mailbox', methods=['GET', 'POST', 'DELETE'])
@admin_required
def api_admin_mailbox():
    """邮箱管理 API（增强版）"""
    db = get_db()
    db_type = app.config['DATABASE_TYPE']
    
    if request.method == 'GET':
        # 获取邮箱列表（支持分页和搜索）
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search = request.args.get('search', '').strip()
        
        offset = (page - 1) * per_page
        
        # 构建查询条件
        where_clause = ""
        params = []
        if search:
            where_clause = "WHERE email LIKE ? OR server LIKE ? OR remarks LIKE ?"
            search_param = f"%{search}%"
            params = [search_param, search_param, search_param]
        
        # 获取总数
        if db_type == 'sqlite':
            count_sql = f"SELECT COUNT(*) as count FROM mail_accounts {where_clause}"
            count_result = db.execute(count_sql, params).fetchone()
            total = count_result['count']
            
            # 获取分页数据 - 按ID排序确保ID稳定显示
            sql = f"""
                SELECT * FROM mail_accounts {where_clause}
                ORDER BY id ASC 
                LIMIT ? OFFSET ?
            """
            accounts = db.execute(sql, params + [per_page, offset]).fetchall()
        else:
            cursor = db.cursor()
            if db_type == 'mysql':
                placeholder = '%s'
            else:  # postgresql
                placeholder = '%s'
            
            where_mysql = where_clause.replace('?', placeholder) if where_clause else ""
            count_sql = f"SELECT COUNT(*) as count FROM mail_accounts {where_mysql}"
            cursor.execute(count_sql, params)
            total = cursor.fetchone()['count'] if db_type == 'postgresql' else cursor.fetchone()[0]
            
            sql = f"""
                SELECT * FROM mail_accounts {where_mysql}
                ORDER BY id ASC 
                LIMIT {per_page} OFFSET {offset}
            """
            cursor.execute(sql, params)
            accounts = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'data': [dict(account) for account in accounts],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    
    elif request.method == 'POST':
        # 添加或编辑邮箱
        data = request.get_json()
        action = data.get('action')
        
        if action == 'add':
            return _add_mailbox(db, data)
        elif action == 'batch_add':
            return _batch_add_mailbox(db, data)
        elif action == 'edit':
            return _edit_mailbox(db, data)
        elif action == 'test':
            return _test_mailbox(db, data)
        elif action == 'test_new':
            return _test_new_mailbox(data)
        elif action == 'batch_delete':
            return _batch_delete_mailbox(db, data)
    
    elif request.method == 'DELETE':
        # 删除邮箱
        data = request.get_json()
        account_id = data.get('id')
        
        if not account_id:
            return jsonify({
                'success': False,
                'message': '缺少邮箱ID'
            })
        
        try:
            if app.config['DATABASE_TYPE'] == 'sqlite':
                db.execute('DELETE FROM mail_accounts WHERE id = ?', (account_id,))
                db.commit()
            else:
                cursor = db.cursor()
                cursor.execute('DELETE FROM mail_accounts WHERE id = %s', (account_id,))
                db.commit()
            
            return jsonify({
                'success': True,
                'message': '邮箱删除成功'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'删除失败: {str(e)}'
            })

def _add_mailbox(db, data):
    """添加单个邮箱"""
    email = data.get('email', '').strip()
    username = email  # 使用邮箱作为用户名
    password = data.get('password', '').strip()
    server = data.get('server', '').strip()
    port = int(data.get('port', 0))
    protocol = data.get('protocol', 'imap')
    ssl = 1 if data.get('ssl') else 0
    remarks = data.get('remarks', '').strip()
    
    if not all([email, password, server, port]):
        return jsonify({
            'success': False,
            'message': '请填写所有必需字段'
        })
    
    try:
        # 检查邮箱是否已存在
        if app.config['DATABASE_TYPE'] == 'sqlite':
            existing = db.execute('SELECT id FROM mail_accounts WHERE email = ?', (email,)).fetchone()
        else:
            cursor = db.cursor()
            cursor.execute('SELECT id FROM mail_accounts WHERE email = %s', (email,))
            existing = cursor.fetchone()
            
        if existing:
            return jsonify({
                'success': False,
                'message': '邮箱已存在'
            })
        
        # 插入新邮箱
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if app.config['DATABASE_TYPE'] == 'sqlite':
            db.execute('''
                INSERT INTO mail_accounts (email, username, password, server, port, protocol, ssl, remarks, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (email, username, password, server, port, protocol, ssl, remarks, now, now))
            db.commit()
        else:
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO mail_accounts (email, username, password, server, port, protocol, ssl, remarks, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (email, username, password, server, port, protocol, ssl, remarks, now, now))
            db.commit()
        
        return jsonify({
            'success': True,
            'message': '邮箱添加成功'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'添加失败: {str(e)}'
        })

def _batch_add_mailbox(db, data):
    """批量添加邮箱"""
    batch_content = data.get('batch_content', '').strip()
    server = data.get('server', '').strip()
    port = int(data.get('port', 0))
    protocol = data.get('protocol', 'imap')
    ssl = 1 if data.get('ssl') else 0
    remarks = data.get('remarks', '').strip()
    
    if not batch_content or not server or not port:
        return jsonify({
            'success': False,
            'message': '请填写批量内容和服务器信息'
        })
    
    # 解析批量内容（格式：账号----密码）
    lines = batch_content.split('\n')
    success_count = 0
    error_count = 0
    errors = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if '----' not in line:
            error_count += 1
            errors.append(f'格式错误：{line}')
            continue
        
        try:
            email, password = line.split('----', 1)
            email = email.strip()
            password = password.strip()
            
            if not email or not password:
                error_count += 1
                errors.append(f'账号或密码为空：{line}')
                continue
            
            # 检查邮箱是否已存在
            if app.config['DATABASE_TYPE'] == 'sqlite':
                existing = db.execute('SELECT id FROM mail_accounts WHERE email = ?', (email,)).fetchone()
            else:
                cursor = db.cursor()
                cursor.execute('SELECT id FROM mail_accounts WHERE email = %s', (email,))
                existing = cursor.fetchone()
                
            if existing:
                error_count += 1
                errors.append(f'邮箱已存在：{email}')
                continue
            
            # 插入邮箱
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if app.config['DATABASE_TYPE'] == 'sqlite':
                db.execute('''
                    INSERT INTO mail_accounts (email, username, password, server, port, protocol, ssl, remarks, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (email, email, password, server, port, protocol, ssl, remarks, now, now))
            else:
                cursor = db.cursor()
                cursor.execute('''
                    INSERT INTO mail_accounts (email, username, password, server, port, protocol, ssl, remarks, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (email, email, password, server, port, protocol, ssl, remarks, now, now))
            
            success_count += 1
            
        except Exception as e:
            error_count += 1
            errors.append(f'处理失败：{line} - {str(e)}')
    
    try:
        db.commit()
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'数据库提交失败: {str(e)}'
        })
    
    message = f'批量添加完成：成功 {success_count} 个，失败 {error_count} 个'
    if errors:
        message += f'\n错误详情：\n' + '\n'.join(errors[:10])  # 只显示前10个错误
    
    return jsonify({
        'success': True,
        'message': message,
        'details': {
            'success_count': success_count,
            'error_count': error_count,
            'errors': errors
        }
    })

def _edit_mailbox(db, data):
    """编辑邮箱"""
    account_id = data.get('id')
    if not account_id:
        return jsonify({
            'success': False,
            'message': '缺少邮箱ID'
        })
    
    # 更新邮箱信息
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    server = data.get('server', '').strip()
    port = int(data.get('port', 0))
    protocol = data.get('protocol', 'imap')
    ssl = 1 if data.get('ssl') else 0
    remarks = data.get('remarks', '').strip()
    
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if app.config['DATABASE_TYPE'] == 'sqlite':
            db.execute('''
                UPDATE mail_accounts 
                SET email=?, username=?, password=?, server=?, port=?, protocol=?, ssl=?, remarks=?, updated_at=?
                WHERE id=?
            ''', (email, email, password, server, port, protocol, ssl, remarks, now, account_id))
            db.commit()
        else:
            cursor = db.cursor()
            cursor.execute('''
                UPDATE mail_accounts 
                SET email=%s, username=%s, password=%s, server=%s, port=%s, protocol=%s, ssl=%s, remarks=%s, updated_at=%s
                WHERE id=%s
            ''', (email, email, password, server, port, protocol, ssl, remarks, now, account_id))
            db.commit()
        
        return jsonify({
            'success': True,
            'message': '邮箱更新成功'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'更新失败: {str(e)}'
        })

def _test_mailbox(db, data):
    """测试邮箱连接"""
    account_id = data.get('id')
    
    try:
        # 获取邮箱信息
        if app.config['DATABASE_TYPE'] == 'sqlite':
            account = db.execute('SELECT * FROM mail_accounts WHERE id = ?', (account_id,)).fetchone()
        else:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM mail_accounts WHERE id = %s', (account_id,))
            account = cursor.fetchone()
        
        if not account:
            return jsonify({
                'success': False,
                'message': '邮箱不存在'
            })
        
        # 调用Python邮件获取器进行测试
        try:
            if app.config['DATABASE_TYPE'] == 'sqlite':
                account_dict = dict(account)
            else:
                columns = [desc[0] for desc in cursor.description]
                account_dict = dict(zip(columns, account))
            
            result = subprocess.run([
                sys.executable, 
                os.path.join(os.path.dirname(__file__), 'python', 'mail_fetcher.py'),
                account_dict['email'],
                '--test-connection'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # 解析JSON输出
                test_result = json.loads(result.stdout)
                test_success = test_result.get('success', False)
                test_message = test_result.get('message', '测试完成')
                
                # 更新测试结果
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if app.config['DATABASE_TYPE'] == 'sqlite':
                    db.execute('''
                        UPDATE mail_accounts 
                        SET last_test=?, test_result=?
                        WHERE id=?
                    ''', (now, test_message, account_id))
                    db.commit()
                else:
                    cursor = db.cursor()
                    cursor.execute('''
                        UPDATE mail_accounts 
                        SET last_test=%s, test_result=%s
                        WHERE id=%s
                    ''', (now, test_message, account_id))
                    db.commit()
                
                return jsonify({
                    'success': test_success,
                    'message': test_message,
                    'proxy_info': test_result.get('proxy', {}),
                    'diagnostics': test_result.get('diagnostics', {})
                })
            else:
                error_message = result.stderr or "邮箱测试失败"
                
                # 更新测试结果
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if app.config['DATABASE_TYPE'] == 'sqlite':
                    db.execute('''
                        UPDATE mail_accounts 
                        SET last_test=?, test_result=?
                        WHERE id=?
                    ''', (now, error_message, account_id))
                    db.commit()
                else:
                    cursor = db.cursor()
                    cursor.execute('''
                        UPDATE mail_accounts 
                        SET last_test=%s, test_result=%s
                        WHERE id=%s
                    ''', (now, error_message, account_id))
                    db.commit()
                
                return jsonify({
                    'success': False,
                    'message': error_message
                })
                
        except subprocess.TimeoutExpired:
            return jsonify({
                'success': False,
                'message': '邮箱连接测试超时，请检查网络连接或服务器配置'
            })
        except json.JSONDecodeError:
            return jsonify({
                'success': False,
                'message': '邮箱测试服务响应格式错误'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'邮箱测试服务错误: {str(e)}'
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'测试失败: {str(e)}'
        })

def _test_new_mailbox(data):
    """测试新邮箱连接（无需保存到数据库）"""
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    server = data.get('server', '').strip()
    port = int(data.get('port', 0))
    protocol = data.get('protocol', 'imap')
    ssl = data.get('ssl', True)
    
    if not all([email, password, server, port]):
        return jsonify({
            'success': False,
            'message': '请填写完整的邮箱信息'
        })
    
    try:
        # 临时保存邮箱信息到数据库进行测试
        with app.app_context():
            db = get_db()
            temp_email = f"temp_test_{email}_{int(time.time())}"
            
            # 插入临时邮箱记录
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if app.config['DATABASE_TYPE'] == 'sqlite':
                db.execute('''
                    INSERT INTO mail_accounts (email, username, password, server, port, protocol, ssl, remarks, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (temp_email, email, password, server, port, protocol, 1 if ssl else 0, '临时测试邮箱', now, now))
                db.commit()
            else:
                cursor = db.cursor()
                cursor.execute('''
                    INSERT INTO mail_accounts (email, username, password, server, port, protocol, ssl, remarks, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (temp_email, email, password, server, port, protocol, 1 if ssl else 0, '临时测试邮箱', now, now))
                db.commit()
            
            try:
                # 调用Python邮件获取器进行测试
                result = subprocess.run([
                    sys.executable, 
                    os.path.join(os.path.dirname(__file__), 'python', 'mail_fetcher.py'),
                    temp_email,
                    '--test-connection'
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    # 解析JSON输出
                    test_result = json.loads(result.stdout)
                    test_success = test_result.get('success', False)
                    test_message = test_result.get('message', '测试完成')
                    
                    return jsonify({
                        'success': test_success,
                        'message': test_message,
                        'proxy_info': test_result.get('proxy', {}),
                        'diagnostics': test_result.get('diagnostics', {})
                    })
                else:
                    error_message = result.stderr or "邮箱测试失败"
                    return jsonify({
                        'success': False,
                        'message': error_message
                    })
                    
            except subprocess.TimeoutExpired:
                return jsonify({
                    'success': False,
                    'message': '邮箱连接测试超时'
                })
            except json.JSONDecodeError:
                return jsonify({
                    'success': False,
                    'message': '邮箱测试服务响应格式错误'
                })
            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': f'邮箱测试服务错误: {str(e)}'
                })
                
            finally:
                # 删除临时邮箱记录
                try:
                    if app.config['DATABASE_TYPE'] == 'sqlite':
                        db.execute('DELETE FROM mail_accounts WHERE email = ?', (temp_email,))
                        db.commit()
                    else:
                        cursor = db.cursor()
                        cursor.execute('DELETE FROM mail_accounts WHERE email = %s', (temp_email,))
                        db.commit()
                except:
                    pass  # 忽略删除错误
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'测试失败: {str(e)}'
        })

def _batch_delete_mailbox(db, data):
    """批量删除邮箱"""
    account_ids = data.get('ids', [])
    
    if not account_ids:
        return jsonify({
            'success': False,
            'message': '请选择要删除的邮箱'
        })
    
    try:
        if app.config['DATABASE_TYPE'] == 'sqlite':
            placeholders = ','.join(['?' for _ in account_ids])
            db.execute(f'DELETE FROM mail_accounts WHERE id IN ({placeholders})', account_ids)
            db.commit()
        else:
            cursor = db.cursor()
            placeholders = ','.join(['%s' for _ in account_ids])
            cursor.execute(f'DELETE FROM mail_accounts WHERE id IN ({placeholders})', account_ids)
            db.commit()
        
        return jsonify({
            'success': True,
            'message': f'成功删除 {len(account_ids)} 个邮箱'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'批量删除失败: {str(e)}'
        })

@app.route('/admin/api/servers', methods=['GET', 'POST', 'DELETE'])
@admin_required
def api_admin_servers():
    """服务器地址管理 API"""
    db = get_db()
    db_type = app.config['DATABASE_TYPE']
    
    if request.method == 'GET':
        # 获取服务器列表
        if db_type == 'sqlite':
            servers = db.execute('SELECT * FROM server_addresses ORDER BY created_at DESC').fetchall()
        else:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM server_addresses ORDER BY created_at DESC')
            servers = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'data': [dict(server) for server in servers]
        })
    
    elif request.method == 'POST':
        data = request.get_json()
        action = data.get('action')
        
        if action == 'add':
            server_name = data.get('server_name', '').strip()
            server_address = data.get('server_address', '').strip()
            default_port_imap = int(data.get('default_port_imap', 993))
            default_port_pop3 = int(data.get('default_port_pop3', 995))
            ssl_enabled = 1 if data.get('ssl_enabled') else 0
            remarks = data.get('remarks', '').strip()
            
            if not all([server_name, server_address]):
                return jsonify({
                    'success': False,
                    'message': '请填写服务器名称和地址'
                })
            
            try:
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if db_type == 'sqlite':
                    db.execute('''
                        INSERT INTO server_addresses (server_name, server_address, default_port_imap, default_port_pop3, ssl_enabled, remarks, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (server_name, server_address, default_port_imap, default_port_pop3, ssl_enabled, remarks, now, now))
                    db.commit()
                else:
                    cursor = db.cursor()
                    cursor.execute('''
                        INSERT INTO server_addresses (server_name, server_address, default_port_imap, default_port_pop3, ssl_enabled, remarks, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (server_name, server_address, default_port_imap, default_port_pop3, ssl_enabled, remarks, now, now))
                    db.commit()
                
                return jsonify({
                    'success': True,
                    'message': '服务器添加成功'
                })
                
            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': f'添加失败: {str(e)}'
                })
        
        elif action == 'edit':
            server_id = data.get('id')
            if not server_id:
                return jsonify({
                    'success': False,
                    'message': '缺少服务器ID'
                })
            
            server_name = data.get('server_name', '').strip()
            server_address = data.get('server_address', '').strip()
            default_port_imap = int(data.get('default_port_imap', 993))
            default_port_pop3 = int(data.get('default_port_pop3', 995))
            ssl_enabled = 1 if data.get('ssl_enabled') else 0
            remarks = data.get('remarks', '').strip()
            
            try:
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if db_type == 'sqlite':
                    db.execute('''
                        UPDATE server_addresses 
                        SET server_name=?, server_address=?, default_port_imap=?, default_port_pop3=?, ssl_enabled=?, remarks=?, updated_at=?
                        WHERE id=?
                    ''', (server_name, server_address, default_port_imap, default_port_pop3, ssl_enabled, remarks, now, server_id))
                    db.commit()
                else:
                    cursor = db.cursor()
                    cursor.execute('''
                        UPDATE server_addresses 
                        SET server_name=%s, server_address=%s, default_port_imap=%s, default_port_pop3=%s, ssl_enabled=%s, remarks=%s, updated_at=%s
                        WHERE id=%s
                    ''', (server_name, server_address, default_port_imap, default_port_pop3, ssl_enabled, remarks, now, server_id))
                    db.commit()
                
                return jsonify({
                    'success': True,
                    'message': '服务器更新成功'
                })
                
            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': f'更新失败: {str(e)}'
                })
    
    elif request.method == 'DELETE':
        data = request.get_json()
        server_ids = data.get('ids', [])
        
        if not server_ids:
            return jsonify({
                'success': False,
                'message': '请选择要删除的服务器'
            })
        
        try:
            if db_type == 'sqlite':
                placeholders = ','.join(['?' for _ in server_ids])
                db.execute(f'DELETE FROM server_addresses WHERE id IN ({placeholders})', server_ids)
                db.commit()
            else:
                cursor = db.cursor()
                placeholders = ','.join(['%s' for _ in server_ids])
                cursor.execute(f'DELETE FROM server_addresses WHERE id IN ({placeholders})', server_ids)
                db.commit()
            
            return jsonify({
                'success': True,
                'message': f'成功删除 {len(server_ids)} 个服务器'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'删除失败: {str(e)}'
            })

@app.route('/admin/api/proxies/<proxy_type>', methods=['GET', 'POST', 'DELETE'])
@admin_required
def api_admin_proxies(proxy_type):
    """代理管理 API"""
    if proxy_type not in ['http', 'socks5']:
        return jsonify({
            'success': False,
            'message': '无效的代理类型'
        })
    
    db = get_db()
    db_type = app.config['DATABASE_TYPE']
    table_name = f'{proxy_type}_proxies'
    
    if request.method == 'GET':
        # 获取代理列表（支持分页和搜索）
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search = request.args.get('search', '').strip()
        
        offset = (page - 1) * per_page
        
        # 构建查询条件
        where_clause = ""
        params = []
        if search:
            where_clause = "WHERE name LIKE ? OR host LIKE ? OR remarks LIKE ?"
            search_param = f"%{search}%"
            params = [search_param, search_param, search_param]
        
        # 获取总数和数据
        if db_type == 'sqlite':
            count_sql = f"SELECT COUNT(*) as count FROM {table_name} {where_clause}"
            count_result = db.execute(count_sql, params).fetchone()
            total = count_result['count']
            
            sql = f"""
                SELECT * FROM {table_name} {where_clause}
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """
            proxies = db.execute(sql, params + [per_page, offset]).fetchall()
        else:
            cursor = db.cursor()
            placeholder = '%s'
            where_mysql = where_clause.replace('?', placeholder) if where_clause else ""
            
            count_sql = f"SELECT COUNT(*) as count FROM {table_name} {where_mysql}"
            cursor.execute(count_sql, params)
            total = cursor.fetchone()['count'] if db_type == 'postgresql' else cursor.fetchone()[0]
            
            sql = f"""
                SELECT * FROM {table_name} {where_mysql}
                ORDER BY created_at DESC 
                LIMIT {per_page} OFFSET {offset}
            """
            cursor.execute(sql, params)
            proxies = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'data': [dict(proxy) for proxy in proxies],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    
    elif request.method == 'POST':
        data = request.get_json()
        action = data.get('action')
        
        if action == 'add':
            return _add_proxy(db, table_name, data, proxy_type)
        elif action == 'edit':
            return _edit_proxy(db, table_name, data)
        elif action == 'test':
            return _test_proxy(db, table_name, data, proxy_type)
        elif action == 'test_new':
            return _test_new_proxy(data, proxy_type)
        elif action == 'batch_delete':
            return _batch_delete_proxy(db, table_name, data)
        else:
            return jsonify({
                'success': False,
                'message': '无效的操作类型'
            })
    
    elif request.method == 'DELETE':
        data = request.get_json()
        proxy_id = data.get('id')
        
        if not proxy_id:
            return jsonify({
                'success': False,
                'message': '缺少代理ID'
            })
        
        try:
            if db_type == 'sqlite':
                db.execute(f'DELETE FROM {table_name} WHERE id = ?', (proxy_id,))
                db.commit()
            else:
                cursor = db.cursor()
                cursor.execute(f'DELETE FROM {table_name} WHERE id = %s', (proxy_id,))
                db.commit()
            
            # 重新排序统一代理ID
            reorder_unified_proxy_ids(db, db_type)
            
            return jsonify({
                'success': True,
                'message': '代理删除成功'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'删除失败: {str(e)}'
            })

def _add_proxy(db, table_name, data, proxy_type):
    """添加代理"""
    name = data.get('name', '').strip()
    host = data.get('host', '').strip()
    port_value = data.get('port')
    
    # Handle port conversion more safely
    try:
        port = int(port_value) if port_value is not None else 0
    except (ValueError, TypeError):
        port = 0
    
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    remarks = data.get('remarks', '').strip()
    
    if not all([host, port]):
        return jsonify({
            'success': False,
            'message': '请填写代理地址和端口'
        })
    
    # 如果没有提供名称，保持为空字符串
    if not name:
        name = ""
    
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 先插入代理记录（不包含unified_id）
        if app.config['DATABASE_TYPE'] == 'sqlite':
            cursor = db.execute(f'''
                INSERT INTO {table_name} (name, host, port, username, password, remarks, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, host, port, username, password, remarks, now, now))
            proxy_id = cursor.lastrowid
        else:
            cursor = db.cursor()
            cursor.execute(f'''
                INSERT INTO {table_name} (name, host, port, username, password, remarks, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (name, host, port, username, password, remarks, now, now))
            proxy_id = cursor.lastrowid
            
        # 获取统一ID
        unified_id = get_next_unified_proxy_id(db, proxy_type, proxy_id)
        
        # 更新代理记录的unified_id（如果列存在）
        try:
            update_proxy_unified_id(db, table_name, proxy_id, unified_id)
        except:
            # 如果unified_id列不存在，继续执行
            pass
        
        db.commit()
        
        return jsonify({
            'success': True,
            'message': f'{proxy_type.upper()}代理添加成功'
        })
        
    except Exception as e:
        logger.error(f"Error adding proxy: {e}")
        return jsonify({
            'success': False,
            'message': f'添加失败: {str(e)}'
        })

def _edit_proxy(db, table_name, data):
    """编辑代理"""
    proxy_id = data.get('id')
    if not proxy_id:
        return jsonify({
            'success': False,
            'message': '缺少代理ID'
        })
    
    name = data.get('name', '').strip()
    host = data.get('host', '').strip()
    port_value = data.get('port')
    
    # Handle port conversion more safely
    try:
        port = int(port_value) if port_value is not None else 0
    except (ValueError, TypeError):
        port = 0
    
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    remarks = data.get('remarks', '').strip()
    
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if app.config['DATABASE_TYPE'] == 'sqlite':
            db.execute(f'''
                UPDATE {table_name}
                SET name=?, host=?, port=?, username=?, password=?, remarks=?, updated_at=?
                WHERE id=?
            ''', (name, host, port, username, password, remarks, now, proxy_id))
            db.commit()
        else:
            cursor = db.cursor()
            cursor.execute(f'''
                UPDATE {table_name}
                SET name=%s, host=%s, port=%s, username=%s, password=%s, remarks=%s, updated_at=%s
                WHERE id=%s
            ''', (name, host, port, username, password, remarks, now, proxy_id))
            db.commit()
        
        return jsonify({
            'success': True,
            'message': '代理更新成功'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'更新失败: {str(e)}'
        })

def _test_proxy(db, table_name, data, proxy_type):
    """测试代理"""
    proxy_id = data.get('id')
    
    try:
        # 获取代理信息
        if app.config['DATABASE_TYPE'] == 'sqlite':
            proxy = db.execute(f'SELECT * FROM {table_name} WHERE id = ?', (proxy_id,)).fetchone()
        else:
            cursor = db.cursor()
            cursor.execute(f'SELECT * FROM {table_name} WHERE id = %s', (proxy_id,))
            proxy = cursor.fetchone()
        
        if not proxy:
            return jsonify({
                'success': False,
                'message': '代理不存在'
            })
        
        # 测试代理连接
        test_results = _perform_proxy_test(proxy, proxy_type)
        
        # 更新测试结果
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        response_time = test_results.get('avg_response_time', 0)
        
        if app.config['DATABASE_TYPE'] == 'sqlite':
            db.execute(f'''
                UPDATE {table_name}
                SET last_check=?, response_time=?, status=?
                WHERE id=?
            ''', (now, response_time, 1 if test_results['success'] else 0, proxy_id))
            db.commit()
        else:
            cursor = db.cursor()
            cursor.execute(f'''
                UPDATE {table_name}
                SET last_check=%s, response_time=%s, status=%s
                WHERE id=%s
            ''', (now, response_time, 1 if test_results['success'] else 0, proxy_id))
            db.commit()
        
        return jsonify({
            'success': test_results['success'],
            'message': test_results['message'],
            'details': test_results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'测试失败: {str(e)}'
        })

def _test_new_proxy(data, proxy_type):
    """测试新代理（无需保存到数据库）"""
    host = data.get('host', '').strip()
    port_value = data.get('port')
    
    # Handle port conversion more safely
    try:
        port = int(port_value) if port_value is not None else 0
    except (ValueError, TypeError):
        port = 0
    
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    name = data.get('name', '').strip() or f"临时代理"
    
    if not all([host, port]):
        return jsonify({
            'success': False,
            'message': '请填写代理地址和端口'
        })
    
    try:
        # Create temporary proxy dict for testing
        proxy_dict = {
            'host': host,
            'port': port,
            'username': username or None,
            'password': password or None,
            'name': name
        }
        
        # Test proxy connection
        test_results = _perform_proxy_test(proxy_dict, proxy_type)
        
        return jsonify({
            'success': test_results['success'],
            'message': test_results['message'],
            'details': test_results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'测试失败: {str(e)}'
        })

def _perform_proxy_test(proxy, proxy_type):
    """执行代理测试 - 优化版本"""
    try:
        host = proxy['host']
        port = proxy['port']
        username = proxy['username'] or None
        password = proxy['password'] or None
        
        # 优化测试目标 - 使用baidu.com和163.com进行测试
        test_urls = [
            ('http://baidu.com', 10),          # 百度网站
            ('http://163.com', 10)             # 网易163网站
        ]
        results = []
        
        for url, timeout in test_urls:
            start_time = time.time()
            try:
                if proxy_type == 'http':
                    proxies = {
                        'http': f'http://{username}:{password}@{host}:{port}' if username else f'http://{host}:{port}',
                        'https': f'http://{username}:{password}@{host}:{port}' if username else f'http://{host}:{port}'
                    }
                else:  # socks5
                    proxies = {
                        'http': f'socks5://{username}:{password}@{host}:{port}' if username else f'socks5://{host}:{port}',
                        'https': f'socks5://{username}:{password}@{host}:{port}' if username else f'socks5://{host}:{port}'
                    }
                
                # 优化请求设置
                response = requests.get(
                    url, 
                    proxies=proxies, 
                    timeout=timeout,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Connection': 'keep-alive',
                        'Cache-Control': 'no-cache'
                    },
                    allow_redirects=True,
                    verify=False  # 跳过SSL验证以提高速度
                )
                response_time = int((time.time() - start_time) * 1000)
                
                if response.status_code == 200:
                    results.append({
                        'url': url,
                        'success': True,
                        'response_time': response_time,
                        'status_code': response.status_code
                    })
                    # 注释掉早期中断，确保测试所有URL以显示完整的测试结果
                    # if url == test_urls[0][0]:
                    #     break
                elif response.status_code == 403 and ('163.com' in url or 'baidu.com' in url):
                    # 这些网站的403错误视为网站限制，不算失败
                    results.append({
                        'url': url,
                        'success': True,  # 标记为成功，因为代理工作正常
                        'response_time': response_time,
                        'error': '网站限制(403) - 代理工作正常',
                        'status_code': response.status_code
                    })
                else:
                    results.append({
                        'url': url,
                        'success': False,
                        'response_time': response_time,
                        'error': f'HTTP {response.status_code}',
                        'status_code': response.status_code
                    })
                    
            except requests.exceptions.ConnectTimeout:
                results.append({
                    'url': url,
                    'success': False,
                    'response_time': int((time.time() - start_time) * 1000),
                    'error': '连接超时'
                })
            except requests.exceptions.ProxyError as e:
                results.append({
                    'url': url,
                    'success': False,
                    'response_time': int((time.time() - start_time) * 1000),
                    'error': f'代理错误: {str(e)}'
                })
            except requests.exceptions.RequestException as e:
                error_msg = str(e)
                # 对于特定网站的限制，给出更友好的提示
                if ('163.com' in url or 'baidu.com' in url) and ('403' in error_msg or 'Forbidden' in error_msg):
                    results.append({
                        'url': url,
                        'success': True,
                        'response_time': int((time.time() - start_time) * 1000),
                        'error': '网站限制 - 代理工作正常'
                    })
                else:
                    results.append({
                        'url': url,
                        'success': False,
                        'response_time': int((time.time() - start_time) * 1000),
                        'error': error_msg
                    })
            except Exception as e:
                results.append({
                    'url': url,
                    'success': False,
                    'response_time': int((time.time() - start_time) * 1000),
                    'error': str(e)
                })
        
        # 计算结果 - 优先考虑成功的测试
        successful_tests = [r for r in results if r['success']]
        
        if successful_tests:
            # 使用第一个成功测试的响应时间
            avg_response_time = successful_tests[0]['response_time']
            message = f"测试成功，延迟: {avg_response_time}ms"
            
            if len(successful_tests) > 1:
                message += f"，成功: {len(successful_tests)}/{len(results)}"
                
            return {
                'success': True,
                'message': message,
                'avg_response_time': avg_response_time,
                'results': results
            }
        else:
            # 所有测试都失败 - 简化错误消息，避免显示复杂的堆栈信息
            return {
                'success': False,
                'message': "测试失败",
                'avg_response_time': 0,
                'results': results
            }
            
    except Exception as e:
        return {
            'success': False,
            'message': '测试失败',
            'avg_response_time': 0,
            'results': []
        }

def _batch_delete_proxy(db, table_name, data):
    """批量删除代理"""
    proxy_ids = data.get('ids', [])
    
    if not proxy_ids:
        return jsonify({
            'success': False,
            'message': '请选择要删除的代理'
        })
    
    try:
        if app.config['DATABASE_TYPE'] == 'sqlite':
            placeholders = ','.join(['?' for _ in proxy_ids])
            db.execute(f'DELETE FROM {table_name} WHERE id IN ({placeholders})', proxy_ids)
            db.commit()
        else:
            cursor = db.cursor()
            placeholders = ','.join(['%s' for _ in proxy_ids])
            cursor.execute(f'DELETE FROM {table_name} WHERE id IN ({placeholders})', proxy_ids)
            db.commit()
        
        # 重新排序统一代理ID
        reorder_unified_proxy_ids(db, app.config['DATABASE_TYPE'])
        
        return jsonify({
            'success': True,
            'message': f'成功删除 {len(proxy_ids)} 个代理'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'批量删除失败: {str(e)}'
        })

@app.route('/admin/api/proxy-config', methods=['GET', 'POST'])
@admin_required
def api_admin_proxy_config():
    """代理配置管理 API"""
    db = get_db()
    db_type = app.config['DATABASE_TYPE']
    
    if request.method == 'GET':
        # 获取代理配置
        try:
            if db_type == 'sqlite':
                config_rows = db.execute('SELECT * FROM proxy_config').fetchall()
            else:
                cursor = db.cursor()
                cursor.execute('SELECT * FROM proxy_config')
                config_rows = cursor.fetchall()
            
            # 转换为字典
            config = {}
            for row in config_rows:
                if db_type == 'sqlite':
                    config[row['config_key']] = row['config_value']
                else:
                    config[row[1]] = row[2]  # config_key, config_value
            
            # 获取当前激活的代理信息
            active_proxy = None
            if config.get('proxy_enabled') == '1':
                proxy_type = config.get('active_proxy_type', '')
                proxy_id = int(config.get('active_proxy_id', '0'))
                
                if proxy_type and proxy_id > 0:
                    table_name = 'socks5_proxies' if proxy_type == 'socks5' else 'http_proxies'
                    
                    if db_type == 'sqlite':
                        proxy = db.execute(f'SELECT * FROM {table_name} WHERE id = ?', (proxy_id,)).fetchone()
                    else:
                        cursor = db.cursor()
                        cursor.execute(f'SELECT * FROM {table_name} WHERE id = %s', (proxy_id,))
                        proxy = cursor.fetchone()
                    
                    if proxy:
                        if db_type == 'sqlite':
                            active_proxy = dict(proxy)
                        else:
                            columns = [desc[0] for desc in cursor.description]
                            active_proxy = dict(zip(columns, proxy))
                        active_proxy['proxy_type'] = proxy_type
            
            return jsonify({
                'success': True,
                'config': config,
                'active_proxy': active_proxy
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'获取代理配置失败: {str(e)}'
            })
    
    elif request.method == 'POST':
        # 更新代理配置
        data = request.get_json()
        action = data.get('action')
        
        try:
            if action == 'enable_proxy':
                # 开启代理功能 - 测试所有代理，自动选择延迟最低的代理启用
                
                # 获取所有可用的代理
                all_proxies = []
                
                # 获取HTTP代理
                if db_type == 'sqlite':
                    http_proxies = db.execute('SELECT * FROM http_proxies WHERE status = 1').fetchall()
                else:
                    cursor = db.cursor()
                    cursor.execute('SELECT * FROM http_proxies WHERE status = 1')
                    http_proxies = cursor.fetchall()
                
                if http_proxies:
                    for proxy in http_proxies:
                        if db_type == 'sqlite':
                            proxy_dict = dict(proxy)
                        else:
                            columns = [desc[0] for desc in cursor.description]
                            proxy_dict = dict(zip(columns, proxy))
                        proxy_dict['proxy_type'] = 'http'
                        all_proxies.append(proxy_dict)
                
                # 获取SOCKS5代理
                if db_type == 'sqlite':
                    socks5_proxies = db.execute('SELECT * FROM socks5_proxies WHERE status = 1').fetchall()
                else:
                    cursor = db.cursor()
                    cursor.execute('SELECT * FROM socks5_proxies WHERE status = 1')
                    socks5_proxies = cursor.fetchall()
                
                if socks5_proxies:
                    for proxy in socks5_proxies:
                        if db_type == 'sqlite':
                            proxy_dict = dict(proxy)
                        else:
                            columns = [desc[0] for desc in cursor.description]
                            proxy_dict = dict(zip(columns, proxy))
                        proxy_dict['proxy_type'] = 'socks5'
                        all_proxies.append(proxy_dict)
                
                if not all_proxies:
                    return jsonify({
                        'success': False,
                        'message': '没有找到可用的代理配置'
                    })
                
                # 测试所有代理，选择延迟最低的
                best_proxy = None
                best_response_time = float('inf')
                test_results = []
                
                for proxy in all_proxies:
                    try:
                        # 测试代理连接
                        test_result = _perform_proxy_test(proxy, proxy['proxy_type'])
                        test_results.append({
                            'proxy': proxy,
                            'result': test_result
                        })
                        
                        # 如果测试成功且延迟更低，更新最佳代理
                        if test_result['success'] and test_result['avg_response_time'] < best_response_time:
                            best_proxy = proxy
                            best_response_time = test_result['avg_response_time']
                            
                            # 更新数据库中的响应时间
                            table_name = f"{proxy['proxy_type']}_proxies"
                            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            
                            if db_type == 'sqlite':
                                db.execute(f'''
                                    UPDATE {table_name}
                                    SET last_check=?, response_time=?
                                    WHERE id=?
                                ''', (now, test_result['avg_response_time'], proxy['id']))
                            else:
                                cursor = db.cursor()
                                cursor.execute(f'''
                                    UPDATE {table_name}
                                    SET last_check=%s, response_time=%s
                                    WHERE id=%s
                                ''', (now, test_result['avg_response_time'], proxy['id']))
                        
                    except Exception as e:
                        test_results.append({
                            'proxy': proxy,
                            'result': {
                                'success': False,
                                'message': f'测试失败: {str(e)}',
                                'avg_response_time': 0
                            }
                        })
                
                if not best_proxy:
                    # 如果没有测试成功的代理，选择ID最小的作为备用
                    all_proxies.sort(key=lambda x: x['id'])
                    best_proxy = all_proxies[0]
                    proxy_type = best_proxy['proxy_type']
                    proxy_id = best_proxy['id']
                    
                    # 更新代理配置
                    config_updates = [
                        ('proxy_enabled', '1'),
                        ('active_proxy_type', proxy_type),
                        ('active_proxy_id', str(proxy_id))
                    ]
                    
                    for key, value in config_updates:
                        if db_type == 'sqlite':
                            db.execute('''
                                INSERT OR REPLACE INTO proxy_config (config_key, config_value, updated_at)
                                VALUES (?, ?, CURRENT_TIMESTAMP)
                            ''', (key, value))
                        else:
                            cursor = db.cursor()
                            cursor.execute('''
                                INSERT INTO proxy_config (config_key, config_value, updated_at)
                                VALUES (%s, %s, CURRENT_TIMESTAMP)
                                ON DUPLICATE KEY UPDATE config_value = VALUES(config_value), updated_at = CURRENT_TIMESTAMP
                            ''' if db_type == 'mysql' else '''
                                INSERT INTO proxy_config (config_key, config_value, updated_at)
                                VALUES (%s, %s, CURRENT_TIMESTAMP)
                                ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP
                            ''', (key, value))
                    
                    if db_type != 'sqlite':
                        db.commit()
                    else:
                        db.commit()
                    
                    proxy_name = best_proxy.get('name', '')
                    return jsonify({
                        'success': True,
                        'message': f'🟢 代理状态：已启用\n当前代理: {proxy_type.upper()}--{proxy_name}--地址: {best_proxy["host"]}:{best_proxy["port"]}，所有代理测试均失败，已选择ID最小的代理'
                    })
                
                # 找到最佳代理，更新配置
                proxy_type = best_proxy['proxy_type']
                proxy_id = best_proxy['id']
                
                config_updates = [
                    ('proxy_enabled', '1'),
                    ('active_proxy_type', proxy_type),
                    ('active_proxy_id', str(proxy_id))
                ]
                
                for key, value in config_updates:
                    if db_type == 'sqlite':
                        db.execute('''
                            INSERT OR REPLACE INTO proxy_config (config_key, config_value, updated_at)
                            VALUES (?, ?, CURRENT_TIMESTAMP)
                        ''', (key, value))
                    else:
                        cursor = db.cursor()
                        cursor.execute('''
                            INSERT INTO proxy_config (config_key, config_value, updated_at)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                            ON DUPLICATE KEY UPDATE config_value = VALUES(config_value), updated_at = CURRENT_TIMESTAMP
                        ''' if db_type == 'mysql' else '''
                            INSERT INTO proxy_config (config_key, config_value, updated_at)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP
                        ''', (key, value))
                
                if db_type != 'sqlite':
                    db.commit()
                else:
                    db.commit()
                
                proxy_name = best_proxy.get('name', '')
                return jsonify({
                    'success': True,
                    'message': f'🟢 代理状态：已启用\n当前代理: {proxy_type.upper()}--{proxy_name}--地址: {best_proxy["host"]}:{best_proxy["port"]}，平均延迟: {best_response_time}ms'
                })
                
            elif action == 'disable_proxy':
                # 关闭代理功能
                if db_type == 'sqlite':
                    db.execute('''
                        INSERT OR REPLACE INTO proxy_config (config_key, config_value, updated_at)
                        VALUES ('proxy_enabled', '0', CURRENT_TIMESTAMP)
                    ''')
                    db.commit()
                else:
                    cursor = db.cursor()
                    cursor.execute('''
                        INSERT INTO proxy_config (config_key, config_value, updated_at)
                        VALUES (%s, %s, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE config_value = VALUES(config_value), updated_at = CURRENT_TIMESTAMP
                    ''' if db_type == 'mysql' else '''
                        INSERT INTO proxy_config (config_key, config_value, updated_at)
                        VALUES (%s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP
                    ''', ('proxy_enabled', '0'))
                    db.commit()
                
                return jsonify({
                    'success': True,
                    'message': '代理已关闭'
                })
                
            elif action == 'switch_proxy':
                # 切换代理
                proxy_type = data.get('proxy_type')
                proxy_id = int(data.get('proxy_id', 0))
                
                if not proxy_type or not proxy_id:
                    return jsonify({
                        'success': False,
                        'message': '请提供代理类型和ID'
                    })
                
                # 验证代理是否存在
                table_name = 'socks5_proxies' if proxy_type == 'socks5' else 'http_proxies'
                
                if db_type == 'sqlite':
                    proxy = db.execute(f'SELECT * FROM {table_name} WHERE id = ? AND status = 1', (proxy_id,)).fetchone()
                else:
                    cursor = db.cursor()
                    cursor.execute(f'SELECT * FROM {table_name} WHERE id = %s AND status = 1', (proxy_id,))
                    proxy = cursor.fetchone()
                
                if not proxy:
                    return jsonify({
                        'success': False,
                        'message': '代理不存在或已禁用'
                    })
                
                # 更新配置
                config_updates = [
                    ('proxy_enabled', '1'),
                    ('active_proxy_type', proxy_type),
                    ('active_proxy_id', str(proxy_id))
                ]
                
                for key, value in config_updates:
                    if db_type == 'sqlite':
                        db.execute('''
                            INSERT OR REPLACE INTO proxy_config (config_key, config_value, updated_at)
                            VALUES (?, ?, CURRENT_TIMESTAMP)
                        ''', (key, value))
                    else:
                        cursor = db.cursor()
                        cursor.execute('''
                            INSERT INTO proxy_config (config_key, config_value, updated_at)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                            ON DUPLICATE KEY UPDATE config_value = VALUES(config_value), updated_at = CURRENT_TIMESTAMP
                        ''' if db_type == 'mysql' else '''
                            INSERT INTO proxy_config (config_key, config_value, updated_at)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP
                        ''', (key, value))
                
                if db_type != 'sqlite':
                    db.commit()
                else:
                    db.commit()
                
                # 获取代理信息
                if db_type == 'sqlite':
                    proxy_dict = dict(proxy)
                else:
                    cursor.execute(f'DESCRIBE {table_name}' if db_type == 'mysql' else 
                                 f'SELECT column_name FROM information_schema.columns WHERE table_name = \'{table_name}\'')
                    columns = [row[0] for row in cursor.fetchall()]
                    proxy_dict = dict(zip(columns, proxy))
                
                proxy_name = proxy_dict.get('name', '')
                return jsonify({
                    'success': True,
                    'message': f'🟢 代理状态：已启用\n当前代理: {proxy_type.upper()}--{proxy_name}--地址: {proxy_dict["host"]}:{proxy_dict["port"]}'
                })
            
            else:
                return jsonify({
                    'success': False,
                    'message': '无效的操作'
                })
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'操作失败: {str(e)}'
            })

@app.route('/admin/api/cards', methods=['GET', 'POST', 'DELETE'])
@admin_required
def api_admin_cards():
    """卡密管理 API"""
    db = get_db()
    db_type = app.config['DATABASE_TYPE']
    
    if request.method == 'GET':
        # 获取卡密列表（支持分页和搜索）
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search = request.args.get('search', '').strip()
        
        offset = (page - 1) * per_page
        
        # 构建查询条件
        where_clause = ""
        params = []
        if search:
            where_clause = "WHERE card_key LIKE ? OR remarks LIKE ?"
            search_param = f"%{search}%"
            params = [search_param, search_param]
        
        # 获取总数
        if db_type == 'sqlite':
            count_sql = f"SELECT COUNT(*) as count FROM cards {where_clause}"
            count_result = db.execute(count_sql, params).fetchone()
            total = count_result['count']
            
            # 获取分页数据
            sql = f"""
                SELECT c.*, 
                    e.email as bound_email,
                    (SELECT created_at FROM card_logs WHERE card_id = c.id ORDER BY created_at DESC LIMIT 1) as last_used_at
                FROM cards c
                LEFT JOIN mail_accounts e ON c.bound_email_id = e.id
                {where_clause.replace('card_key', 'c.card_key').replace('remarks', 'c.remarks') if where_clause else ''}
                ORDER BY c.id ASC 
                LIMIT ? OFFSET ?
            """
            cards = db.execute(sql, params + [per_page, offset]).fetchall()
        else:
            cursor = db.cursor()
            placeholder = '%s'
            where_mysql = where_clause.replace('?', placeholder) if where_clause else ""
            
            count_sql = f"SELECT COUNT(*) as count FROM cards {where_mysql}"
            cursor.execute(count_sql, params)
            total = cursor.fetchone()[0]
            
            sql = f"""
                SELECT c.*, 
                    e.email as bound_email,
                    (SELECT created_at FROM card_logs WHERE card_id = c.id ORDER BY created_at DESC LIMIT 1) as last_used_at
                FROM cards c
                LEFT JOIN mail_accounts e ON c.bound_email_id = e.id
                {where_mysql}
                ORDER BY c.id ASC 
                LIMIT {per_page} OFFSET {offset}
            """
            cursor.execute(sql, params)
            cards = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'data': [dict(card) for card in cards],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    
    elif request.method == 'POST':
        # 添加或处理卡密
        data = request.get_json()
        action = data.get('action')
        
        if action == 'generate':
            return _generate_card(db, data)
        elif action == 'batch_generate':
            return _batch_generate_cards(db, data)
        elif action == 'bind_email':
            return _bind_email_to_card(db, data)
        elif action == 'edit':
            return _edit_card(db, data)
        else:
            return jsonify({
                'success': False,
                'message': '无效的操作类型'
            })
    
    elif request.method == 'DELETE':
        # 删除卡密
        data = request.get_json()
        
        if 'action' in data and data['action'] == 'batch_delete':
            return _batch_delete_cards(db, data)
        else:
            card_id = data.get('id')
            if not card_id:
                return jsonify({
                    'success': False,
                    'message': '缺少卡密ID'
                })
            
            try:
                success, message = move_card_to_recycle_bin(db, db_type, card_id, 'deleted', '手动删除')
                if success:
                    db.commit()
                    return jsonify({
                        'success': True,
                        'message': '卡密已移动到回收站'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'message': message
                    })
                
            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': f'删除失败: {str(e)}'
                })

@app.route('/admin/api/cards/stats')
@admin_required
def api_admin_card_stats():
    """卡密统计 API"""
    db = get_db()
    db_type = app.config['DATABASE_TYPE']
    
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if db_type == 'sqlite':
            # 总数
            total_result = db.execute('SELECT COUNT(*) as count FROM cards').fetchone()
            total = total_result['count']
            
            # 可用数量（状态正常、未过期、未用完）
            active_result = db.execute('''
                SELECT COUNT(*) as count FROM cards 
                WHERE status = 1 
                AND (expired_at IS NULL OR expired_at > ?) 
                AND used_count < usage_limit
            ''', (now,)).fetchone()
            active = active_result['count']
            
            # 已使用完
            used_result = db.execute('''
                SELECT COUNT(*) as count FROM cards 
                WHERE used_count >= usage_limit
            ''').fetchone()
            used = used_result['count']
            
            # 已过期
            expired_result = db.execute('''
                SELECT COUNT(*) as count FROM cards 
                WHERE expired_at IS NOT NULL AND expired_at <= ?
            ''', (now,)).fetchone()
            expired = expired_result['count']
            
        else:
            cursor = db.cursor()
            
            # 总数
            cursor.execute('SELECT COUNT(*) as count FROM cards')
            total = cursor.fetchone()[0]
            
            # 可用数量
            cursor.execute('''
                SELECT COUNT(*) as count FROM cards 
                WHERE status = 1 
                AND (expired_at IS NULL OR expired_at > %s) 
                AND used_count < usage_limit
            ''', (now,))
            active = cursor.fetchone()[0]
            
            # 已使用完
            cursor.execute('''
                SELECT COUNT(*) as count FROM cards 
                WHERE used_count >= usage_limit
            ''')
            used = cursor.fetchone()[0]
            
            # 已过期
            cursor.execute('''
                SELECT COUNT(*) as count FROM cards 
                WHERE expired_at IS NOT NULL AND expired_at <= %s
            ''', (now,))
            expired = cursor.fetchone()[0]
        
        return jsonify({
            'success': True,
            'stats': {
                'total': total,
                'active': active,
                'used': used,
                'expired': expired
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取统计数据失败: {str(e)}'
        })

def _generate_card_key():
    """生成12位随机小写字母和数字的卡密"""
    import random
    import string
    
    # 小写字母和数字
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(12))

def _generate_card(db, data):
    """生成单个卡密"""
    usage_limit = data.get('usage_limit', 1)
    expired_at = data.get('expired_at')
    remarks = data.get('remarks', '')
    email_days_filter = data.get('email_days_filter', 1)
    keyword_filter = data.get('keyword_filter', '')
    
    try:
        # 生成唯一卡密
        max_attempts = 10
        for _ in range(max_attempts):
            card_key = _generate_card_key()
            
            # 检查是否已存在
            if app.config['DATABASE_TYPE'] == 'sqlite':
                existing = db.execute('SELECT id FROM cards WHERE card_key = ?', (card_key,)).fetchone()
            else:
                cursor = db.cursor()
                cursor.execute('SELECT id FROM cards WHERE card_key = %s', (card_key,))
                existing = cursor.fetchone()
            
            if not existing:
                break
        else:
            return jsonify({
                'success': False,
                'message': '生成卡密失败，请重试'
            })
        
        # 插入卡密
        now = get_beijing_time()  # 使用北京时间
        if app.config['DATABASE_TYPE'] == 'sqlite':
            db.execute('''
                INSERT INTO cards (card_key, usage_limit, expired_at, remarks, email_days_filter, keyword_filter, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (card_key, usage_limit, expired_at, remarks, email_days_filter, keyword_filter, now, now))
            db.commit()
        else:
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO cards (card_key, usage_limit, expired_at, remarks, email_days_filter, keyword_filter, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (card_key, usage_limit, expired_at, remarks, email_days_filter, keyword_filter, now, now))
            db.commit()
        
        return jsonify({
            'success': True,
            'message': f'卡密生成成功：{card_key}',
            'card_key': card_key
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'生成卡密失败: {str(e)}'
        })

def _batch_generate_cards(db, data):
    """批量生成卡密"""
    count = data.get('count', 1)
    usage_limit = data.get('usage_limit', 1)
    expired_at = data.get('expired_at')
    remarks = data.get('remarks', '')
    email_days_filter = data.get('email_days_filter', 1)
    keyword_filter = data.get('keyword_filter', '')
    
    if count > 100:
        return jsonify({
            'success': False,
            'message': '一次最多生成100个卡密'
        })
    
    try:
        generated_cards = []
        now = get_beijing_time()  # 使用北京时间
        
        for i in range(count):
            # 生成唯一卡密
            max_attempts = 10
            for _ in range(max_attempts):
                card_key = _generate_card_key()
                
                # 检查是否已存在（包括已生成的）
                if card_key not in generated_cards:
                    if app.config['DATABASE_TYPE'] == 'sqlite':
                        existing = db.execute('SELECT id FROM cards WHERE card_key = ?', (card_key,)).fetchone()
                    else:
                        cursor = db.cursor()
                        cursor.execute('SELECT id FROM cards WHERE card_key = %s', (card_key,))
                        existing = cursor.fetchone()
                    
                    if not existing:
                        generated_cards.append(card_key)
                        break
            else:
                return jsonify({
                    'success': False,
                    'message': f'生成第{i+1}个卡密失败，请重试'
                })
        
        # 批量插入
        if app.config['DATABASE_TYPE'] == 'sqlite':
            for card_key in generated_cards:
                db.execute('''
                    INSERT INTO cards (card_key, usage_limit, expired_at, remarks, email_days_filter, keyword_filter, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (card_key, usage_limit, expired_at, remarks, email_days_filter, keyword_filter, now, now))
            db.commit()
        else:
            cursor = db.cursor()
            for card_key in generated_cards:
                cursor.execute('''
                    INSERT INTO cards (card_key, usage_limit, expired_at, remarks, email_days_filter, keyword_filter, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (card_key, usage_limit, expired_at, remarks, email_days_filter, keyword_filter, now, now))
            db.commit()
        
        return jsonify({
            'success': True,
            'message': f'批量生成成功，共生成 {len(generated_cards)} 个卡密',
            'generated_count': len(generated_cards),
            'card_keys': generated_cards
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'批量生成失败: {str(e)}'
        })

def _batch_delete_cards(db, data):
    """批量删除卡密"""
    card_ids = data.get('ids', [])
    
    if not card_ids:
        return jsonify({
            'success': False,
            'message': '请选择要删除的卡密'
        })
    
    try:
        db_type = app.config['DATABASE_TYPE']  # 获取数据库类型
        success_count = 0
        error_count = 0
        
        for card_id in card_ids:
            success, message = move_card_to_recycle_bin(db, db_type, card_id, 'deleted', '批量删除')
            if success:
                success_count += 1
            else:
                error_count += 1
                logger.error(f"Failed to move card {card_id} to recycle bin: {message}")
        
        if success_count > 0:
            db.commit()
        
        if error_count == 0:
            return jsonify({
                'success': True,
                'message': f'成功将 {success_count} 个卡密移动到回收站'
            })
        else:
            return jsonify({
                'success': True,
                'message': f'成功将 {success_count} 个卡密移动到回收站，{error_count} 个失败'
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'批量删除失败: {str(e)}'
        })

def _edit_card(db, data):
    """编辑卡密"""
    card_id = data.get('card_id')
    usage_limit = data.get('usage_limit', 1)
    expired_at = data.get('expired_at')
    remarks = data.get('remarks', '')
    bound_email_id = data.get('bound_email_id')
    email_days_filter = data.get('email_days_filter', 7)
    sender_filter = data.get('sender_filter', '')
    keyword_filter = data.get('keyword_filter', '')
    
    if not card_id:
        return jsonify({
            'success': False,
            'message': '缺少卡密ID'
        })
    
    try:
        now = get_beijing_time()  # 使用北京时间
        
        # 验证bound_email_id是否有效（如果提供）
        if bound_email_id:
            if app.config['DATABASE_TYPE'] == 'sqlite':
                email_exists = db.execute('SELECT id FROM mail_accounts WHERE id = ?', (bound_email_id,)).fetchone()
            else:
                cursor = db.cursor()
                cursor.execute('SELECT id FROM mail_accounts WHERE id = %s', (bound_email_id,))
                email_exists = cursor.fetchone()
            
            if not email_exists:
                return jsonify({
                    'success': False,
                    'message': '指定的邮箱不存在'
                })
        
        if app.config['DATABASE_TYPE'] == 'sqlite':
            # 检查卡密是否存在
            card = db.execute('SELECT * FROM cards WHERE id = ?', (card_id,)).fetchone()
            if not card:
                return jsonify({
                    'success': False,
                    'message': '卡密不存在'
                })
            
            # 更新卡密
            db.execute('''
                UPDATE cards 
                SET usage_limit = ?, expired_at = ?, remarks = ?, 
                    bound_email_id = ?, email_days_filter = ?, sender_filter = ?, keyword_filter = ?, updated_at = ?
                WHERE id = ?
            ''', (usage_limit, expired_at, remarks, bound_email_id, email_days_filter, sender_filter, keyword_filter, now, card_id))
            db.commit()
        else:
            cursor = db.cursor()
            # 检查卡密是否存在
            cursor.execute('SELECT * FROM cards WHERE id = %s', (card_id,))
            card = cursor.fetchone()
            if not card:
                return jsonify({
                    'success': False,
                    'message': '卡密不存在'
                })
            
            # 更新卡密
            cursor.execute('''
                UPDATE cards 
                SET usage_limit = %s, expired_at = %s, remarks = %s, 
                    bound_email_id = %s, email_days_filter = %s, sender_filter = %s, keyword_filter = %s, updated_at = %s
                WHERE id = %s
            ''', (usage_limit, expired_at, remarks, bound_email_id, email_days_filter, sender_filter, keyword_filter, now, card_id))
            db.commit()
        
        return jsonify({
            'success': True,
            'message': '卡密编辑成功'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'编辑卡密失败: {str(e)}'
        })

def _bind_email_to_card(db, data):
    """绑定邮箱到卡密"""
    card_id = data.get('card_id')
    email_id = data.get('email_id')
    
    if not card_id or not email_id:
        return jsonify({
            'success': False,
            'message': '请提供卡密ID和邮箱ID'
        })
    
    try:
        # 验证卡密和邮箱是否存在
        if app.config['DATABASE_TYPE'] == 'sqlite':
            card = db.execute('SELECT * FROM cards WHERE id = ?', (card_id,)).fetchone()
            email = db.execute('SELECT * FROM mail_accounts WHERE id = ?', (email_id,)).fetchone()
        else:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM cards WHERE id = %s', (card_id,))
            card = cursor.fetchone()
            cursor.execute('SELECT * FROM mail_accounts WHERE id = %s', (email_id,))
            email = cursor.fetchone()
        
        if not card:
            return jsonify({
                'success': False,
                'message': '卡密不存在'
            })
        
        if not email:
            return jsonify({
                'success': False,
                'message': '邮箱不存在'
            })
        
        # 更新卡密备注，记录绑定的邮箱
        if app.config['DATABASE_TYPE'] == 'sqlite':
            email_dict = dict(email)
            new_remarks = f"绑定邮箱: {email_dict['email']}"
            db.execute('UPDATE cards SET remarks = ? WHERE id = ?', (new_remarks, card_id))
            db.commit()
        else:
            cursor = db.cursor()
            # 获取邮箱信息
            cursor.execute('SELECT email FROM mail_accounts WHERE id = %s', (email_id,))
            email_address = cursor.fetchone()[0]
            new_remarks = f"绑定邮箱: {email_address}"
            cursor.execute('UPDATE cards SET remarks = %s WHERE id = %s', (new_remarks, card_id))
            db.commit()
        
        return jsonify({
            'success': True,
            'message': '邮箱绑定成功'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'绑定失败: {str(e)}'
        })

@app.route('/admin/api/cards/<int:card_id>/available-emails', methods=['GET'])
@admin_required
def api_admin_card_available_emails(card_id):
    """获取指定卡密可绑定的邮箱列表（排除已绑定的邮箱）"""
    db = get_db()
    db_type = app.config['DATABASE_TYPE']
    
    try:
        # 获取所有邮箱
        if db_type == 'sqlite':
            all_emails = db.execute('SELECT * FROM mail_accounts ORDER BY email ASC').fetchall()
        else:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM mail_accounts ORDER BY email ASC')
            all_emails = cursor.fetchall()
        
        # 获取已绑定的邮箱ID（排除当前卡密）
        if db_type == 'sqlite':
            bound_email_ids = db.execute('''
                SELECT DISTINCT bound_email_id 
                FROM cards 
                WHERE bound_email_id IS NOT NULL AND id != ?
            ''', (card_id,)).fetchall()
            bound_ids = [row['bound_email_id'] for row in bound_email_ids]
        else:
            cursor = db.cursor()
            cursor.execute('''
                SELECT DISTINCT bound_email_id 
                FROM cards 
                WHERE bound_email_id IS NOT NULL AND id != %s
            ''', (card_id,))
            bound_email_ids = cursor.fetchall()
            bound_ids = [row[0] for row in bound_email_ids]
        
        # 过滤掉已绑定的邮箱
        available_emails = []
        for email in all_emails:
            email_id = email['id'] if db_type == 'sqlite' else email[0]
            if email_id not in bound_ids:
                available_emails.append(dict(email) if db_type == 'sqlite' else dict(zip([desc[0] for desc in cursor.description], email)))
        
        return jsonify({
            'success': True,
            'data': available_emails
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取可绑定邮箱列表失败: {str(e)}'
        })

@app.route('/admin/api/cards/generate-api/<card_key>', methods=['GET'])
def api_admin_generate_card_api_page(card_key):
    """为卡密生成API页面"""
    try:
        # 获取数据库连接
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        # 查询卡密信息，包括绑定的邮箱
        if db_type == 'sqlite':
            card_query = """
                SELECT c.*, e.email, e.server 
                FROM cards c 
                LEFT JOIN mail_accounts e ON c.bound_email_id = e.id 
                WHERE c.card_key = ?
            """
            card_result = db.execute(card_query, (card_key,)).fetchone()
            if card_result:
                card_result = dict(card_result)  # Convert Row to dict
        else:
            cursor = db.cursor()
            card_query = """
                SELECT c.*, e.email, e.server 
                FROM cards c 
                LEFT JOIN mail_accounts e ON c.bound_email_id = e.id 
                WHERE c.card_key = %s
            """
            cursor.execute(card_query, (card_key,))
            card_result = cursor.fetchone()
            if card_result and hasattr(card_result, '_asdict'):
                card_result = card_result._asdict()
            elif card_result:
                # Handle tuple result
                columns = [desc[0] for desc in cursor.description]
                card_result = dict(zip(columns, card_result))
        
        if not card_result:
            # 获取API页面标题
            api_title = get_system_config('api_page_title', 'API取件页面')
            # 返回包含"此卡密不存在"消息的HTML页面而不是JSON
            error_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{api_title} - 卡密不存在</title>
    <link rel="icon" type="image/x-icon" href="/static/img/favicons/favicon.ico">
    <link rel="icon" type="image/png" sizes="16x16" href="/static/img/favicons/favicon-16x16.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/img/favicons/favicon-32x32.png">
    <link rel="icon" type="image/svg+xml" href="/static/img/favicons/favicon.svg">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        
        .error-container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 500px;
            width: 100%;
        }}
        
        .error-icon {{
            font-size: 64px;
            margin-bottom: 20px;
            color: #ef4444;
        }}
        
        .error-title {{
            font-size: 24px;
            color: #1e293b;
            margin-bottom: 15px;
            font-weight: 600;
        }}
        
        .error-message {{
            color: #6b7280;
            font-size: 16px;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <div class="error-container">
        <div class="error-icon">❌</div>
        <div class="error-title">此卡密不存在</div>
        <div class="error-message">请检查卡密是否正确，或联系管理员获取有效卡密</div>
    </div>
</body>
</html>"""
            return error_content, 404, {'Content-Type': 'text/html; charset=utf-8'}
        
        # 检查卡密是否已绑定邮箱
        has_bound_email = card_result.get('bound_email_id') is not None
        bound_email = card_result.get('email') if has_bound_email else None
        
        # 根据绑定状态生成不同的API页面内容
        if has_bound_email:
            # 已绑定邮箱：页面无输入框，不显示当前卡密和绑定邮箱，仅有"获取邮件"按钮
            input_section = f"""
            <div class="action-group">
                <button class="get-mail-btn" onclick="getMail()">获取邮件</button>
            </div>"""
        else:
            # 未绑定邮箱：页面仅有输入框和"获取邮件"按钮
            input_section = f"""
            <div class="input-group">
                <input type="email" id="emailInput" placeholder="请输入邮箱地址" required>
                <button class="get-mail-btn" onclick="getMail()">获取邮件</button>
            </div>"""
        
        # 获取API页面标题
        api_title = get_system_config('api_page_title', 'API取件页面')
        
        api_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{api_title}</title>
    <link rel="icon" type="image/x-icon" href="/static/img/favicons/favicon.ico">
    <link rel="icon" type="image/png" sizes="16x16" href="/static/img/favicons/favicon-16x16.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/img/favicons/favicon-32x32.png">
    <link rel="icon" type="image/svg+xml" href="/static/img/favicons/favicon.svg">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        
        .header {{
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }}
        
        .header h1 {{
            font-size: 32px;
            margin-bottom: 10px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}
        
        .header p {{
            font-size: 16px;
            opacity: 0.9;
        }}
        
        .main-card {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        
        .input-group {{
            display: flex;
            margin-bottom: 20px;
            gap: 15px;
        }}
        
        .action-group {{
            text-align: center;
            margin-bottom: 20px;
        }}
        
        .bound-email-info {{
            margin-bottom: 25px;
            padding: 20px;
            background: #f8fafc;
            border-radius: 12px;
            border-left: 4px solid #667eea;
        }}
        
        .unbound-email-info {{
            margin-bottom: 20px;
            padding: 15px;
            background: #fef3c7;
            border-radius: 12px;
            border-left: 4px solid #f59e0b;
        }}
        
        .email-info {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }}
        
        .email-label {{
            font-weight: 600;
            color: #374151;
        }}
        
        .email-address {{
            background: #667eea;
            color: white;
            padding: 4px 10px;
            border-radius: 6px;
            font-family: 'Courier New', monospace;
            font-size: 14px;
        }}
        
        .info-text {{
            color: #6b7280;
            font-size: 14px;
            margin: 0;
        }}
        
        .input-group input {{
            flex: 1;
            padding: 15px 20px;
            border: 2px solid #e1e5e9;
            border-radius: 12px;
            font-size: 16px;
            transition: all 0.3s ease;
        }}
        
        .input-group input:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}
        
        .get-mail-btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            min-width: 120px;
        }}
        
        .get-mail-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(102, 126, 234, 0.3);
        }}
        
        .get-mail-btn:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }}
        
        .loading {{
            display: none;
            text-align: center;
            padding: 20px;
            color: #667eea;
            font-size: 16px;
        }}
        
        .loading .spinner {{
            width: 40px;
            height: 40px;
            border: 4px solid #f3f4f6;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }}
        
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        
        .message {{
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
            font-weight: 500;
        }}
        
        .message.success {{
            background: #d1fae5;
            color: #065f46;
            border: 1px solid #a7f3d0;
        }}
        
        .message.error {{
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }}
        
        .message.info {{
            background: #dbeafe;
            color: #1e40af;
            border: 1px solid #93c5fd;
        }}
        
        .mail-display {{
            display: none;
            background: #f8fafc;
            border-radius: 15px;
            padding: 25px;
            margin-top: 25px;
        }}
        
        .mail-header {{
            margin-bottom: 20px;
        }}
        
        .mail-subject {{
            font-size: 20px;
            font-weight: 600;
            color: #1e293b;
            margin-bottom: 15px;
        }}
        
        .mail-meta {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        
        .mail-meta-item {{
            background: white;
            padding: 12px 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        
        .mail-meta-label {{
            font-size: 12px;
            color: #6b7280;
            font-weight: 500;
            display: block;
            margin-bottom: 5px;
        }}
        
        .mail-body {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #e5e7eb;
            max-height: 400px;
            overflow-y: auto;
            font-size: 14px;
            line-height: 1.6;
        }}
        
        .mail-body.text-content {{
            white-space: pre-wrap;
            font-family: 'Courier New', monospace;
        }}
        
        .mail-body.html-content {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }}
        
        .mail-body.html-content a {{
            color: #667eea;
            text-decoration: none;
        }}
        
        .mail-body.html-content a:hover {{
            color: #764ba2;
            text-decoration: underline;
        }}
        
        /* Images section styles */
        .mail-images {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #e5e7eb;
            margin-top: 15px;
        }}
        
        .image-container {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 10px;
        }}
        
        .image-item {{
            background: #f8fafc;
            border-radius: 8px;
            overflow: hidden;
            transition: transform 0.2s ease;
        }}
        
        .image-item:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        
        .image-item img {{
            width: 100%;
            height: 150px;
            object-fit: cover;
            cursor: pointer;
        }}
        
        .image-info {{
            padding: 10px;
        }}
        
        .attachment-name {{
            font-weight: 600;
            color: #374151;
            margin-bottom: 4px;
            word-break: break-all;
        }}
        
        .attachment-meta {{
            font-size: 12px;
            color: #6b7280;
        }}
        
        /* Attachments section styles */
        .mail-attachments {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #e5e7eb;
            margin-top: 15px;
        }}
        
        .attachment-list {{
            margin-top: 10px;
        }}
        
        .attachment-item {{
            display: flex;
            align-items: center;
            padding: 12px;
            background: #f8fafc;
            border-radius: 8px;
            margin-bottom: 8px;
            transition: background 0.2s ease;
        }}
        
        .attachment-item:hover {{
            background: #e5e7eb;
        }}
        
        .attachment-icon {{
            width: 40px;
            height: 40px;
            background: #667eea;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            margin-right: 12px;
        }}
        
        .attachment-details {{
            flex: 1;
        }}
        
        .attachment-size {{
            color: #6b7280;
            font-size: 12px;
        }}
        
        /* Image Modal styles */
        .image-modal {{
            display: none;
            position: fixed;
            z-index: 4000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.9);
        }}
        
        .image-modal-content {{
            margin: auto;
            display: block;
            width: 80%;
            max-width: 700px;
            max-height: 80%;
            animation: zoom 0.3s;
        }}
        
        @keyframes zoom {{
            from {{transform: scale(0)}}
            to {{transform: scale(1)}}
        }}
        
        .image-modal-close {{
            position: absolute;
            top: 15px;
            right: 35px;
            color: #f1f1f1;
            font-size: 40px;
            font-weight: bold;
            transition: 0.3s;
            cursor: pointer;
        }}
        
        .image-modal-close:hover,
        .image-modal-close:focus {{
            color: #bbb;
            text-decoration: none;
        }}
        
        .api-info {{
            background: #f1f5f9;
            padding: 20px;
            border-radius: 10px;
            margin-top: 20px;
            font-size: 14px;
            color: #475569;
        }}
        
        .card-key {{
            background: #667eea;
            color: white;
            padding: 8px 12px;
            border-radius: 6px;
            font-family: 'Courier New', monospace;
            font-weight: 600;
        }}
        
        /* Toast Notifications */
        .toast-container {{
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 3000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-width: 400px;
        }}
        
        .toast {{
            padding: 15px 20px;
            border-radius: 10px;
            color: white;
            font-weight: 500;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            transform: translateX(450px);
            opacity: 0;
            transition: all 0.3s ease;
            position: relative;
            background: #6b7280;
            margin-bottom: 10px;
        }}
        
        .toast.show {{
            transform: translateX(0);
            opacity: 1;
        }}
        
        .toast.success {{
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        }}
        
        .toast.error {{
            background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
        }}
        
        .toast.info {{
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        }}
        
        .toast.warning {{
            background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
        }}
    </style>
</head>
<body>
    <!-- Toast notification container -->
    <div id="toast-container" class="toast-container"></div>
    
    <div class="container">
        <div class="header">
            <h1>📧 API邮件查看</h1>
            <p>{api_title}</p>
        </div>
        
        <div class="main-card">
            {input_section}
            
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <div>正在通过API获取邮件，请稍候...</div>
            </div>
        </div>
        
        <div class="mail-display" id="mailDisplay">
            <div class="mail-header">
                <div class="mail-subject" id="mailSubject"></div>
                <div class="mail-meta">
                    <div class="mail-meta-item">
                        <span class="mail-meta-label">发件人:</span>
                        <span id="mailFrom"></span>
                    </div>
                    <div class="mail-meta-item">
                        <span class="mail-meta-label">收件人:</span>
                        <span id="mailTo"></span>
                    </div>
                    <div class="mail-meta-item">
                        <span class="mail-meta-label">时间:</span>
                        <span id="mailDate"></span>
                    </div>
                </div>
            </div>
            
            <div class="mail-body" id="mailBody"></div>
            
            <!-- Images section -->
            <div class="mail-images" id="mailImages" style="display: none;">
                <h4 style="color: #667eea; margin-bottom: 10px;">📷 图片内容</h4>
                <div class="image-container" id="imageContainer"></div>
            </div>
            
            <!-- Attachments section -->
            <div class="mail-attachments" id="mailAttachments" style="display: none;">
                <h4 style="color: #667eea; margin-bottom: 10px;">📎 附件</h4>
                <div class="attachment-list" id="attachmentList"></div>
            </div>
        </div>
    </div>
    
    <!-- Image Modal -->
    <div id="imageModal" class="image-modal">
        <span class="image-modal-close" onclick="closeImageModal()">&times;</span>
        <img class="image-modal-content" id="modalImage">
    </div>
    
    <script>
        // 检查是否已绑定邮箱
        const hasBoundEmail = {str(has_bound_email).lower()};
        const boundEmail = "{bound_email if bound_email else ''}";
        
        // 回车键触发获取邮件（仅在有输入框时）
        const emailInput = document.getElementById('emailInput');
        if (emailInput) {{
            emailInput.addEventListener('keypress', function(e) {{
                if (e.key === 'Enter') {{
                    getMail();
                }}
            }});
        }}
        
        async function getMail() {{
            const loading = document.getElementById('loading');
            const mailDisplay = document.getElementById('mailDisplay');
            const getMailBtn = document.querySelector('.get-mail-btn');
            
            let email;
            
            if (hasBoundEmail) {{
                // 已绑定邮箱，直接使用绑定的邮箱
                email = boundEmail;
            }} else {{
                // 未绑定邮箱，从输入框获取
                const emailInput = document.getElementById('emailInput');
                email = emailInput.value.trim();
                
                if (!email) {{
                    showToast('请输入邮箱地址', 'error');
                    return;
                }}
                
                if (!isValidEmail(email)) {{
                    showToast('请输入有效的邮箱地址', 'error');
                    return;
                }}
            }}
            
            // 显示加载状态
            loading.style.display = 'block';
            getMailBtn.disabled = true;
            getMailBtn.textContent = '获取中...';
            mailDisplay.style.display = 'none';
            
            try {{
                const response = await fetch('/api/get_mail', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'X-Card-Key': '{card_key}'
                    }},
                    body: JSON.stringify({{ 
                        email: email,
                        card_key: '{card_key}'
                    }})
                }});
                
                const data = await response.json();
                
                if (data.success) {{
                    if (data.mail) {{
                        displayMailWithCardInfo(data);
                        // 添加连接状态到成功消息
                        let successMessage = '邮件获取成功';
                        if (data.proxy && data.proxy.enabled) {{
                            successMessage += ' (代理)';
                        }} else {{
                            successMessage += ' (直连)';
                        }}
                        showToast(successMessage, 'success');
                    }} else {{
                        // 添加连接状态到无邮件消息  
                        let noMailMessage = '邮箱中暂无邮件';
                        if (data.proxy && data.proxy.enabled) {{
                            noMailMessage += ' (代理)';
                        }} else {{
                            noMailMessage += ' (直连)';
                        }}
                        showToast(noMailMessage, 'info');
                    }}
                }} else {{
                    // 添加连接状态到错误消息
                    let errorMessage = data.message || '获取邮件失败';
                    // 检查消息是否已经包含连接指示符，避免重复添加
                    const hasConnectionInfo = /\\(直连\\)|\\(代理\\)|\\(通过.*\\)|\\(代理连接.*\\)/.test(errorMessage);
                    
                    if (!hasConnectionInfo) {{
                        if (data.proxy && data.proxy.enabled) {{
                            if (data.proxy.info && data.proxy.info.name) {{
                                errorMessage += ` (代理连接: ${{data.proxy.info.name}})`;
                            }} else {{
                                errorMessage += ' (代理连接)';
                            }}
                        }} else {{
                            errorMessage += ' (直连)';
                        }}
                    }}
                    showToast(errorMessage, 'error');
                }}
                
            }} catch (error) {{
                console.error('API请求失败:', error);
                showToast('网络请求失败，请检查网络连接', 'error');
            }} finally {{
                // 隐藏加载状态
                loading.style.display = 'none';
                getMailBtn.disabled = false;
                getMailBtn.textContent = '获取邮件';
            }}
        }}
        
        function displayMail(mail) {{
            document.getElementById('mailSubject').textContent = mail.subject || '(无主题)';
            
            // 显示发件人信息（后端已格式化为"名称 <邮箱地址>"格式）
            document.getElementById('mailFrom').textContent = mail.from || '未知';
            
            document.getElementById('mailTo').textContent = mail.to || '未知';
            document.getElementById('mailDate').textContent = mail.date || '未知';
            
            // 显示邮件正文
            const mailBodyElement = document.getElementById('mailBody');
            if (mail.body_type === 'html') {{
                mailBodyElement.innerHTML = mail.body || '(邮件内容为空)';
                mailBodyElement.className = 'mail-body html-content';
            }} else {{
                mailBodyElement.textContent = mail.body || '(邮件内容为空)';
                mailBodyElement.className = 'mail-body text-content';
            }}
            
            // 显示图片
            displayImages(mail.images || []);
            
            // 显示附件
            displayAttachments(mail.attachments || []);
            
            document.getElementById('mailDisplay').style.display = 'block';
        }}
        
        function displayMailWithCardInfo(data) {{
            if (data.mail) {{
                displayMail(data.mail);
                
                // 显示卡密使用信息
                if (data.card_info) {{
                    const cardInfo = data.card_info;
                    const cardMessage = `邮件获取成功！剩余使用次数: ${{cardInfo.remaining_uses}}/${{cardInfo.total_uses}}`;
                    showToast(cardMessage, 'success', 5000);
                }}
            }}
        }}
        
        function showMessage(text, type) {{
            showToast(text, type);
        }}
        
        function isValidEmail(email) {{
            const re = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
            return re.test(email);
        }}
        
        // Toast notification system
        function showToast(message, type = 'info', duration = 3000) {{
            const container = document.getElementById('toast-container');
            
            const toast = document.createElement('div');
            toast.className = `toast ${{type}}`;
            toast.textContent = message;
            
            container.appendChild(toast);
            
            setTimeout(() => {{
                toast.classList.add('show');
            }}, 10);
            
            setTimeout(() => {{
                toast.classList.remove('show');
                setTimeout(() => {{
                    if (container.contains(toast)) {{
                        container.removeChild(toast);
                    }}
                }}, 300);
            }}, duration);
        }}
        
        function displayImages(images) {{
            const imagesSection = document.getElementById('mailImages');
            const imageContainer = document.getElementById('imageContainer');
            
            if (images && images.length > 0) {{
                imageContainer.innerHTML = '';
                
                images.forEach((image, index) => {{
                    const imageItem = document.createElement('div');
                    imageItem.className = 'image-item';
                    
                    const img = document.createElement('img');
                    img.src = 'data:' + image.mime_type + ';base64,' + image.content;
                    img.alt = image.filename;
                    img.onclick = () => openImageModal(img.src);
                    
                    const imageInfo = document.createElement('div');
                    imageInfo.className = 'image-info';
                    imageInfo.innerHTML = `
                        <div class="attachment-name">${{escapeHtml(image.filename)}}</div>
                        <div class="attachment-meta">${{formatFileSize(image.size)}} • ${{image.mime_type}}</div>
                    `;
                    
                    imageItem.appendChild(img);
                    imageItem.appendChild(imageInfo);
                    imageContainer.appendChild(imageItem);
                }});
                
                imagesSection.style.display = 'block';
            }} else {{
                imagesSection.style.display = 'none';
            }}
        }}
        
        function displayAttachments(attachments) {{
            const attachmentsSection = document.getElementById('mailAttachments');
            const attachmentList = document.getElementById('attachmentList');
            
            if (attachments && attachments.length > 0) {{
                attachmentList.innerHTML = '';
                
                attachments.forEach((attachment, index) => {{
                    const attachmentItem = document.createElement('div');
                    attachmentItem.className = 'attachment-item';
                    
                    const fileExt = attachment.filename.split('.').pop()?.toUpperCase() || '?';
                    
                    attachmentItem.innerHTML = `
                        <div class="attachment-icon">${{fileExt.substring(0, 3)}}</div>
                        <div class="attachment-details">
                            <div class="attachment-name">${{escapeHtml(attachment.filename)}}</div>
                            <div class="attachment-size">${{formatFileSize(attachment.size)}} • ${{attachment.mime_type}}</div>
                        </div>
                    `;
                    
                    attachmentList.appendChild(attachmentItem);
                }});
                
                attachmentsSection.style.display = 'block';
            }} else {{
                attachmentsSection.style.display = 'none';
            }}
        }}
        
        // Image modal functions
        function openImageModal(src) {{
            const modal = document.getElementById('imageModal');
            const modalImg = document.getElementById('modalImage');
            modal.style.display = 'block';
            modalImg.src = src;
        }}
        
        function closeImageModal() {{
            document.getElementById('imageModal').style.display = 'none';
        }}
        
        // Click outside modal to close
        document.getElementById('imageModal').onclick = function(event) {{
            if (event.target === this) {{
                closeImageModal();
            }}
        }}
        
        // Escape key to close modal
        document.addEventListener('keydown', function(event) {{
            if (event.key === 'Escape') {{
                closeImageModal();
            }}
        }});
        
        // Utility functions
        function escapeHtml(text) {{
            const map = {{
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            }};
            return text.replace(/[&<>"']/g, function(m) {{ return map[m]; }});
        }}
        
        function formatFileSize(bytes) {{
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }}
    </script>
</body>
</html>"""
        
        return api_content, 200, {'Content-Type': 'text/html; charset=utf-8'}
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'生成API页面失败: {str(e)}'
        }), 500

@app.route('/admin/api/card-logs')
@admin_required
def api_admin_card_logs():
    """卡密日志 API（Stub实现）"""
    return jsonify({
        'success': True,
        'message': '卡密日志功能正在开发中',
        'data': []
    })

@app.route('/admin/api/recycle-bin')
@admin_required
def api_admin_recycle_bin():
    """获取回收站数据 API"""
    try:
        recycle_type = request.args.get('type', 'deleted')  # deleted 或 expired
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        # 获取回收站数据
        if db_type == 'sqlite':
            if recycle_type == 'deleted':
                cards = db.execute('''
                    SELECT * FROM card_recycle_bin 
                    WHERE recycle_type = 'deleted' 
                    ORDER BY deleted_at DESC
                ''').fetchall()
            else:  # expired
                cards = db.execute('''
                    SELECT * FROM card_recycle_bin 
                    WHERE recycle_type = 'expired' 
                    ORDER BY deleted_at DESC
                ''').fetchall()
            
            # 获取计数
            counts = {
                'deleted': db.execute('SELECT COUNT(*) as count FROM card_recycle_bin WHERE recycle_type = "deleted"').fetchone()['count'],
                'expired': db.execute('SELECT COUNT(*) as count FROM card_recycle_bin WHERE recycle_type = "expired"').fetchone()['count']
            }
        else:
            cursor = db.cursor()
            if recycle_type == 'deleted':
                cursor.execute('''
                    SELECT * FROM card_recycle_bin 
                    WHERE recycle_type = 'deleted' 
                    ORDER BY deleted_at DESC
                ''')
            else:  # expired
                cursor.execute('''
                    SELECT * FROM card_recycle_bin 
                    WHERE recycle_type = 'expired' 
                    ORDER BY deleted_at DESC
                ''')
            cards = cursor.fetchall()
            
            # 获取计数
            cursor.execute('SELECT COUNT(*) as count FROM card_recycle_bin WHERE recycle_type = %s', ('deleted',))
            deleted_count = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) as count FROM card_recycle_bin WHERE recycle_type = %s', ('expired',))
            expired_count = cursor.fetchone()[0]
            counts = {'deleted': deleted_count, 'expired': expired_count}
        
        return jsonify({
            'success': True,
            'data': [dict(card) for card in cards] if db_type == 'sqlite' else [dict(zip([desc[0] for desc in cursor.description], card)) for card in cards],
            'counts': counts
        })
        
    except Exception as e:
        logger.error(f"Get recycle bin error: {e}")
        return jsonify({
            'success': False,
            'message': f'获取回收站数据失败: {str(e)}'
        })

@app.route('/admin/api/recycle-bin/restore', methods=['POST'])
@admin_required
def api_admin_restore_card():
    """恢复卡密 API (支持单个和批量)"""
    try:
        data = request.get_json()
        card_id = data.get('card_id')
        card_ids = data.get('card_ids')
        recycle_type = data.get('type', 'deleted')
        
        # 确定要恢复的卡密ID列表
        if card_ids:
            # 批量恢复
            ids_to_restore = card_ids
        elif card_id:
            # 单个恢复
            ids_to_restore = [card_id]
        else:
            return jsonify({
                'success': False,
                'message': '缺少卡密ID'
            })
        
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        restored_count = 0
        now = get_beijing_time()  # 使用北京时间
        
        for card_id in ids_to_restore:
            try:
                # 获取回收站中的卡密信息
                if db_type == 'sqlite':
                    recycled_card = db.execute('SELECT * FROM card_recycle_bin WHERE id = ?', (card_id,)).fetchone()
                else:
                    cursor = db.cursor()
                    cursor.execute('SELECT * FROM card_recycle_bin WHERE id = %s', (card_id,))
                    recycled_card = cursor.fetchone()
                
                if not recycled_card:
                    continue
                
                # 转换为字典
                if db_type == 'sqlite':
                    card_data = dict(recycled_card)
                else:
                    columns = [desc[0] for desc in cursor.description]
                    card_data = dict(zip(columns, recycled_card))
                
                # 恢复到主卡密表
                if db_type == 'sqlite':
                    db.execute('''
                        INSERT INTO cards (card_key, usage_limit, used_count, expired_at, bound_email_id, 
                                         email_days_filter, sender_filter, remarks, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ''', (card_data['card_key'], card_data['usage_limit'], card_data['used_count'],
                          card_data['expired_at'], card_data['bound_email_id'], card_data['email_days_filter'],
                          card_data['sender_filter'], card_data['remarks'], card_data['created_at'], now))
                    
                    # 从回收站删除
                    db.execute('DELETE FROM card_recycle_bin WHERE id = ?', (card_id,))
                else:
                    cursor = db.cursor()
                    cursor.execute('''
                        INSERT INTO cards (card_key, usage_limit, used_count, expired_at, bound_email_id, 
                                         email_days_filter, sender_filter, remarks, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                    ''', (card_data['card_key'], card_data['usage_limit'], card_data['used_count'],
                          card_data['expired_at'], card_data['bound_email_id'], card_data['email_days_filter'],
                          card_data['sender_filter'], card_data['remarks'], card_data['created_at'], now))
                    
                    # 从回收站删除
                    cursor.execute('DELETE FROM card_recycle_bin WHERE id = %s', (card_id,))
                
                restored_count += 1
                
            except Exception as e:
                logger.error(f"Error restoring card {card_id}: {e}")
                continue
        
        # 提交所有更改
        if db_type == 'sqlite':
            db.commit()
        else:
            db.commit()
        
        if restored_count > 0:
            message = f'成功恢复 {restored_count} 个卡密' if restored_count > 1 else '卡密恢复成功'
            return jsonify({
                'success': True,
                'message': message,
                'restored_count': restored_count
            })
        else:
            return jsonify({
                'success': False,
                'message': '没有找到可恢复的卡密'
            })
        
    except Exception as e:
        logger.error(f"Restore card error: {e}")
        return jsonify({
            'success': False,
            'message': f'恢复卡密失败: {str(e)}'
        })

@app.route('/admin/api/recycle-bin/permanent-delete', methods=['DELETE'])
@admin_required
def api_admin_permanent_delete_card():
    """永久删除卡密 API (支持单个和批量)"""
    try:
        data = request.get_json()
        card_id = data.get('card_id')
        card_ids = data.get('card_ids')
        
        # 确定要删除的卡密ID列表
        if card_ids:
            # 批量删除
            ids_to_delete = card_ids
        elif card_id:
            # 单个删除
            ids_to_delete = [card_id]
        else:
            return jsonify({
                'success': False,
                'message': '缺少卡密ID'
            })
        
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        deleted_count = 0
        
        for card_id in ids_to_delete:
            try:
                if db_type == 'sqlite':
                    result = db.execute('DELETE FROM card_recycle_bin WHERE id = ?', (card_id,))
                    if result.rowcount > 0:
                        deleted_count += 1
                else:
                    cursor = db.cursor()
                    cursor.execute('DELETE FROM card_recycle_bin WHERE id = %s', (card_id,))
                    if cursor.rowcount > 0:
                        deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting card {card_id}: {e}")
                continue
        
        # 提交所有更改
        if db_type == 'sqlite':
            db.commit()
        else:
            db.commit()
        
        if deleted_count > 0:
            message = f'成功永久删除 {deleted_count} 个卡密' if deleted_count > 1 else '卡密永久删除成功'
            return jsonify({
                'success': True,
                'message': message,
                'deleted_count': deleted_count
            })
        else:
            return jsonify({
                'success': False,
                'message': '没有找到可删除的卡密'
            })
        
    except Exception as e:
        logger.error(f"Permanent delete card error: {e}")
        return jsonify({
            'success': False,
            'message': f'永久删除失败: {str(e)}'
        })

@app.route('/admin/api/recycle-bin/clear', methods=['DELETE'])
@admin_required
def api_admin_clear_recycle_bin():
    """清空回收站 API"""
    try:
        db = get_db()
        db_type = app.config['DATABASE_TYPE']
        
        if db_type == 'sqlite':
            db.execute('DELETE FROM card_recycle_bin')
            db.commit()
        else:
            cursor = db.cursor()
            cursor.execute('DELETE FROM card_recycle_bin')
            db.commit()
        
        return jsonify({
            'success': True,
            'message': '回收站清空成功'
        })
        
    except Exception as e:
        logger.error(f"Clear recycle bin error: {e}")
        return jsonify({
            'success': False,
            'message': f'清空回收站失败: {str(e)}'
        })

@app.route('/admin/api/process-expired-cards', methods=['POST'])
@admin_required
def api_admin_process_expired_cards():
    """手动处理过期卡密 API"""
    try:
        process_expired_cards()
        return jsonify({
            'success': True,
            'message': '过期卡密处理完成'
        })
        
    except Exception as e:
        logger.error(f"Process expired cards API error: {e}")
        return jsonify({
            'success': False,
            'message': f'处理过期卡密失败: {str(e)}'
        })

@app.route('/admin/api/mail-logs')
@admin_required
def api_admin_mail_logs():
    """收件日志 API（Stub实现）"""
    return jsonify({
        'success': True,
        'message': '收件日志功能正在开发中',
        'data': []
    })

@app.route('/admin/api/system-config', methods=['GET', 'POST'])
@admin_required
def api_admin_system_config():
    """系统设置 API"""
    db = get_db()
    db_type = app.config['DATABASE_TYPE']
    
    if request.method == 'GET':
        try:
            # 获取当前管理员信息
            current_admin_username = session.get('admin_username', 'admin')
            
            # 获取系统配置
            system_config = {}
            if db_type == 'sqlite':
                config_rows = db.execute('SELECT config_key, config_value FROM system_config').fetchall()
                for row in config_rows:
                    system_config[row['config_key']] = row['config_value']
            else:
                cursor = db.cursor()
                cursor.execute('SELECT config_key, config_value FROM system_config')
                config_rows = cursor.fetchall()
                for row in config_rows:
                    system_config[row[0]] = row[1]
            
            return jsonify({
                'success': True,
                'data': {
                    'system_name': system_config.get('system_name', '邮件查看系统'),
                    'system_title': system_config.get('system_title', '邮件查看系统'),
                    'version': system_config.get('system_version', '2.0.0'),
                    'database_type': app.config['DATABASE_TYPE'],
                    'admin_username': current_admin_username,
                    'api_page_title': system_config.get('api_page_title', 'API取件页面'),
                    'frontend_page_title': system_config.get('frontend_page_title', '邮件查看'),
                    'admin_login_title': system_config.get('admin_login_title', '管理员登录')
                }
            })
        except Exception as e:
            logger.error(f"Get system config error: {e}")
            return jsonify({
                'success': False,
                'message': f'获取系统设置失败: {str(e)}'
            })
    
    else:  # POST
        try:
            data = request.get_json()
            action = data.get('action')
            
            if action == 'update_admin':
                return _update_admin_account(db, db_type, data)
            elif action == 'update_page_titles':
                return _update_page_titles(db, db_type, data)
            elif action == 'update_system_title':
                return _update_system_title(db, db_type, data)
            else:
                return jsonify({
                    'success': False,
                    'message': '未知的操作类型'
                })
                
        except Exception as e:
            logger.error(f"Update system config error: {e}")
            return jsonify({
                'success': False,
                'message': f'更新系统设置失败: {str(e)}'
            })

def _update_admin_account(db, db_type, data):
    """更新管理员账号"""
    new_username = data.get('admin_username', '').strip()
    new_password = data.get('admin_password', '').strip()
    
    if not new_username or not new_password:
        return jsonify({
            'success': False,
            'message': '用户名和密码不能为空'
        })
    
    if len(new_password) < 4:
        return jsonify({
            'success': False,
            'message': '密码长度至少4位'
        })
    
    try:
        current_admin_id = session.get('admin_id')
        
        # 验证当前用户ID
        if not current_admin_id:
            return jsonify({
                'success': False,
                'message': '会话已过期，请重新登录'
            })
        
        # 加密密码（生产环境使用）
        hashed_password = generate_password_hash(new_password)
        
        if db_type == 'sqlite':
            # 检查当前用户是否存在
            current_user = db.execute(
                'SELECT id, username FROM admin_users WHERE id = ?',
                (current_admin_id,)
            ).fetchone()
            
            if not current_user:
                return jsonify({
                    'success': False,
                    'message': '当前管理员用户不存在'
                })
            
            # 检查新用户名是否已存在（排除当前用户）
            if new_username != current_user['username']:
                existing_user = db.execute(
                    'SELECT id FROM admin_users WHERE username = ? AND id != ?', 
                    (new_username, current_admin_id)
                ).fetchone()
                
                if existing_user:
                    return jsonify({
                        'success': False,
                        'message': '用户名已存在'
                    })
            
            # 更新管理员账号
            db.execute(
                'UPDATE admin_users SET username = ?, password = ? WHERE id = ?',
                (new_username, hashed_password, current_admin_id)
            )
            db.commit()
        else:
            cursor = db.cursor()
            
            # 检查当前用户是否存在
            cursor.execute(
                'SELECT id, username FROM admin_users WHERE id = %s',
                (current_admin_id,)
            )
            current_user = cursor.fetchone()
            
            if not current_user:
                return jsonify({
                    'success': False,
                    'message': '当前管理员用户不存在'
                })
            
            # 检查新用户名是否已存在（排除当前用户）
            current_username = current_user[1] if current_user else None
            if new_username != current_username:
                cursor.execute(
                    'SELECT id FROM admin_users WHERE username = %s AND id != %s', 
                    (new_username, current_admin_id)
                )
                existing_user = cursor.fetchone()
                
                if existing_user:
                    return jsonify({
                        'success': False,
                        'message': '用户名已存在'
                    })
            
            # 更新管理员账号
            cursor.execute(
                'UPDATE admin_users SET username = %s, password = %s WHERE id = %s',
                (new_username, hashed_password, current_admin_id)
            )
            db.commit()
        
        # 更新会话中的用户名
        session['admin_username'] = new_username
        
        logger.info(f"Admin account updated: {current_user['username'] if 'current_user' in locals() else 'unknown'} -> {new_username}")
        
        return jsonify({
            'success': True,
            'message': '管理员账号更新成功'
        })
        
    except Exception as e:
        logger.error(f"Update admin account error: {e}")
        return jsonify({
            'success': False,
            'message': f'更新管理员账号失败: {str(e)}'
        })

def _update_page_titles(db, db_type, data):
    """更新页面标题设置"""
    api_page_title = data.get('api_page_title', '').strip()
    frontend_page_title = data.get('frontend_page_title', '').strip()
    admin_login_title = data.get('admin_login_title', '').strip()
    
    if not api_page_title or not frontend_page_title or not admin_login_title:
        return jsonify({
            'success': False,
            'message': '所有页面标题不能为空'
        })
    
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 更新或插入配置项
        config_items = [
            ('api_page_title', api_page_title, 'API取件页面标题'),
            ('frontend_page_title', frontend_page_title, '前端取件页面标题'),
            ('admin_login_title', admin_login_title, '管理员登录页面标题')
        ]
        
        for config_key, config_value, description in config_items:
            if db_type == 'sqlite':
                # 使用 INSERT OR REPLACE 语法
                db.execute('''
                    INSERT OR REPLACE INTO system_config 
                    (config_key, config_value, config_type, description, is_system, created_at, updated_at)
                    VALUES (?, ?, 'string', ?, 0, 
                        COALESCE((SELECT created_at FROM system_config WHERE config_key = ?), ?), 
                        ?)
                ''', (config_key, config_value, description, config_key, now, now))
            else:
                cursor = db.cursor()
                if db_type == 'mysql':
                    # MySQL 使用 ON DUPLICATE KEY UPDATE
                    cursor.execute('''
                        INSERT INTO system_config 
                        (config_key, config_value, config_type, description, is_system, created_at, updated_at)
                        VALUES (%s, %s, 'string', %s, 0, %s, %s)
                        ON DUPLICATE KEY UPDATE 
                        config_value = VALUES(config_value), 
                        updated_at = VALUES(updated_at)
                    ''', (config_key, config_value, description, now, now))
                else:  # PostgreSQL
                    # PostgreSQL 使用 ON CONFLICT
                    cursor.execute('''
                        INSERT INTO system_config 
                        (config_key, config_value, config_type, description, is_system, created_at, updated_at)
                        VALUES (%s, %s, 'string', %s, 0, %s, %s)
                        ON CONFLICT (config_key) DO UPDATE SET 
                        config_value = EXCLUDED.config_value, 
                        updated_at = EXCLUDED.updated_at
                    ''', (config_key, config_value, description, now, now))
        
        if db_type == 'sqlite':
            db.commit()
        else:
            db.commit()
        
        logger.info(f"Page titles updated: API={api_page_title}, Frontend={frontend_page_title}, Admin={admin_login_title}")
        
        return jsonify({
            'success': True,
            'message': '页面标题更新成功'
        })
        
    except Exception as e:
        logger.error(f"Update page titles error: {e}")
        return jsonify({
            'success': False,
            'message': f'更新页面标题失败: {str(e)}'
        })

def _update_system_title(db, db_type, data):
    """更新系统标题设置"""
    system_title = data.get('system_title', '').strip()
    
    if not system_title:
        return jsonify({
            'success': False,
            'message': '系统标题不能为空'
        })
    
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 更新或插入系统标题配置
        if db_type == 'sqlite':
            # 使用 INSERT OR REPLACE 语法
            db.execute('''
                INSERT OR REPLACE INTO system_config 
                (config_key, config_value, config_type, description, is_system, created_at, updated_at)
                VALUES ('system_title', ?, 'string', '系统页面标题', 0, 
                    COALESCE((SELECT created_at FROM system_config WHERE config_key = 'system_title'), ?), 
                    ?)
            ''', (system_title, now, now))
        else:
            cursor = db.cursor()
            if db_type == 'mysql':
                # MySQL 使用 ON DUPLICATE KEY UPDATE
                cursor.execute('''
                    INSERT INTO system_config 
                    (config_key, config_value, config_type, description, is_system, created_at, updated_at)
                    VALUES ('system_title', %s, 'string', '系统页面标题', 0, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                    config_value = VALUES(config_value), 
                    updated_at = VALUES(updated_at)
                ''', (system_title, now, now))
            else:  # PostgreSQL
                # PostgreSQL 使用 ON CONFLICT
                cursor.execute('''
                    INSERT INTO system_config 
                    (config_key, config_value, config_type, description, is_system, created_at, updated_at)
                    VALUES ('system_title', %s, 'string', '系统页面标题', 0, %s, %s)
                    ON CONFLICT (config_key) DO UPDATE SET 
                    config_value = EXCLUDED.config_value, 
                    updated_at = EXCLUDED.updated_at
                ''', (system_title, now, now))
        
        if db_type == 'sqlite':
            db.commit()
        else:
            db.commit()
        
        logger.info(f"System title updated to: {system_title}")
        
        return jsonify({
            'success': True,
            'message': '系统标题更新成功'
        })
        
    except Exception as e:
        logger.error(f"Update system title error: {e}")
        return jsonify({
            'success': False,
            'message': f'更新系统标题失败: {str(e)}'
        })

if __name__ == '__main__':
    # 初始化数据库
    with app.app_context():
        init_db()
    
    # 启动应用（端口8005）
    port = int(os.environ.get('PORT', 8005))
    app.run(debug=False, host='0.0.0.0', port=port)