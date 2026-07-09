#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储层 - 双库分离 (用户库 + 作业库)
"""

import sqlite3
import threading
import time
import json
from queue import Queue, Empty
import config


class Storage:
    """存储层主类 - 支持双库分离"""

    def __init__(self):
        # ====== 用户数据库 ======
        self.user_db_path = config.USER_DB_PATH
        self.user_conn = None
        self.user_cursor = None

        # ====== 作业数据库 ======
        self.work_db_path = config.WORK_DB_PATH
        self.work_conn = None
        self.work_cursor = None

        # ====== 缓存 ======
        self.cache = {}
        self.cache_lock = threading.RLock()

        # ====== 写入队列 ======
        self.write_queue = Queue(maxsize=config.WRITE_QUEUE_MAX)
        self.is_running = True
        self._init_time = time.time()

        # ====== 初始化数据库 ======
        self._init_databases()

        # ====== 启动写入线程 ======
        self.writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self.writer_thread.start()

        print(f"✅ Storage 初始化完成")
        print(f"   📁 用户库: {self.user_db_path}")
        print(f"   📁 作业库: {self.work_db_path}")

    # ==========================================
    # 数据库连接管理
    # ==========================================

    def _get_user_conn(self):
        """获取用户数据库连接"""
        if self.user_conn is None:
            self.user_conn = sqlite3.connect(self.user_db_path, check_same_thread=False)
            self.user_conn.row_factory = sqlite3.Row
        return self.user_conn

    def _get_work_conn(self):
        """获取作业数据库连接"""
        if self.work_conn is None:
            self.work_conn = sqlite3.connect(self.work_db_path, check_same_thread=False)
            self.work_conn.row_factory = sqlite3.Row
        return self.work_conn

    def _close_connections(self):
        """关闭所有连接"""
        if self.user_conn:
            self.user_conn.close()
            self.user_conn = None
        if self.work_conn:
            self.work_conn.close()
            self.work_conn = None

    # ==========================================
    # 数据库初始化
    # ==========================================

    def _init_databases(self):
        """初始化两个数据库"""
        self._init_user_db()
        self._init_work_db()

    def _init_user_db(self):
        """初始化用户数据库"""
        conn = self._get_user_conn()
        cursor = conn.cursor()

        # 用户表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                student_id TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                name TEXT NOT NULL,
                first_login INTEGER DEFAULT 1,
                created_at INTEGER NOT NULL
            )
        ''')

        # 班级表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        ''')

        # 科目表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                standard_name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                is_custom INTEGER DEFAULT 0,
                created_at INTEGER
            )
        ''')

        # 用户-班级关联表（支持多班级 + 班级学号）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                class_number INTEGER DEFAULT 0,
                is_primary INTEGER DEFAULT 0,
                UNIQUE(user_id, class_id)
            )
        ''')

        # 教师指派表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS teacher_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        ''')

        # 课代表指派表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rep_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rep_id INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        ''')

        conn.commit()

        # 初始化默认数据
        self._init_default_subjects()
        self._ensure_default_admin()

    def _init_work_db(self):
        """初始化作业数据库"""
        conn = self._get_work_conn()
        cursor = conn.cursor()

        # 作业表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                subject TEXT,
                subject_display TEXT,
                subject_custom INTEGER DEFAULT 0,
                created_by INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                is_public INTEGER DEFAULT 0,
                shared_with TEXT DEFAULT '[]',
                pending_invites TEXT DEFAULT '[]',
                created_at INTEGER NOT NULL,
                due_date INTEGER NOT NULL
            )
        ''')

        # 完成记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                completed_at INTEGER NOT NULL,
                UNIQUE(assignment_id, user_id)
            )
        ''')

        # 分享邀请表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                from_user INTEGER NOT NULL,
                to_user INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL
            )
        ''')

        # 回收站表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recycle_bin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment TEXT NOT NULL,
                deleted_by INTEGER NOT NULL,
                deleted_at INTEGER NOT NULL,
                reason TEXT
            )
        ''')

        # 操作日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                ip TEXT,
                action TEXT,
                path TEXT,
                method TEXT,
                status_code INTEGER,
                duration_ms INTEGER,
                error_message TEXT,
                user_agent TEXT,
                created_at INTEGER
            )
        ''')

        # 错误日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS error_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_type TEXT,
                error_message TEXT,
                stack_trace TEXT,
                path TEXT,
                user_id INTEGER,
                ip TEXT,
                resolved INTEGER DEFAULT 0,
                created_at INTEGER
            )
        ''')

        # 每日统计表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                total_visits INTEGER DEFAULT 0,
                total_operations INTEGER DEFAULT 0,
                total_errors INTEGER DEFAULT 0,
                avg_response_ms INTEGER DEFAULT 0,
                updated_at INTEGER
            )
        ''')

        conn.commit()

    def _init_default_subjects(self):
        """初始化默认科目"""
        conn = self._get_user_conn()
        cursor = conn.cursor()

        for (standard, display), aliases in config.PRESET_SUBJECTS.items():
            cursor.execute(
                "SELECT id FROM subjects WHERE standard_name = ?", (standard,)
            )
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO subjects (standard_name, display_name, is_custom, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (standard, display, 0, int(time.time())))

        conn.commit()

    def _ensure_default_admin(self):
        """确保有默认管理员账号"""
        import bcrypt
        conn = self._get_user_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        if not cursor.fetchone():
            password_hash = bcrypt.hashpw(
                config.DEFAULT_ADMIN_PASSWORD.encode('utf-8'),
                bcrypt.gensalt()
            )
            cursor.execute('''
                INSERT INTO users (username, student_id, password_hash, role, name, first_login, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                config.DEFAULT_ADMIN_USERNAME,
                'admin001',
                password_hash,
                'admin',
                config.DEFAULT_ADMIN_NAME,
                0,
                int(time.time())
            ))
            print(f"✅ 默认管理员账号: {config.DEFAULT_ADMIN_USERNAME} / {config.DEFAULT_ADMIN_PASSWORD}")

        conn.commit()

    # ==========================================
    # 写入队列
    # ==========================================

    def _writer_loop(self):
        while self.is_running:
            try:
                task = self.write_queue.get(timeout=1)
                self._execute_write(task)
                self.write_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                print(f"❌ 写入线程错误: {e}")
                self.write_queue.task_done()

    def _invalidate_cache_by_sql(self, sql):
        with self.cache_lock:
            if 'user_classes' in sql:
                keys_to_delete = [k for k in self.cache.keys() if k.startswith('user_classes:')]
                for k in keys_to_delete:
                    del self.cache[k]
            if 'classes' in sql:
                keys_to_delete = [k for k in self.cache.keys() if 'classes' in k]
                for k in keys_to_delete:
                    del self.cache[k]
            if 'users' in sql:
                keys_to_delete = [k for k in self.cache.keys() if k.startswith('user:') or k == 'users:all']
                for k in keys_to_delete:
                    del self.cache[k]

    def _execute_write(self, task):
        try:
            db_type = task.get('db', 'work')  # 'user' or 'work'
            if db_type == 'user':
                conn = self._get_user_conn()
            else:
                conn = self._get_work_conn()

            cursor = conn.cursor()
            cursor.execute(task['sql'], task.get('params', ()))
            conn.commit()

            if task.get('return_id'):
                task['result'] = cursor.lastrowid

            if task.get('cache_keys'):
                with self.cache_lock:
                    for key in task['cache_keys']:
                        if key in self.cache:
                            del self.cache[key]
            self._invalidate_cache_by_sql(task.get('sql', ''))

            if task.get('callback'):
                task['callback'](True, task.get('result'))

        except Exception as e:
            print(f"❌ 写入失败: {e}, SQL: {task.get('sql')}")
            if task.get('callback'):
                task['callback'](False, str(e))

    def _enqueue_write(self, sql, params=None, cache_keys=None,
                       return_id=False, callback=None, db='work'):
        """将写入任务加入队列"""
        task = {
            'sql': sql,
            'params': params or (),
            'cache_keys': cache_keys or [],
            'return_id': return_id,
            'callback': callback,
            'db': db
        }

        if self.write_queue.full():
            print("⚠️ 写入队列已满，等待...")

        self.write_queue.put(task)

    # ==========================================
    # 缓存工具
    # ==========================================

    def _get_cache(self, key):
        with self.cache_lock:
            return self.cache.get(key)

    def _set_cache(self, key, data):
        with self.cache_lock:
            self.cache[key] = data

    def _clear_cache(self, pattern=None):
        with self.cache_lock:
            if pattern:
                keys_to_delete = [k for k in self.cache.keys() if pattern in k]
                for k in keys_to_delete:
                    del self.cache[k]
            else:
                self.cache.clear()

    # ==========================================
    # 查询方法
    # ==========================================

    def _query(self, sql, params=None, cache_key=None, db='work'):
        """执行查询（带缓存）"""
        if cache_key:
            cached = self._get_cache(cache_key)
            if cached is not None:
                return cached

        if db == 'user':
            conn = self._get_user_conn()
        else:
            conn = self._get_work_conn()

        cursor = conn.cursor()
        cursor.execute(sql, params or ())

        columns = [description[0] for description in cursor.description] if cursor.description else []
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.commit()  # SQLite 需要提交以释放锁

        if cache_key:
            self._set_cache(cache_key, results)

        return results

    def _query_one(self, sql, params=None, cache_key=None, db='work'):
        results = self._query(sql, params, cache_key, db)
        return results[0] if results else None

    def _execute(self, sql, params=None, db='work', cache_keys=None):
        """直接执行 SQL（同步），支持可选缓存清理"""
        conn = self._get_work_conn() if db == 'work' else self._get_user_conn()
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()

        # 自动清理相关缓存（若提供 cache_keys 则按其清理；否则对常见表进行智能清理）
        with self.cache_lock:
            if cache_keys:
                for key in cache_keys:
                    if key in self.cache:
                        del self.cache[key]
            else:
                # 当修改 user_classes 时，清除所有按用户缓存的 user_classes
                if 'user_classes' in sql:
                    keys_to_delete = [k for k in self.cache.keys() if k.startswith('user_classes:')]
                    for k in keys_to_delete:
                        del self.cache[k]
                # 当修改 classes 表时，清除 classes:all 缓存
                if 'classes' in sql:
                    if 'classes:all' in self.cache:
                        del self.cache['classes:all']
                # 当修改 users 表时，清除用户缓存
                if 'users' in sql:
                    keys_to_delete = [k for k in self.cache.keys() if k.startswith('user:') or k == 'users:all']
                    for k in keys_to_delete:
                        del self.cache[k]

        self._invalidate_cache_by_sql(sql)

    # ==========================================
    # 用户相关操作
    # ==========================================

    def get_user_by_username(self, username):
        return self._query_one(
            "SELECT * FROM users WHERE username = ?",
            (username,),
            cache_key=f'user:username:{username}',
            db='user'
        )

    def get_user_by_student_id(self, student_id):
        return self._query_one(
            "SELECT * FROM users WHERE student_id = ?",
            (student_id,),
            cache_key=f'user:student_id:{student_id}',
            db='user'
        )

    def get_user_classes(self, user_id):
        """获取用户的所有班级"""
        return self._query('''
            SELECT uc.*, c.name as class_name
            FROM user_classes uc
            JOIN classes c ON uc.class_id = c.id
            WHERE uc.user_id = ?
            ORDER BY uc.is_primary DESC, uc.class_number
        ''', (user_id,), cache_key=f'user_classes:{user_id}', db='user')

    def get_user_primary_class(self, user_id):
        """获取用户的主班级"""
        return self._query_one('''
            SELECT uc.*, c.name as class_name
            FROM user_classes uc
            JOIN classes c ON uc.class_id = c.id
            WHERE uc.user_id = ? AND uc.is_primary = 1
        ''', (user_id,), cache_key=f'user_primary_class:{user_id}', db='user')

    # ==========================================
    # 日志记录
    # ==========================================

    def log_operation(self, user_id, username, ip, action, path, method,
                      status_code, duration_ms, error_message=None, user_agent=None):
        sql = '''
            INSERT INTO operation_logs
            (user_id, username, ip, action, path, method,
             status_code, duration_ms, error_message, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        params = (user_id, username, ip, action, path, method,
                  status_code, duration_ms, error_message, user_agent, int(time.time()))

        self._enqueue_write(sql, params, cache_keys=['daily_stats'], db='work')

    def log_error(self, error_type, error_message, stack_trace, path, user_id, ip):
        sql = '''
            INSERT INTO error_logs
            (error_type, error_message, stack_trace, path, user_id, ip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        '''
        params = (error_type, error_message, stack_trace, path, user_id, ip, int(time.time()))

        self._execute(sql, params, db='work')

    # ==========================================
    # 监控数据查询
    # ==========================================

    def get_daily_stats(self, date=None):
        if not date:
            date = time.strftime('%Y-%m-%d')
        return self._query_one(
            "SELECT * FROM daily_stats WHERE date = ?",
            (date,),
            cache_key=f'daily_stats:{date}',
            db='work'
        )

    def get_recent_errors(self, limit=50):
        return self._query(
            "SELECT * FROM error_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
            cache_key=f'error_logs:recent:{limit}',
            db='work'
        )

    def get_recent_operations(self, limit=100):
        return self._query(
            "SELECT * FROM operation_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
            cache_key=f'operation_logs:recent:{limit}',
            db='work'
        )

    def get_operation_stats(self, date=None):
        if not date:
            date = time.strftime('%Y-%m-%d')

        start_ts = int(time.mktime(time.strptime(date, '%Y-%m-%d')))
        end_ts = start_ts + 86400

        sql = '''
            SELECT
                action,
                COUNT(*) as count,
                AVG(duration_ms) as avg_duration,
                SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) as error_count
            FROM operation_logs
            WHERE created_at >= ? AND created_at < ?
            GROUP BY action
            ORDER BY count DESC
        '''
        return self._query(sql, (start_ts, end_ts), cache_key=f'op_stats:{date}', db='work')

    # ==========================================
    # 关闭
    # ==========================================

    def close(self):
        self.is_running = False
        self.write_queue.join()
        self._close_connections()
        print("✅ Storage 已关闭")


# ==========================================
# 全局实例
# ==========================================
storage = None