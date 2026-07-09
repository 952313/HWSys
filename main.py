#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作业管理平台 - 主应用
"""

from flask import Flask, render_template, request, redirect, session, flash, jsonify, send_file
from storage import Storage
from subject_aliases import get_subject_info, search_subjects, get_all_subjects_for_dropdown
from middleware import RequestLogger
import bcrypt
import time
import json
import csv
import io
import random
import string
import os
from functools import wraps
from datetime import datetime, timedelta
from api import api_bp, set_storage
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.debug = config.DEBUG

# ==========================================
# 初始化存储层
# ==========================================
storage = Storage()

# ==========================================
# 注册API
# ==========================================
# 设置 API 的存储实例
set_storage(storage)

# 注册 API Blueprint
app.register_blueprint(api_bp)

# ==========================================
# 启用日志中间件
# ==========================================
if config.ENABLE_REQUEST_LOGGER:
    logger = RequestLogger(app, storage)

# ==========================================
# 配置
# ==========================================
ALLOW_TEACHER_ANY_SUBJECT = config.ALLOW_TEACHER_ANY_SUBJECT
USERS_PER_PAGE = config.USERS_PER_PAGE

# ==========================================
# 导入进度追踪
# ==========================================
import_progress = {
    'status': 'idle',
    'total': 0,
    'processed': 0,
    'success': 0,
    'error': 0,
    'message': '',
    'errors': []
}
# ==========================================
# 辅助函数
# ==========================================
def get_home_for_role():
    """根据用户角色返回正确的首页链接"""
    if 'user_id' not in session:
        return '/', '登录页面'
    
    role = session.get('role')
    if role == 'admin':
        return '/admin', '管理后台'
    elif role == 'technician':
        return '/monitor', '监控面板'
    else:
        return '/page', '首页'


def get_user_classes_for_page(user_id, role):
    classes = storage.get_user_classes(user_id)
    if role == 'teacher' and not classes:
        classes = storage._query('''
            SELECT c.id as class_id, c.name as class_name, 0 as is_primary, 0 as class_number
            FROM teacher_assignments ta
            JOIN classes c ON ta.class_id = c.id
            WHERE ta.teacher_id = ?
            GROUP BY c.id, c.name
            ORDER BY c.name
        ''', (user_id,), db='user')
    return classes


def get_user_primary_class_for_page(user_id, role):
    primary_class = storage.get_user_primary_class(user_id)
    if primary_class:
        return primary_class
    if role == 'teacher':
        return storage._query_one('''
            SELECT c.id as class_id, c.name as class_name, 0 as class_number
            FROM teacher_assignments ta
            JOIN classes c ON ta.class_id = c.id
            WHERE ta.teacher_id = ?
            ORDER BY c.name
            LIMIT 1
        ''', (user_id,), db='user')
    return None

# ==========================================
# 限流配置
# ==========================================
rate_limit = {}

def is_rate_limited(ip, action, limit=None, window=None):
    if action == 'login':
        limit, window = config.RATE_LIMIT_LOGIN
    elif action == 'write':
        limit, window = config.RATE_LIMIT_WRITE
    else:
        limit, window = config.RATE_LIMIT_READ

    key = f"{ip}:{action}"
    now = time.time()

    if key not in rate_limit:
        rate_limit[key] = []

    rate_limit[key] = [t for t in rate_limit[key] if now - t < window]

    if len(rate_limit[key]) >= limit:
        return True, len(rate_limit[key]) - limit + 1

    rate_limit[key].append(now)
    return False, 0


# ==========================================
# 权限装饰器
# ==========================================

def require_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'error')
            return redirect('/')
        return f(*args, **kwargs)
    return decorated_function


def require_role(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('请先登录', 'error')
                return redirect('/')
            if session.get('role') not in roles:
                flash('权限不足', 'error')
                return redirect('/page')
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==========================================
# 页面路由
# ==========================================

@app.route('/')
def index():
    if 'user_id' not in session:
        return render_template('login.html')
    
    role = session.get('role')
    
    if role == 'admin':
        return redirect('/admin')
    elif role == 'technician':
        return redirect('/monitor')
    else:
        return redirect('/page')


@app.route('/login', methods=['POST'])
def login():
    ip = request.remote_addr
    is_limited, _ = is_rate_limited(ip, 'login')
    if is_limited:
        flash(f'登录尝试过于频繁，请等待 {config.RATE_LIMIT_LOGIN[1]} 秒后重试', 'error')
        return redirect('/')

    username = request.form.get('username')
    password = request.form.get('password')
    remember_me = request.form.get('remember_me') == 'on'

    user_data = storage.get_user_by_username(username)

    if not user_data:
        flash('学号或密码错误', 'error')
        return redirect('/')

    if not bcrypt.checkpw(password.encode('utf-8'), user_data['password_hash']):
        flash('学号或密码错误', 'error')
        return redirect('/')

    session['user_id'] = user_data['id']
    session['username'] = user_data['username']
    session['student_id'] = user_data.get('student_id', '')
    session['role'] = user_data['role']
    session['name'] = user_data['name']

    if remember_me:
        session.permanent = True
        app.permanent_session_lifetime = timedelta(days=config.SESSION_REMEMBER_DAYS)
    else:
        session.permanent = True
        app.permanent_session_lifetime = timedelta(hours=config.SESSION_NORMAL_HOURS)

    if user_data['first_login']:
        return redirect('/change_password')

    if session['role'] == 'admin':
        return redirect('/admin')
    elif session['role'] == 'technician':
        return redirect('/monitor')
    else:
        return redirect('/page')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# ==========================================
# 修改密码
# ==========================================

@app.route('/change_password', methods=['GET', 'POST'])
@require_login
def change_password():
    if request.method == 'GET':
        return render_template('change_password.html')

    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if new_password != confirm_password:
        flash('两次输入密码不一致', 'error')
        return render_template('change_password.html')
    if len(new_password) < 6:
        flash('密码至少 6 位', 'error')
        return render_template('change_password.html')

    user_data = storage.get_user_by_username(session['username'])
    if not bcrypt.checkpw(old_password.encode('utf-8'), user_data['password_hash']):
        flash('旧密码错误', 'error')
        return render_template('change_password.html')

    new_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
    storage._enqueue_write(
        "UPDATE users SET password_hash = ?, first_login = 0 WHERE id = ?",
        (new_hash, session['user_id']),
        cache_keys=[f'user:username:{user_data["username"]}'],
        db='user'
    )
    flash('密码修改成功！', 'success')
    return redirect('/page')


# ==========================================
# 主页（学生/老师/课代表）- 支持日期过滤
# ==========================================

@app.route('/page')
@require_login
def page():
    user_id = session['user_id']
    role = session.get('role')

    # 获取用户的所有班级
    user_classes = get_user_classes_for_page(user_id, role)
    class_ids = [uc['class_id'] for uc in user_classes]
    class_names = {uc['class_id']: uc['class_name'] for uc in user_classes}

    # 获取用户的主班级
    primary_class = get_user_primary_class_for_page(user_id, role)
    primary_class_name = primary_class['class_name'] if primary_class else '未分配'
    class_number = ''
    if primary_class and primary_class['class_number']:
        class_number = f" #{primary_class['class_number']}"

    # 班级筛选
    filter_class_id = request.args.get('class_id', type=int)
    if filter_class_id and filter_class_id in class_ids:
        filter_class_ids = [filter_class_id]
        filter_class_name = class_names.get(filter_class_id, '')
    else:
        filter_class_ids = class_ids
        filter_class_name = '全部班级'

    # ====== 日期过滤 ======
    date_filter = request.args.get('date', '').strip()
    date_filter_type = request.args.get('date_type', 'due')  # 'due' 或 'created'
    is_filtered = False
    
    # 构建日期过滤条件
    date_condition = ""
    date_params = []
    
    if date_filter:
        try:
            # 解析日期 (YYYY-MM-DD)
            date_ts_start = int(time.mktime(time.strptime(date_filter, '%Y-%m-%d')))
            date_ts_end = date_ts_start + 86400  # 加一天
            is_filtered = True
            
            if date_filter_type == 'due':
                date_condition = "AND a.due_date >= ? AND a.due_date < ?"
            else:  # 'created'
                date_condition = "AND a.created_at >= ? AND a.created_at < ?"
            date_params = [date_ts_start, date_ts_end]
        except ValueError:
            date_filter = ''  # 无效日期，忽略

    # 查询作业
    if filter_class_ids:
        placeholders = ','.join(['?'] * len(filter_class_ids))
        sql = f'''
            SELECT a.*
            FROM assignments a
            WHERE a.class_id IN ({placeholders})
            {date_condition}
            ORDER BY a.due_date ASC, a.created_at ASC
        '''
        params = tuple(filter_class_ids + date_params)
        assignments = storage._query(sql, params, db='work')
        
        # 单独获取创建者名称
        for a in assignments:
            if a.get('created_by'):
                creator = storage._query_one(
                    "SELECT name FROM users WHERE id = ?",
                    (a['created_by'],),
                    db='user'
                )
                a['creator_name'] = creator['name'] if creator else '未知'
            else:
                a['creator_name'] = '未知'
    else:
        assignments = []

    # 获取完成记录
    completions = storage._query(
        "SELECT assignment_id FROM completions WHERE user_id = ?",
        (user_id,),
        db='work'
    )
    completed_ids = [c['assignment_id'] for c in completions]

    # 过滤：不显示以下作业
    # - 已完成且已过期的作业（completed 且截止 < 现在）
    # - 逾期超过 1 天的作业（截止 < 昨天的 00:00） —— 保留昨天截止的作业
    now_ts = int(time.time())
    today_start = int(time.mktime(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timetuple()))
    yesterday_start = today_start - 86400

    filtered_assignments = []
    for a in assignments:
        due = a.get('due_date') or 0
        is_completed = a['id'] in completed_ids

        # 已完成且已经逾期（任意逾期） -> 隐藏
        # 但如果用户是用截止日期过滤并且该作业的截止时间在所选日期范围内，则应显示
        if is_completed and due < now_ts:
            if not (is_filtered and date_filter_type == 'due' and date_ts_start <= due < date_ts_end):
                continue

        # 逾期超过 1 天（截止在昨天之前的日期） -> 隐藏
        if due < yesterday_start:
            continue

        filtered_assignments.append(a)

    assignments = filtered_assignments

    # 权限
    can_create_public = role in ['admin', 'teacher', 'rep']
    can_create_personal = True

    # 课代表负责的科目
    rep_subjects = []
    if role == 'rep' and primary_class:
        rep_subjects = storage._query('''
            SELECT s.standard_name, s.display_name
            FROM rep_assignments ra
            JOIN subjects s ON ra.subject_id = s.id
            WHERE ra.rep_id = ? AND ra.class_id = ?
        ''', (user_id, primary_class['class_id']), db='user')

    # 默认截止日期 = 明天
    default_due_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    # 明天开始时间戳（用于紧急判断）
    tomorrow_start = int(time.mktime((datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0).timetuple()))

    # 获取用户的完整班级列表
    user_classes_full = get_user_classes_for_page(user_id, role)

    # ====== 管理员：获取所有班级的作业（用于修改） ======
    all_class_assignments = []
    if role == 'admin':
        all_class_assignments = storage._query('''
            SELECT a.*, u.name as creator_name, c.name as class_name
            FROM assignments a
            LEFT JOIN users u ON a.created_by = u.id
            LEFT JOIN classes c ON a.class_id = c.id
            ORDER BY a.due_date ASC, a.created_at ASC
        ''', db='work')

    return render_template('index.html',
        user_name=session.get('name'),
        user_role=role,
        user_classes=user_classes_full,
        primary_class_name=primary_class_name,
        class_number=class_number,
        filter_class_id=filter_class_id,
        filter_class_name=filter_class_name,
        assignments=assignments,
        completed_ids=completed_ids,
        can_create_public=can_create_public,
        can_create_personal=can_create_personal,
        rep_subjects=rep_subjects,
        default_due_date=default_due_date,
        get_tomorrow_timestamp=lambda: tomorrow_start,
        now=time.time(),
        # 日期过滤
        date_filter=date_filter,
        date_filter_type=date_filter_type,
        is_filtered=is_filtered,
        # 管理员全部作业
        all_class_assignments=all_class_assignments
    )


# ==========================================
# 创建作业
# ==========================================

@app.route('/assignment/create', methods=['POST'])
@require_login
def create_assignment():
    user_id = session['user_id']
    role = session.get('role')
    class_id = request.form.get('class_id', type=int)

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    subject_input = request.form.get('subject', '').strip()
    due_date_str = request.form.get('due_date', '')
    is_public = request.form.get('is_public') == 'on'

    if not title:
        flash('请输入作业标题', 'error')
        return redirect('/page')

    user_classes = get_user_classes_for_page(user_id, role)
    class_ids = [uc['class_id'] for uc in user_classes]
    if class_id not in class_ids:
        flash('您不属于该班级', 'error')
        return redirect('/page')

    subject_info = get_subject_info(subject_input)
    subject = subject_info['standard']
    subject_display = subject_info['display']
    subject_custom = 1 if subject_info['is_custom'] else 0

    if not subject:
        subject = 'general'
        subject_display = '通用'
        subject_custom = 0

    if role == 'rep':
        rep_subjects = storage._query('''
            SELECT s.standard_name
            FROM rep_assignments ra
            JOIN subjects s ON ra.subject_id = s.id
            WHERE ra.rep_id = ? AND ra.class_id = ?
        ''', (user_id, class_id), db='user')
        rep_subject_names = [rs['standard_name'] for rs in rep_subjects]
        if not subject_info['is_custom'] and subject not in rep_subject_names:
            flash('您只能创建自己负责科目的作业', 'error')
            return redirect('/page')

    if due_date_str:
        due_date = int(time.mktime(time.strptime(due_date_str, '%Y-%m-%d')))
    else:
        due_date = int(time.time() + 7 * 24 * 3600)

    if is_public and role not in ['admin', 'teacher', 'rep']:
        flash('权限不足，无法创建公共作业', 'error')
        return redirect('/page')

    storage._enqueue_write('''
        INSERT INTO assignments
        (title, description, subject, subject_display, subject_custom,
         created_by, class_id, is_public, shared_with, pending_invites,
         created_at, due_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (title, description, subject, subject_display, subject_custom,
          user_id, class_id, 1 if is_public else 0, '[]', '[]',
          int(time.time()), due_date),
        cache_keys=['assignments'],
        db='work'
    )

    flash(f'✅ 作业 "{title}" 创建成功！', 'success')
    return redirect('/page')


# ==========================================
# 完成/取消完成/删除
# ==========================================

@app.route('/assignment/complete/<int:assignment_id>')
@require_login
def complete_assignment(assignment_id):
    user_id = session['user_id']

    assignment = storage._query_one(
        "SELECT * FROM assignments WHERE id = ?",
        (assignment_id,),
        db='work'
    )
    if not assignment:
        flash('作业不存在', 'error')
        return redirect('/page')

    user_classes = storage.get_user_classes(user_id)
    class_ids = [uc['class_id'] for uc in user_classes]
    if assignment['class_id'] not in class_ids:
        flash('您无法完成此作业', 'error')
        return redirect('/page')

    existing = storage._query_one(
        "SELECT id FROM completions WHERE assignment_id = ? AND user_id = ?",
        (assignment_id, user_id),
        db='work'
    )
    if existing:
        flash('你已经完成过这个作业了', 'info')
    else:
        storage._enqueue_write(
            "INSERT INTO completions (assignment_id, user_id, completed_at) VALUES (?, ?, ?)",
            (assignment_id, user_id, int(time.time())),
            db='work'
        )
        flash('✅ 作业已完成！', 'success')

    return redirect('/page')


@app.route('/assignment/uncomplete/<int:assignment_id>')
@require_login
def uncomplete_assignment(assignment_id):
    user_id = session['user_id']
    storage._enqueue_write(
        "DELETE FROM completions WHERE assignment_id = ? AND user_id = ?",
        (assignment_id, user_id),
        db='work'
    )
    flash('🔄 已取消完成状态', 'info')
    return redirect('/page')


@app.route('/assignment/delete/<int:assignment_id>', methods=['GET', 'POST'])
@require_login
def delete_assignment(assignment_id):
    user_id = session['user_id']
    role = session['role']

    assignment = storage._query_one("SELECT * FROM assignments WHERE id = ?", (assignment_id,), db='work')
    if not assignment:
        flash('作业不存在', 'error')
        return redirect('/page')

    can_delete = False
    if role == 'admin':
        can_delete = True
    elif role == 'teacher':
        can_delete = assignment['created_by'] == user_id or assignment['class_id'] == session.get('class_id')
    else:
        can_delete = assignment['created_by'] == user_id

    if not can_delete:
        flash('权限不足', 'error')
        return redirect('/page')

    if request.method == 'GET':
        return render_template('delete_confirm.html',
            assignment=assignment,
            delete_reasons=config.DELETE_REASONS
        )

    reason = request.form.get('reason', '未填写理由')
    storage._enqueue_write(
        "DELETE FROM assignments WHERE id = ?",
        (assignment_id,),
        cache_keys=['assignments'],
        db='work'
    )
    flash(f'🗑️ 已删除作业 "{assignment["title"]}"', 'info')
    return redirect('/page')


# ==========================================
# 管理员后台
# ==========================================

@app.route('/admin')
@require_role(['admin'])
def admin_panel():
    users = storage._query(
        "SELECT id, username, student_id, role, name, first_login, created_at FROM users ORDER BY created_at DESC LIMIT 20",
        db='user'
    )
    classes = storage._query("SELECT * FROM classes ORDER BY name", db='user')
    subjects = storage._query("SELECT * FROM subjects ORDER BY display_name", db='user')

    teacher_assignments = storage._query('''
        SELECT ta.*, u.name as teacher_name, c.name as class_name, s.display_name as subject_name
        FROM teacher_assignments ta
        JOIN users u ON ta.teacher_id = u.id
        JOIN classes c ON ta.class_id = c.id
        JOIN subjects s ON ta.subject_id = s.id
        ORDER BY u.name, c.name
    ''', db='user')

    rep_assignments = storage._query('''
        SELECT ra.*, u.name as rep_name, c.name as class_name, s.display_name as subject_name
        FROM rep_assignments ra
        JOIN users u ON ra.rep_id = u.id
        JOIN classes c ON ra.class_id = c.id
        JOIN subjects s ON ra.subject_id = s.id
        ORDER BY u.name, c.name
    ''', db='user')

    total_users = storage._query_one("SELECT COUNT(*) as total FROM users", db='user')
    total_users = total_users['total'] if total_users else 0

    return render_template('admin.html',
        users=users,
        classes=classes,
        subjects=subjects,
        teacher_assignments=teacher_assignments,
        rep_assignments=rep_assignments,
        total_users=total_users,
        now=time.strftime('%Y-%m-%d %H:%M:%S')
    )


# ==========================================
# 管理员 - 用户列表（分页）
# ==========================================

@app.route('/admin/users')
@require_role(['admin'])
def admin_users():
    page = request.args.get('page', 1, type=int)
    per_page = USERS_PER_PAGE
    search = request.args.get('search', '').strip()

    offset = (page - 1) * per_page
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE username LIKE ? OR name LIKE ? OR student_id LIKE ?"
        params = [f'%{search}%', f'%{search}%', f'%{search}%']

    count_sql = f"SELECT COUNT(*) as total FROM users {where_clause}"
    total_result = storage._query_one(count_sql, tuple(params) if params else (), db='user')
    total = total_result['total'] if total_result else 0
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    sql = f"""
        SELECT id, username, student_id, role, name, first_login, created_at
        FROM users {where_clause}
        ORDER BY username ASC
        LIMIT ? OFFSET ?
    """
    users = storage._query(sql, tuple(params + [per_page, offset]), db='user')

    for u in users:
        user_classes = storage.get_user_classes(u['id'])
        u['classes'] = [{'class_id': uc['class_id'], 'class_name': uc['class_name'], 'class_number': uc['class_number']}
                        for uc in user_classes]

    classes = storage._query("SELECT id, name FROM classes ORDER BY name", db='user')
    class_map = {c['id']: c['name'] for c in classes}

    return render_template('admin_users.html',
        users=users,
        class_map=class_map,
        classes=classes,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
        search=search
    )


# ==========================================
# 管理员 - 批量修改班级
# ==========================================

@app.route('/admin/users/batch_update_classes', methods=['POST'])
@require_role(['admin'])
def admin_batch_update_classes():
    action = request.form.get('action')
    class_id = request.form.get('class_id', type=int)
    user_ids = request.form.getlist('user_ids')

    if not user_ids or not class_id:
        flash('请选择用户和班级', 'error')
        return redirect('/admin/users')

    class_data = storage._query_one("SELECT name FROM classes WHERE id = ?", (class_id,), db='user')
    if not class_data:
        flash('班级不存在', 'error')
        return redirect('/admin/users')

    class_name = class_data['name']
    count = 0

    for uid in user_ids:
        uid = int(uid)
        if uid == session['user_id']:
            continue

        if action == 'add':
            existing = storage._query_one(
                "SELECT id FROM user_classes WHERE user_id = ? AND class_id = ?",
                (uid, class_id),
                db='user'
            )
            if not existing:
                storage._enqueue_write('''
                    INSERT INTO user_classes (user_id, class_id, is_primary, class_number)
                    VALUES (?, ?, ?, ?)
                ''', (uid, class_id, 0, 0), db='user')
                count += 1
        elif action == 'remove':
            storage._enqueue_write(
                "DELETE FROM user_classes WHERE user_id = ? AND class_id = ?",
                (uid, class_id),
                db='user'
            )
            count += 1
        elif action == 'set':
            storage._enqueue_write(
                "DELETE FROM user_classes WHERE user_id = ?",
                (uid,),
                db='user'
            )
            storage._enqueue_write('''
                INSERT INTO user_classes (user_id, class_id, is_primary, class_number)
                VALUES (?, ?, ?, ?)
            ''', (uid, class_id, 1, 0), db='user')
            count += 1

    flash(f'✅ 已更新 {count} 个用户的班级（{class_name}）', 'success')
    return redirect('/admin/users')


# ==========================================
# 管理员 - 导入用户（带进度）
# ==========================================

@app.route('/admin/import/progress')
@require_role(['admin'])
def import_progress_api():
    return jsonify(import_progress)

@app.route('/admin/import', methods=['POST'])
@require_role(['admin'])
def admin_import_users():
    print("=" * 60)
    print("🔥🔥🔥 admin_import_users 被调用了！")
    print("=" * 60)
    global import_progress

    file = request.files.get('csv_file')
    if not file:
        flash('请选择CSV文件', 'error')
        return redirect('/admin')

    default_role = request.form.get('default_role', 'student')
    default_password = request.form.get('default_password', '123456')

    import_progress = {
        'status': 'running',
        'total': 0,
        'processed': 0,
        'success': 0,
        'error': 0,
        'message': '正在解析文件...',
        'errors': []
    }

    try:
        raw_data = file.read()
        try:
            content = raw_data.decode('utf-8')
        except UnicodeDecodeError:
            try:
                content = raw_data.decode('gbk')
            except UnicodeDecodeError:
                content = raw_data.decode('gb18030')

        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        rows = [r for r in rows if r and any(cell.strip() for cell in r)]

        print(f"📊 解析到 {len(rows)} 行数据")
        if rows:
            print(f"📊 第一行: {rows[0]}")

        if not rows:
            import_progress['status'] = 'error'
            import_progress['message'] = '文件为空'
            flash('文件为空', 'error')
            return redirect('/admin')

        first_row = rows[0]
        has_header = any(keyword in str(first_row).lower() for keyword in ['学号', '姓名', '班级', 'username', 'name'])
        if has_header:
            print("📊 检测到表头，跳过第一行")
            rows = rows[1:]

        total = len(rows)
        import_progress['total'] = total
        import_progress['message'] = f'开始导入 {total} 条记录...'

        success_count = 0
        error_count = 0
        errors = []

        # ====== 步骤1：收集所有班级 ======
        print("📊 步骤1: 收集所有班级...")
        all_classes = set()
        for row in rows:
            if len(row) > 3 and row[3].strip():
                for c in row[3].split(config.CSV_CLASS_SEPARATOR):
                    c = c.strip()
                    if c:
                        all_classes.add(c)

        print(f"📊 需要创建的班级: {all_classes}")

        class_cache = {}
        for class_name in all_classes:
            class_name = class_name.strip()  # ✅ 去掉空格
            existing = storage._query_one(
                "SELECT id FROM classes WHERE name = ?",
                (class_name,),
                db='user'
            )
            if existing:
                class_cache[class_name] = existing['id']
                print(f"   ✅ 班级已存在: {class_name} -> id={existing['id']}")
            else:
                storage._execute(
                    "INSERT INTO classes (name, created_at) VALUES (?, ?)",
                    (class_name, int(time.time())),
                    db='user'
                )
                existing = storage._query_one(
                    "SELECT id FROM classes WHERE name = ?",
                    (class_name,),
                    db='user'
                )
                class_cache[class_name] = existing['id'] if existing else None
                print(f"   ✅ 已创建班级: {class_name} -> id={class_cache[class_name]}")

        print(f"📊 class_cache: {class_cache}")

        # ====== 步骤2：逐条处理用户 ======
        print(f"\n📊 步骤2: 开始处理 {total} 个用户...")

        for idx, row in enumerate(rows):
            import_progress['processed'] = idx + 1

            if len(row) < 2 or not row[0].strip():
                continue

            student_id = row[0].strip()
            name = row[1].strip() if len(row) > 1 else student_id

            if len(row) > 2 and row[2].strip():
                password = row[2].strip()
            else:
                password = default_password

            class_str = row[3].strip() if len(row) > 3 else ''
            class_number_str = row[4].strip() if len(row) > 4 else '0'
            class_number_int = int(class_number_str) if class_number_str.isdigit() else 0

            print(f"\n🔍 处理第 {idx+1}/{total} 行: {student_id} -> {class_str} (#{class_number_int})")

            try:
                existing_user = storage.get_user_by_student_id(student_id)

                if existing_user:
                    user_id = existing_user['id']
                    print(f"   📌 用户已存在: {student_id} (id={user_id})")

                    storage._execute(
                        "UPDATE users SET name = ? WHERE id = ?",
                        (name, user_id),
                        db='user'
                    )

                    storage._execute(
                        "DELETE FROM user_classes WHERE user_id = ?",
                        (user_id,),
                        db='user'
                    )

                    if class_str:
                        class_list = [c.strip() for c in class_str.split(config.CSV_CLASS_SEPARATOR) if c.strip()]
                        is_primary = 1

                        for class_name in class_list:
                            class_name = class_name.strip()  # ✅ 去掉空格
                            class_id = class_cache.get(class_name)
                            print(f"   📌 查找班级: '{class_name}' -> class_id={class_id}")
                            if class_id:
                                cnum = class_number_int if is_primary else 0
                                storage._execute('''
                                    INSERT INTO user_classes (user_id, class_id, is_primary, class_number)
                                    VALUES (?, ?, ?, ?)
                                ''', (user_id, class_id, is_primary, cnum), db='user')
                                print(f"   ✅ 关联班级: {class_name} (id={class_id}, cnum={cnum})")
                                is_primary = 0
                            else:
                                print(f"   ❌ 班级 '{class_name}' 在 class_cache 中不存在!")
                else:
                    print(f"   📌 创建新用户: {student_id}")
                    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
                    storage._execute('''
                        INSERT INTO users (username, student_id, password_hash, role, name, first_login, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (student_id, student_id, password_hash, default_role, name, 1, int(time.time())),
                        db='user'
                    )
                    print(f"   ✅ 已创建用户: {student_id}")

                    new_user = storage.get_user_by_student_id(student_id)
                    if new_user:
                        user_id = new_user['id']
                        print(f"   📌 新用户ID: {user_id}")

                        if class_str:
                            class_list = [c.strip() for c in class_str.split(config.CSV_CLASS_SEPARATOR) if c.strip()]
                            is_primary = 1

                            for class_name in class_list:
                                class_name = class_name.strip()  # ✅ 去掉空格
                                class_id = class_cache.get(class_name)
                                print(f"   📌 查找班级: '{class_name}' -> class_id={class_id}")
                                if class_id:
                                    cnum = class_number_int if is_primary else 0
                                    storage._execute('''
                                        INSERT INTO user_classes (user_id, class_id, is_primary, class_number)
                                        VALUES (?, ?, ?, ?)
                                    ''', (user_id, class_id, is_primary, cnum), db='user')
                                    print(f"   ✅ 关联班级: {class_name} (id={class_id}, cnum={cnum})")
                                    is_primary = 0
                                else:
                                    print(f"   ❌ 班级 '{class_name}' 在 class_cache 中不存在!")
                    else:
                        print(f"   ❌ 创建用户后查询不到: {student_id}")

                success_count += 1
                import_progress['success'] = success_count
                import_progress['message'] = f'处理中: {idx+1}/{total}'

            except Exception as e:
                error_count += 1
                errors.append(f'学号 {student_id}: {str(e)}')
                import_progress['error'] = error_count
                print(f"   ❌ 导入失败 {student_id}: {e}")
                import traceback
                traceback.print_exc()

        print("\n" + "=" * 60)
        print(f"📊 导入完成! 成功: {success_count}, 失败: {error_count}")
        print("=" * 60)

        import_progress['status'] = 'done'
        import_progress['message'] = f'✅ 导入完成！成功: {success_count} 个，失败: {error_count} 个'
        import_progress['errors'] = errors[:10]

        flash(f'✅ 导入完成！成功: {success_count} 个，失败: {error_count} 个', 'success')
        if errors:
            flash(f'⚠️ 错误详情: {", ".join(errors[:5])}', 'error')

    except Exception as e:
        import_progress['status'] = 'error'
        import_progress['message'] = f'❌ 导入失败: {str(e)}'
        flash(f'❌ 导入失败: {str(e)}', 'error')
        import traceback
        traceback.print_exc()

    return redirect('/admin')

@app.route('/admin/import/template')
@require_role(['admin'])
def admin_import_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['总学号', '姓名', '密码（可选）', '班级列表（多个用&分隔）', '主班级学号'])
    writer.writerow(['s25001', '张三', '123456', '2A&2X', '10'])
    writer.writerow(['s25002', '李四', '123456', '2A', '5'])
    writer.writerow(['s25003', '王五', '', '2B', '3'])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='用户导入模板.csv'
    )


# ==========================================
# 管理员 - 用户管理
# ==========================================

@app.route('/admin/user/create', methods=['POST'])
@require_role(['admin'])
def admin_create_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    name = request.form.get('name', '').strip()
    role = request.form.get('role', 'student')
    class_id = request.form.get('class_id', type=int)

    if not username or not password or not name:
        flash('请填写完整信息', 'error')
        return redirect('/admin')

    existing = storage._query_one("SELECT id FROM users WHERE username = ?", (username,), db='user')
    if existing:
        flash(f'学号 "{username}" 已存在！', 'error')
        return redirect('/admin')

    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    storage._enqueue_write('''
        INSERT INTO users (username, student_id, password_hash, role, name, first_login, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (username, username, password_hash, role, name, 1, int(time.time())),
        cache_keys=['users:all'],
        db='user'
    )

    if class_id:
        new_user = storage.get_user_by_username(username)
        if new_user:
            storage._enqueue_write('''
                INSERT INTO user_classes (user_id, class_id, is_primary, class_number)
                VALUES (?, ?, ?, ?)
            ''', (new_user['id'], class_id, 1, 0), db='user')

    flash(f'✅ 用户 "{username}" ({name}) 创建成功！', 'success')
    return redirect('/admin')


@app.route('/admin/user/delete/<int:user_id>')
@require_role(['admin'])
def admin_delete_user(user_id):
    if user_id == session['user_id']:
        flash('❌ 不能删除自己！', 'error')
        return redirect('/admin')

    user = storage._query_one("SELECT username FROM users WHERE id = ?", (user_id,), db='user')
    if not user:
        flash('❌ 用户不存在', 'error')
        return redirect('/admin')

    storage._enqueue_write("DELETE FROM users WHERE id = ?", (user_id,), cache_keys=['users:all'], db='user')
    storage._enqueue_write("DELETE FROM user_classes WHERE user_id = ?", (user_id,), db='user')
    flash(f'🗑️ 已删除用户 "{user["username"]}"', 'info')
    return redirect('/admin')


@app.route('/admin/user/reset_password/<int:user_id>')
@require_role(['admin'])
def admin_reset_password(user_id):
    user = storage._query_one(
        "SELECT username, student_id FROM users WHERE id = ?",
        (user_id,),
        db='user'
    )
    if not user:
        flash('❌ 用户不存在', 'error')
        return redirect('/admin')

    chars = string.ascii_letters + string.digits
    new_password = ''.join(random.choice(chars) for _ in range(8))
    password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())

    storage._execute(
        "UPDATE users SET password_hash = ?, first_login = 1 WHERE id = ?",
        (password_hash, user_id),
        db='user',
        cache_keys=[
            f'user:username:{user["username"]}',
            f'user:student_id:{user["student_id"]}',
            'users:all'
        ]
    )
    flash(f'🔑 密码已重置为: {new_password}', 'success')
    return redirect('/admin')


# ==========================================
# 管理员 - 班级管理
# ==========================================

@app.route('/admin/class/create', methods=['POST'])
@require_role(['admin'])
def admin_create_class():
    name = request.form.get('name', '').strip()
    if not name:
        flash('请输入班级名称', 'error')
        return redirect('/admin')

    storage._enqueue_write(
        "INSERT INTO classes (name, created_at) VALUES (?, ?)",
        (name, int(time.time())),
        cache_keys=['classes:all'],
        db='user'
    )
    flash(f'✅ 班级 "{name}" 创建成功！', 'success')
    return redirect('/admin')


@app.route('/admin/class/delete/<int:class_id>')
@require_role(['admin'])
def admin_delete_class(class_id):
    storage._enqueue_write("DELETE FROM classes WHERE id = ?", (class_id,), cache_keys=['classes:all'], db='user')
    flash('🗑️ 班级已删除', 'info')
    return redirect('/admin')


# ==========================================
# 管理员 - 科目管理
# ==========================================

@app.route('/admin/subject/create', methods=['POST'])
@require_role(['admin'])
def admin_create_subject():
    name = request.form.get('name', '').strip()
    if not name:
        flash('请输入科目名称', 'error')
        return redirect('/admin')

    storage._enqueue_write(
        "INSERT INTO subjects (standard_name, display_name, is_custom, created_at) VALUES (?, ?, ?, ?)",
        (name, name, 1, int(time.time())),
        cache_keys=['subjects:all'],
        db='user'
    )
    flash(f'✅ 科目 "{name}" 创建成功！', 'success')
    return redirect('/admin')


@app.route('/admin/assignments/export')
@require_role(['admin'])
def admin_export_assignments():
    """导出过期作业为 CSV，参数：days（可选，默认 config.CLEANUP_EXPIRED_DAYS）"""
    days = request.args.get('days', type=int) or config.CLEANUP_EXPIRED_DAYS
    cutoff = int(time.time()) - days * 86400

    assignments = storage._query(
        "SELECT * FROM assignments WHERE due_date < ? ORDER BY due_date",
        (cutoff,),
        db='work'
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'title', 'subject', 'subject_display', 'created_by', 'class_id', 'is_public', 'created_at', 'due_date'])
    for a in assignments:
        writer.writerow([
            a.get('id'), a.get('title'), a.get('subject'), a.get('subject_display'),
            a.get('created_by'), a.get('class_id'), a.get('is_public'), a.get('created_at'), a.get('due_date')
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'assignments_expired_{days}d.csv'
    )


@app.route('/admin/assignments/cleanup', methods=['POST'])
@require_role(['admin'])
def admin_cleanup_assignments():
    """将过期作业移入 recycle_bin 并删除，参数：days（可选），reason（可选）"""
    days = request.form.get('days', type=int) or config.CLEANUP_EXPIRED_DAYS
    reason = request.form.get('reason', '').strip() or '管理员清理'
    cutoff = int(time.time()) - days * 86400

    assignments = storage._query(
        "SELECT * FROM assignments WHERE due_date < ?",
        (cutoff,),
        db='work'
    )

    count = 0
    for a in assignments:
        # 保存到回收站（串行写入到写队列）
        storage._enqueue_write(
            "INSERT INTO recycle_bin (assignment, deleted_by, deleted_at, reason) VALUES (?, ?, ?, ?)",
            (json.dumps(a, ensure_ascii=False), session.get('user_id'), int(time.time()), reason),
            db='work'
        )
        storage._enqueue_write(
            "DELETE FROM assignments WHERE id = ?",
            (a['id'],),
            cache_keys=['assignments'],
            db='work'
        )
        count += 1

    flash(f'✅ 已清理 {count} 个作业（早于 {days} 天）', 'success')
    return redirect('/admin')


# ==========================================
# 管理员 - 老师指派
# ==========================================

@app.route('/admin/teacher/assign', methods=['POST'])
@require_role(['admin'])
def admin_assign_teacher():
    teacher_id = request.form.get('teacher_id', type=int)
    class_id = request.form.get('class_id', type=int)
    subject_id = request.form.get('subject_id', type=int)

    if not teacher_id or not class_id or not subject_id:
        flash('请选择完整信息', 'error')
        return redirect('/admin')

    existing = storage._query_one(
        "SELECT id FROM teacher_assignments WHERE teacher_id = ? AND class_id = ? AND subject_id = ?",
        (teacher_id, class_id, subject_id),
        db='user'
    )
    if existing:
        flash('⚠️ 该指派已存在', 'info')
        return redirect('/admin')

    storage._enqueue_write('''
        INSERT INTO teacher_assignments (teacher_id, class_id, subject_id, created_at)
        VALUES (?, ?, ?, ?)
    ''', (teacher_id, class_id, subject_id, int(time.time())),
        cache_keys=['teacher_assignments'],
        db='user'
    )
    flash('✅ 老师指派成功！', 'success')
    return redirect('/admin')


@app.route('/admin/teacher/remove/<int:assignment_id>')
@require_role(['admin'])
def admin_remove_teacher(assignment_id):
    storage._enqueue_write(
        "DELETE FROM teacher_assignments WHERE id = ?",
        (assignment_id,),
        cache_keys=['teacher_assignments'],
        db='user'
    )
    flash('🗑️ 已移除老师指派', 'info')
    return redirect('/admin')


# ==========================================
# 管理员 - 课代表指派
# ==========================================

@app.route('/admin/rep/assign', methods=['POST'])
@require_role(['admin', 'teacher'])
def admin_assign_rep():
    rep_id = request.form.get('rep_id', type=int)
    class_id = request.form.get('class_id', type=int)
    subject_id = request.form.get('subject_id', type=int)

    if not rep_id or not class_id or not subject_id:
        flash('请选择完整信息', 'error')
        return redirect('/admin')

    existing = storage._query_one(
        "SELECT id FROM rep_assignments WHERE rep_id = ? AND class_id = ? AND subject_id = ?",
        (rep_id, class_id, subject_id),
        db='user'
    )
    if existing:
        flash('⚠️ 该课代表已指派', 'info')
        return redirect('/admin')

    storage._enqueue_write('''
        INSERT INTO rep_assignments (rep_id, class_id, subject_id, created_at)
        VALUES (?, ?, ?, ?)
    ''', (rep_id, class_id, subject_id, int(time.time())),
        cache_keys=['rep_assignments'],
        db='user'
    )

    storage._enqueue_write(
        "UPDATE users SET role = 'rep' WHERE id = ? AND role = 'student'",
        (rep_id,),
        cache_keys=['users:all'],
        db='user'
    )

    flash('✅ 课代表指派成功！', 'success')
    return redirect('/admin')


@app.route('/admin/rep/remove/<int:assignment_id>')
@require_role(['admin', 'teacher'])
def admin_remove_rep(assignment_id):
    rep_assignment = storage._query_one("SELECT * FROM rep_assignments WHERE id = ?", (assignment_id,), db='user')
    if rep_assignment:
        storage._enqueue_write(
            "DELETE FROM rep_assignments WHERE id = ?",
            (assignment_id,),
            cache_keys=['rep_assignments'],
            db='user'
        )
        other_reps = storage._query_one(
            "SELECT id FROM rep_assignments WHERE rep_id = ? LIMIT 1",
            (rep_assignment['rep_id'],),
            db='user'
        )
        if not other_reps:
            storage._enqueue_write(
                "UPDATE users SET role = 'student' WHERE id = ?",
                (rep_assignment['rep_id'],),
                cache_keys=['users:all'],
                db='user'
            )
    flash('🗑️ 已移除课代表指派', 'info')
    return redirect('/admin')


# ==========================================
# 管理员 - 批量删除用户
# ==========================================

@app.route('/admin/users/batch_delete', methods=['POST'])
@require_role(['admin'])
def admin_batch_delete_users():
    user_ids = request.form.getlist('user_ids')
    class_id = request.form.get('class_id', type=int)

    if not user_ids and not class_id:
        flash('请选择要删除的用户或班级', 'error')
        return redirect('/admin/users')

    deleted_count = 0

    if class_id:
        users = storage._query("SELECT id FROM users WHERE id IN (SELECT user_id FROM user_classes WHERE class_id = ?)", (class_id,), db='user')
        for u in users:
            if u['id'] != session['user_id']:
                storage._enqueue_write("DELETE FROM users WHERE id = ?", (u['id'],), cache_keys=['users:all'], db='user')
                storage._enqueue_write("DELETE FROM user_classes WHERE user_id = ?", (u['id'],), db='user')
                deleted_count += 1
        flash(f'🗑️ 已删除班级中的所有用户（{deleted_count} 个）', 'info')
        return redirect('/admin/users')

    for uid in user_ids:
        if int(uid) != session['user_id']:
            storage._enqueue_write("DELETE FROM users WHERE id = ?", (uid,), cache_keys=['users:all'], db='user')
            storage._enqueue_write("DELETE FROM user_classes WHERE user_id = ?", (uid,), db='user')
            deleted_count += 1

    flash(f'🗑️ 已删除 {deleted_count} 个用户', 'info')
    return redirect('/admin/users')


# ==========================================
# 老师 - 课代表指派
# ==========================================

@app.route('/teacher/rep/assign', methods=['GET', 'POST'])
@require_role(['admin', 'teacher'])
def teacher_assign_rep():
    user_id = session['user_id']
    role = session.get('role')

    if role == 'admin':
        teacher_assignments = storage._query('''
            SELECT ta.*, u.name as teacher_name, c.name as class_name, s.display_name as subject_name
            FROM teacher_assignments ta
            JOIN users u ON ta.teacher_id = u.id
            JOIN classes c ON ta.class_id = c.id
            JOIN subjects s ON ta.subject_id = s.id
            ORDER BY c.name, s.display_name
        ''', db='user')
    else:
        teacher_assignments = storage._query('''
            SELECT ta.*, u.name as teacher_name, c.name as class_name, s.display_name as subject_name
            FROM teacher_assignments ta
            JOIN users u ON ta.teacher_id = u.id
            JOIN classes c ON ta.class_id = c.id
            JOIN subjects s ON ta.subject_id = s.id
            WHERE ta.teacher_id = ?
            ORDER BY c.name, s.display_name
        ''', (user_id,), db='user')

    if request.method == 'GET':
        students = storage._query(
            "SELECT id, username, name FROM users WHERE role IN ('student', 'rep') ORDER BY name",
            db='user'
        )
        return render_template('teacher_rep_assign.html',
            teacher_assignments=teacher_assignments,
            students=students
        )

    rep_id = request.form.get('rep_id', type=int)
    assignment_id = request.form.get('assignment_id', type=int)

    if not rep_id or not assignment_id:
        flash('请选择课代表和班级科目', 'error')
        return redirect('/teacher/rep/assign')

    ta = storage._query_one(
        "SELECT teacher_id, class_id, subject_id FROM teacher_assignments WHERE id = ?",
        (assignment_id,),
        db='user'
    )
    if not ta:
        flash('班级科目不存在', 'error')
        return redirect('/teacher/rep/assign')

    if role == 'teacher' and ta['teacher_id'] != user_id:
        flash('您只能指派自己负责的班级科目', 'error')
        return redirect('/teacher/rep/assign')

    existing = storage._query_one(
        "SELECT id FROM rep_assignments WHERE rep_id = ? AND class_id = ? AND subject_id = ?",
        (rep_id, ta['class_id'], ta['subject_id']),
        db='user'
    )
    if existing:
        flash('⚠️ 该课代表已指派', 'info')
        return redirect('/teacher/rep/assign')

    storage._enqueue_write('''
        INSERT INTO rep_assignments (rep_id, class_id, subject_id, created_at)
        VALUES (?, ?, ?, ?)
    ''', (rep_id, ta['class_id'], ta['subject_id'], int(time.time())),
        cache_keys=['rep_assignments'],
        db='user'
    )
    storage._enqueue_write(
        "UPDATE users SET role = 'rep' WHERE id = ?",
        (rep_id,),
        cache_keys=['users:all'],
        db='user'
    )
    flash('✅ 课代表指派成功！', 'success')
    return redirect('/teacher/rep/assign')


# ==========================================
# 技术员 - 监控
# ==========================================

@app.route('/monitor')
@require_role(['technician', 'admin'])
def monitor():
    today = time.strftime('%Y-%m-%d')
    stats = storage.get_daily_stats(today) or {}
    if not stats:
        stats = {'total_visits': 0, 'total_operations': 0, 'total_errors': 0, 'avg_response_ms': 0}
    op_stats = storage.get_operation_stats(today)
    errors = storage.get_recent_errors(20)
    operations = storage.get_recent_operations(50)

    yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
    y_stats = storage.get_daily_stats(yesterday) or {'total_visits': 0}
    visits_change = 0
    if y_stats.get('total_visits', 0) > 0:
        visits_change = round((stats.get('total_visits', 0) - y_stats['total_visits']) / y_stats['total_visits'] * 100, 1)

    return render_template('monitor.html',
        stats={'total_visits': stats.get('total_visits', 0), 'total_operations': stats.get('total_operations', 0), 'total_errors': stats.get('total_errors', 0), 'avg_response_ms': stats.get('avg_response_ms', 0), 'visits_change': visits_change},
        op_stats=op_stats,
        errors=errors,
        operations=operations,
        now=time.strftime('%Y-%m-%d %H:%M:%S')
    )


@app.route('/resolve_error/<int:error_id>')
@require_role(['technician', 'admin'])
def resolve_error(error_id):
    storage._execute("UPDATE error_logs SET resolved = 1 WHERE id = ?", (error_id,), db='work')
    flash('✅ 错误已标记为已解决', 'success')
    return redirect('/monitor')


# ==========================================
# 技术员 - 系统状态 API
# ==========================================

@app.route('/api/system/status')
@require_role(['technician', 'admin'])
def system_status():
    import threading
    import psutil

    queue_size = storage.write_queue.qsize()
    queue_max = storage.write_queue.maxsize
    active_threads = threading.active_count()

    try:
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
    except:
        memory_percent = 0

    return jsonify({
        'queue': {
            'size': queue_size,
            'max': queue_max,
            'full': queue_size >= queue_max
        },
        'threads': {
            'active': active_threads
        },
        'memory': {
            'percent': memory_percent
        },
        'uptime': int(time.time() - storage._init_time) if hasattr(storage, '_init_time') else 0
    })


# ==========================================
# 错误页面处理器
# ==========================================

# ==========================================
# 错误页面处理器
# ==========================================

@app.errorhandler(404)
def page_not_found(e):
    home_url, home_label = get_home_for_role()
    return render_template('error.html', 
        error_code=404, 
        error_message='页面未找到', 
        user_logged_in='user_id' in session,
        home_url=home_url,
        home_label=home_label
    ), 404


@app.errorhandler(429)
def too_many_requests(e):
    home_url, home_label = get_home_for_role()
    return render_template('error.html', 
        error_code=429, 
        error_message='请求过于频繁，请稍后重试', 
        user_logged_in='user_id' in session,
        home_url=home_url,
        home_label=home_label
    ), 429


@app.errorhandler(500)
def internal_server_error(e):
    home_url, home_label = get_home_for_role()
    return render_template('error.html', 
        error_code=500, 
        error_message='服务器内部错误', 
        user_logged_in='user_id' in session,
        home_url=home_url,
        home_label=home_label
    ), 500

# ==========================================
# 模板过滤器
# ==========================================

@app.template_filter('format_timestamp')
def format_timestamp_filter(ts):
    if not ts:
        return '-'
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))


@app.template_filter('format_date')
def format_date_filter(ts):
    if not ts:
        return '-'
    return time.strftime('%Y-%m-%d', time.localtime(ts))


# ==========================================
# 启动应用
# ==========================================

if __name__ == '__main__':
    print("=" * 60)
    print("📚 作业管理平台")
    print("=" * 60)
    print("🌐 访问: http://localhost:5000")
    print("👤 默认管理员: admin / admin123")
    print("=" * 60)
    print("📖 角色权限:")
    print("   admin      - 管理员（全部权限）")
    print("   technician - 技术员（查看监控 + 系统状态）")
    print("   teacher    - 老师（管理班级作业）")
    print("   rep        - 课代表（协助管理）")
    print("   student    - 同学（查看/完成作业）")
    print("=" * 60)
    print("📚 科目系统: 智能匹配 + 自定义科目")
    print("=" * 60)
    print("⏱️ 限流配置:")
    print(f"   登录: {config.RATE_LIMIT_LOGIN[0]}次/{config.RATE_LIMIT_LOGIN[1]}秒")
    print(f"   写操作: {config.RATE_LIMIT_WRITE[0]}次/{config.RATE_LIMIT_WRITE[1]}秒")
    print(f"   读操作: {config.RATE_LIMIT_READ[0]}次/{config.RATE_LIMIT_READ[1]}秒")
    print("=" * 60)
    app.run(debug=config.DEBUG, host=config.HOST, port=config.PORT)