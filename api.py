#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 接口模块
提供 RESTful API 供外部调用
"""

from flask import Blueprint, request, jsonify, session
import bcrypt
import time
from datetime import datetime, timedelta
from functools import wraps

# 导入存储层和配置
from storage import Storage
from subject_aliases import get_subject_info, search_subjects
import config

# 创建 Blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api')

# 获取存储实例（使用全局 storage，在 main.py 中设置）
storage = None

def set_storage(storage_instance):
    """设置存储实例"""
    global storage
    storage = storage_instance


# ==========================================
# 辅助函数
# ==========================================

def api_response(success, data=None, message='', code=200):
    """统一 API 响应格式"""
    return jsonify({
        'success': success,
        'data': data,
        'message': message,
        'code': code
    }), code


def require_api_login(f):
    """API 登录检查装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return api_response(False, message='请先登录', code=401), 401
        return f(*args, **kwargs)
    return decorated_function


def require_api_role(roles):
    """API 角色检查装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return api_response(False, message='请先登录', code=401), 401
            if session.get('role') not in roles:
                return api_response(False, message='权限不足', code=403), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_user_classes(user_id):
    """获取用户的所有班级"""
    return storage._query('''
        SELECT uc.*, c.name as class_name
        FROM user_classes uc
        JOIN classes c ON uc.class_id = c.id
        WHERE uc.user_id = ?
        ORDER BY uc.is_primary DESC, uc.class_number
    ''', (user_id,), db='user')


# ==========================================
# 限流（复用 main.py 的限流）
# ==========================================

rate_limit = {}

def is_rate_limited_api(ip, action, limit=10, window=60):
    """API 限流，默认 60 秒内 10 次"""
    key = f"api:{ip}:{action}"
    now = time.time()
    
    if key not in rate_limit:
        rate_limit[key] = []
    
    rate_limit[key] = [t for t in rate_limit[key] if now - t < window]
    
    if len(rate_limit[key]) >= limit:
        return True
    
    rate_limit[key].append(now)
    return False


# ==========================================
# API 路由
# ==========================================

# ---------- 认证 ----------

@api_bp.route('/login', methods=['POST'])
def api_login():
    """
    用户登录
    
    请求体:
        {
            "username": "admin",
            "password": "admin123"
        }
    
    响应:
        {
            "success": true,
            "data": {
                "id": 1,
                "username": "admin",
                "role": "admin",
                "name": "系统管理员"
            },
            "message": "登录成功",
            "code": 200
        }
    """
    # 限流
    ip = request.remote_addr
    if is_rate_limited_api(ip, 'login', limit=5, window=60):
        return api_response(False, message='登录尝试过于频繁，请稍后重试', code=429), 429
    
    data = request.get_json()
    if not data:
        return api_response(False, message='请提供用户名和密码', code=400), 400
    
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return api_response(False, message='用户名和密码不能为空', code=400), 400
    
    # 查询用户
    user_data = storage.get_user_by_username(username)
    
    if not user_data:
        return api_response(False, message='用户名或密码错误', code=401), 401
    
    # 验证密码
    if not bcrypt.checkpw(password.encode('utf-8'), user_data['password_hash']):
        return api_response(False, message='用户名或密码错误', code=401), 401
    
    # 设置 Session
    session['user_id'] = user_data['id']
    session['username'] = user_data['username']
    session['student_id'] = user_data.get('student_id', '')
    session['role'] = user_data['role']
    session['name'] = user_data['name']
    
    # 返回用户信息（不包含密码哈希）
    user_info = {
        'id': user_data['id'],
        'username': user_data['username'],
        'student_id': user_data.get('student_id', ''),
        'role': user_data['role'],
        'name': user_data['name'],
        'first_login': bool(user_data['first_login'])
    }
    
    return api_response(True, data=user_info, message='登录成功')


@api_bp.route('/logout', methods=['POST'])
@require_api_login
def api_logout():
    """
    用户登出
    
    响应:
        {
            "success": true,
            "message": "登出成功",
            "code": 200
        }
    """
    session.clear()
    return api_response(True, message='登出成功')


@api_bp.route('/profile', methods=['GET'])
@require_api_login
def api_profile():
    """
    获取当前用户信息
    
    响应:
        {
            "success": true,
            "data": {
                "id": 1,
                "username": "admin",
                "student_id": "admin001",
                "role": "admin",
                "name": "系统管理员",
                "classes": [...]
            },
            "code": 200
        }
    """
    user_id = session['user_id']
    
    user_data = storage._query_one(
        "SELECT id, username, student_id, role, name, first_login, created_at FROM users WHERE id = ?",
        (user_id,),
        db='user'
    )
    
    if not user_data:
        return api_response(False, message='用户不存在', code=404), 404
    
    # 获取用户班级
    user_classes = storage._query('''
        SELECT uc.*, c.name as class_name
        FROM user_classes uc
        JOIN classes c ON uc.class_id = c.id
        WHERE uc.user_id = ?
        ORDER BY uc.is_primary DESC, uc.class_number
    ''', (user_id,), db='user')
    
    user_data['classes'] = user_classes
    
    return api_response(True, data=user_data)


@api_bp.route('/subjects/search', methods=['GET'])
@require_api_login
def api_subjects_search():
    query = request.args.get('q', '').strip()
    results = search_subjects(query)
    return api_response(True, data={'results': results})


    """
    获取作业列表
    
    查询参数:
        class_id: 可选，筛选班级
        status: 可选，pending/completed/all（默认 all）
    
    响应:
        {
            "success": true,
            "data": {
                "total": 10,
                "pending": [...],
                "completed": [...]
            },
            "code": 200
        }
    """
    user_id = session['user_id']
    role = session.get('role')
    
    # 获取用户班级
    user_classes = storage.get_user_classes(user_id)
    class_ids = [uc['class_id'] for uc in user_classes]
    
    # 筛选班级
    filter_class_id = request.args.get('class_id', type=int)
    if filter_class_id and filter_class_id in class_ids:
        filter_class_ids = [filter_class_id]
    else:
        filter_class_ids = class_ids
    
    if not filter_class_ids:
        return api_response(True, data={'total': 0, 'pending': [], 'completed': []})
    
    # 查询作业
    placeholders = ','.join(['?'] * len(filter_class_ids))
    sql = f'''
        SELECT a.*, u.name as creator_name
        FROM assignments a
        LEFT JOIN users u ON a.created_by = u.id
        WHERE a.class_id IN ({placeholders})
        ORDER BY (a.due_year*10000 + a.due_month*100 + a.due_day) ASC, a.created_at ASC
    '''
    assignments = storage._query(sql, tuple(filter_class_ids), db='work')
    
    # 获取完成记录
    completions = storage._query(
        "SELECT assignment_id FROM completions WHERE user_id = ?",
        (user_id,),
        db='work'
    )
    completed_ids = [c['assignment_id'] for c in completions]
    
    # 分类
    pending = []
    completed = []
    
    for a in assignments:
        a['creator_name'] = a.get('creator_name', '')
        # 过滤（与主页一致）：
        # - 已完成且已过期的作业不显示
        # - 逾期超过 1 天的作业不显示（截止 < 昨天 00:00）
        # 以日为单位比较
        now_ts = int(time.time())
        today = datetime.now()
        today_index = today.year * 10000 + today.month * 100 + today.day
        yesterday = today - timedelta(days=1)
        yesterday_index = yesterday.year * 10000 + yesterday.month * 100 + yesterday.day
        y = int(a.get('due_year') or 0)
        m = int(a.get('due_month') or 0)
        d = int(a.get('due_day') or 0)
        due = (y * 10000 + m * 100 + d) if y and m and d else 0
        is_completed = a['id'] in completed_ids

        if is_completed and due and due < today_index:
            continue
        if due and due < yesterday_index:
            continue

        if is_completed:
            completed.append(a)
        else:
            pending.append(a)
    
    return api_response(True, data={
        'total': len(assignments),
        'pending': pending,
        'completed': completed
    })


@api_bp.route('/homework/detail/<int:homework_id>', methods=['GET'])
@require_api_login
def api_homework_detail(homework_id):
    """
    获取作业详情
    
    响应:
        {
            "success": true,
            "data": {...},
            "code": 200
        }
    """
    user_id = session['user_id']
    
    # 检查作业是否存在
    assignment = storage._query_one(
        "SELECT * FROM assignments WHERE id = ?",
        (homework_id,),
        db='work'
    )
    
    if not assignment:
        return api_response(False, message='作业不存在', code=404), 404
    
    # 检查用户是否有权限查看
    user_classes = storage.get_user_classes(user_id)
    class_ids = [uc['class_id'] for uc in user_classes]
    if assignment['class_id'] not in class_ids:
        return api_response(False, message='无权查看此作业', code=403), 403
    
    # 检查是否已完成
    completion = storage._query_one(
        "SELECT completed_at FROM completions WHERE assignment_id = ? AND user_id = ?",
        (homework_id, user_id),
        db='work'
    )
    assignment['is_completed'] = bool(completion)
    assignment['completed_at'] = completion['completed_at'] if completion else None
    
    return api_response(True, data=assignment)


@api_bp.route('/homework/create', methods=['POST'])
@require_api_login
def api_homework_create():
    """
    创建作业
    
    请求体:
        {
            "title": "数学作业",
            "description": "完成练习题1-10",
            "subject": "数学",
            "class_id": 1,
            "due_date": "2026-07-20",
            "is_public": false
        }
    
    响应:
        {
            "success": true,
            "data": {"id": 1, ...},
            "message": "作业创建成功",
            "code": 200
        }
    """
    user_id = session['user_id']
    role = session.get('role')
    
    data = request.get_json()
    if not data:
        return api_response(False, message='请提供作业信息', code=400), 400
    
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    subject = data.get('subject', '').strip()
    class_id = data.get('class_id', type=int)
    due_date_str = data.get('due_date', '')
    is_public = data.get('is_public', False)
    
    if not title:
        return api_response(False, message='作业标题不能为空', code=400), 400
    
    if not class_id:
        return api_response(False, message='请选择班级', code=400), 400
    
    # 检查用户是否属于该班级
    user_classes = storage.get_user_classes(user_id)
    class_ids = [uc['class_id'] for uc in user_classes]
    if class_id not in class_ids:
        return api_response(False, message='您不属于该班级', code=403), 403
    
    # 处理科目
    subject_info = get_subject_info(subject)
    subject_standard = subject_info['standard']
    subject_display = subject_info['display']
    subject_custom = 1 if subject_info['is_custom'] else 0
    
    if not subject_standard:
        subject_standard = 'general'
        subject_display = '通用'
        subject_custom = 0
    
    # 课代表权限检查
    if role == 'rep':
        rep_subjects = storage._query('''
            SELECT s.standard_name
            FROM rep_assignments ra
            JOIN subjects s ON ra.subject_id = s.id
            WHERE ra.rep_id = ? AND ra.class_id = ?
        ''', (user_id, class_id), db='user')
        rep_subject_names = [rs['standard_name'] for rs in rep_subjects]
        if not subject_info['is_custom'] and subject_standard not in rep_subject_names:
            return api_response(False, message='您只能创建自己负责科目的作业', code=403), 403
    
    # 处理截止日期
    if due_date_str:
        try:
            yy = int(due_date_str[0:4]); mm = int(due_date_str[5:7]); dd = int(due_date_str[8:10])
        except Exception:
            return api_response(False, message='截止日期格式错误，请使用 YYYY-MM-DD', code=400), 400
    else:
        dt = datetime.now() + timedelta(days=7)
        yy, mm, dd = dt.year, dt.month, dt.day
    
    # 公共作业权限检查
    if is_public and role not in ['admin', 'teacher', 'rep']:
        return api_response(False, message='权限不足，无法创建公共作业', code=403), 403
    
    # 插入作业
    result = storage._enqueue_write('''
        INSERT INTO assignments
        (title, description, subject, subject_display, subject_custom,
         created_by, class_id, is_public, shared_with, pending_invites,
         created_at, due_year, due_month, due_day)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (title, description, subject_standard, subject_display, subject_custom,
          user_id, class_id, 1 if is_public else 0, '[]', '[]',
          int(time.time()), yy, mm, dd),
        cache_keys=['assignments'],
        db='work',
        return_id=True
    )
    
    # 获取创建后的作业信息（这里简化处理，实际需要等待写入完成）
    new_assignment = {
        'id': result,
        'title': title,
        'description': description,
        'subject': subject_display,
        'created_by': user_id,
        'class_id': class_id,
        'is_public': is_public,
        'due_date': f"{yy}-{mm:02d}-{dd:02d}"
    }
    
    return api_response(True, data=new_assignment, message='作业创建成功', http_code=201)


@api_bp.route('/homework/mark_finished/<int:homework_id>', methods=['POST'])
@require_api_login
def api_homework_mark_finished(homework_id):
    """
    标记作业为已完成
    
    请求体（可选）:
        {
            "undo": false   # true 表示取消完成
        }
    
    响应:
        {
            "success": true,
            "message": "作业已完成",
            "code": 200
        }
    """
    user_id = session['user_id']
    data = request.get_json() or {}
    undo = data.get('undo', False)
    
    # 检查作业是否存在
    assignment = storage._query_one(
        "SELECT * FROM assignments WHERE id = ?",
        (homework_id,),
        db='work'
    )
    
    if not assignment:
        return api_response(False, message='作业不存在', code=404), 404
    
    # 检查用户是否属于该班级
    user_classes = storage.get_user_classes(user_id)
    class_ids = [uc['class_id'] for uc in user_classes]
    if assignment['class_id'] not in class_ids:
        return api_response(False, message='无权操作此作业', code=403), 403
    
    if undo:
        # 取消完成
        storage._enqueue_write(
            "DELETE FROM completions WHERE assignment_id = ? AND user_id = ?",
            (homework_id, user_id),
            db='work'
        )
        return api_response(True, message='已取消完成状态')
    else:
        # 标记完成
        existing = storage._query_one(
            "SELECT id FROM completions WHERE assignment_id = ? AND user_id = ?",
            (homework_id, user_id),
            db='work'
        )
        if existing:
            return api_response(True, message='您已完成此作业')
        
        storage._enqueue_write(
            "INSERT INTO completions (assignment_id, user_id, completed_at) VALUES (?, ?, ?)",
            (homework_id, user_id, int(time.time())),
            db='work'
        )
        return api_response(True, message='作业已完成')


@api_bp.route('/homework/delete/<int:homework_id>', methods=['POST'])
@require_api_login
def api_homework_delete(homework_id):
    """
    删除作业
    
    响应:
        {
            "success": true,
            "message": "作业已删除",
            "code": 200
        }
    """
    user_id = session['user_id']
    role = session.get('role')
    
    # 检查作业是否存在
    assignment = storage._query_one(
        "SELECT * FROM assignments WHERE id = ?",
        (homework_id,),
        db='work'
    )
    
    if not assignment:
        return api_response(False, message='作业不存在', code=404), 404
    
    # 权限检查
    can_delete = False
    if role == 'admin':
        can_delete = True
    elif role == 'teacher':
        can_delete = assignment['created_by'] == user_id or assignment['class_id'] == session.get('class_id')
    else:
        can_delete = assignment['created_by'] == user_id
    
    if not can_delete:
        return api_response(False, message='无权删除此作业', code=403), 403
    
    storage._enqueue_write(
        "DELETE FROM assignments WHERE id = ?",
        (homework_id,),
        cache_keys=['assignments'],
        db='work'
    )
    
    return api_response(True, message='作业已删除')