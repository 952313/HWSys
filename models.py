#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later

# Homework Management Platform - A homework management system for schools.
# Copyright © 2026 Yang Jincheng (Jason Yang Jincheng)

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
数据模型定义

包含系统中所有数据实体及其序列化方法
"""

import json
import time
from datetime import datetime

# ==========================================
# 用户角色常量
# ==========================================
ROLES = {
    'admin': '管理员',
    'technician': '技术员',
    'teacher': '老师',
    'rep': '课代表',
    'student': '同学'
}


# ==========================================
# 用户模型
# ==========================================
class User:
    """
    用户模型
    
    字段说明:
        id: 用户ID（自增）
        username: 学号/工号（唯一）
        password_hash: bcrypt 加密后的密码
        role: 角色（admin/technician/teacher/rep/student）
        name: 真实姓名
        class_id: 所属班级ID
        subjects: 负责科目列表（JSON，用于老师和课代表）
        first_login: 是否首次登录（强制修改密码）
        created_at: 注册时间戳
    """
    def __init__(self, id=None, username=None, password_hash=None, 
                 role='student', name=None, class_id=None, 
                 subjects=None, first_login=True, created_at=None):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.name = name
        self.class_id = class_id
        self.subjects = subjects or []
        self.first_login = first_login
        self.created_at = created_at or int(time.time())
    
    def to_dict(self):
        """转换为字典（用于数据库写入）"""
        return {
            'id': self.id,
            'username': self.username,
            'password_hash': self.password_hash,
            'role': self.role,
            'name': self.name,
            'class_id': self.class_id,
            'subjects': json.dumps(self.subjects),
            'first_login': 1 if self.first_login else 0,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建对象（用于数据库读取）"""
        return cls(
            id=data.get('id'),
            username=data.get('username'),
            password_hash=data.get('password_hash'),
            role=data.get('role', 'student'),
            name=data.get('name'),
            class_id=data.get('class_id'),
            subjects=json.loads(data.get('subjects', '[]')),
            first_login=bool(data.get('first_login', 1)),
            created_at=data.get('created_at')
        )


# ==========================================
# 班级模型
# ==========================================
class Class:
    """
    班级模型
    
    字段说明:
        id: 班级ID（自增）
        name: 班级名称（如"高一(1)班"）
        admin_id: 创建者（管理员ID）
        created_at: 创建时间戳
    """
    def __init__(self, id=None, name=None, admin_id=None, created_at=None):
        self.id = id
        self.name = name
        self.admin_id = admin_id
        self.created_at = created_at or int(time.time())
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'admin_id': self.admin_id,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id'),
            name=data.get('name'),
            admin_id=data.get('admin_id'),
            created_at=data.get('created_at')
        )


# ==========================================
# 科目模型
# ==========================================
class Subject:
    """
    科目模型
    
    字段说明:
        id: 科目ID（自增）
        name: 科目名称（如"数学"）
        created_at: 创建时间戳
    """
    def __init__(self, id=None, name=None, created_at=None):
        self.id = id
        self.name = name
        self.created_at = created_at or int(time.time())
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id'),
            name=data.get('name'),
            created_at=data.get('created_at')
        )


# ==========================================
# 作业模型
# ==========================================
class Assignment:
    """
    作业模型
    
    字段说明:
        id: 作业ID（自增）
        title: 作业标题
        description: 作业描述
        created_by: 创建者用户ID
        class_id: 所属班级ID
        subject_id: 所属科目ID
        is_public: 是否公共作业（1=所有人可见，0=仅自己和分享对象）
        shared_with: 已同意分享的用户ID列表（JSON）
        pending_invites: 等待同意的用户ID列表（JSON）
        created_at: 创建时间戳
        due_year/due_month/due_day: 截止日期（按天存储）
    """
    def __init__(self, id=None, title=None, description=None,
                 created_by=None, class_id=None, subject_id=None,
                 is_public=False, shared_with=None, pending_invites=None,
                 created_at=None, due_year=None, due_month=None, due_day=None):
        self.id = id
        self.title = title
        self.description = description
        self.created_by = created_by
        self.class_id = class_id
        self.subject_id = subject_id
        self.is_public = is_public
        self.shared_with = shared_with or []
        self.pending_invites = pending_invites or []
        self.created_at = created_at or int(time.time())
        self.due_year = due_year
        self.due_month = due_month
        self.due_day = due_day
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'created_by': self.created_by,
            'class_id': self.class_id,
            'subject_id': self.subject_id,
            'is_public': 1 if self.is_public else 0,
            'shared_with': json.dumps(self.shared_with),
            'pending_invites': json.dumps(self.pending_invites),
            'created_at': self.created_at,
            'due_year': self.due_year,
            'due_month': self.due_month,
            'due_day': self.due_day
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id'),
            title=data.get('title'),
            description=data.get('description'),
            created_by=data.get('created_by'),
            class_id=data.get('class_id'),
            subject_id=data.get('subject_id'),
            is_public=bool(data.get('is_public', 0)),
            shared_with=json.loads(data.get('shared_with', '[]')),
            pending_invites=json.loads(data.get('pending_invites', '[]')),
            created_at=data.get('created_at'),
            due_year=data.get('due_year'),
            due_month=data.get('due_month'),
            due_day=data.get('due_day')
        )


# ==========================================
# 完成记录模型
# ==========================================
class Completion:
    """
    完成记录模型
    
    字段说明:
        id: 记录ID（自增）
        assignment_id: 作业ID
        user_id: 完成该作业的用户ID
        completed_at: 完成时间戳
    """
    def __init__(self, id=None, assignment_id=None, user_id=None, 
                 completed_at=None):
        self.id = id
        self.assignment_id = assignment_id
        self.user_id = user_id
        self.completed_at = completed_at or int(time.time())
    
    def to_dict(self):
        return {
            'id': self.id,
            'assignment_id': self.assignment_id,
            'user_id': self.user_id,
            'completed_at': self.completed_at
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id'),
            assignment_id=data.get('assignment_id'),
            user_id=data.get('user_id'),
            completed_at=data.get('completed_at')
        )


# ==========================================
# 分享邀请模型
# ==========================================
class Invite:
    """
    分享邀请模型
    
    字段说明:
        id: 邀请ID（自增）
        assignment_id: 作业ID
        from_user: 邀请发起者用户ID
        to_user: 被邀请者用户ID
        status: 状态（pending/accepted/rejected）
        created_at: 创建时间戳
    """
    def __init__(self, id=None, assignment_id=None, from_user=None,
                 to_user=None, status='pending', created_at=None):
        self.id = id
        self.assignment_id = assignment_id
        self.from_user = from_user
        self.to_user = to_user
        self.status = status
        self.created_at = created_at or int(time.time())
    
    def to_dict(self):
        return {
            'id': self.id,
            'assignment_id': self.assignment_id,
            'from_user': self.from_user,
            'to_user': self.to_user,
            'status': self.status,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id'),
            assignment_id=data.get('assignment_id'),
            from_user=data.get('from_user'),
            to_user=data.get('to_user'),
            status=data.get('status', 'pending'),
            created_at=data.get('created_at')
        )


# ==========================================
# 教师指派模型
# ==========================================
class TeacherAssignment:
    """
    教师指派模型
    
    字段说明:
        id: 指派ID（自增）
        teacher_id: 老师用户ID
        class_id: 被指派的班级ID
        subject_id: 被指派的科目ID
        created_at: 创建时间戳
    """
    def __init__(self, id=None, teacher_id=None, class_id=None, 
                 subject_id=None, created_at=None):
        self.id = id
        self.teacher_id = teacher_id
        self.class_id = class_id
        self.subject_id = subject_id
        self.created_at = created_at or int(time.time())
    
    def to_dict(self):
        return {
            'id': self.id,
            'teacher_id': self.teacher_id,
            'class_id': self.class_id,
            'subject_id': self.subject_id,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id'),
            teacher_id=data.get('teacher_id'),
            class_id=data.get('class_id'),
            subject_id=data.get('subject_id'),
            created_at=data.get('created_at')
        )


# ==========================================
# 操作日志模型
# ==========================================
class OperationLog:
    """
    操作日志模型
    
    字段说明:
        id: 日志ID（自增）
        user_id: 操作用户ID（可为空）
        username: 操作用户学号（冗余）
        ip: 客户端IP
        action: 操作类型（login/view/create/complete等）
        path: 请求路径
        method: 请求方法（GET/POST）
        status_code: 响应状态码
        duration_ms: 响应耗时（毫秒）
        error_message: 错误信息（如果有）
        user_agent: 浏览器信息
        created_at: 创建时间戳
    """
    def __init__(self, id=None, user_id=None, username=None, ip=None,
                 action=None, path=None, method=None, status_code=None,
                 duration_ms=None, error_message=None, user_agent=None,
                 created_at=None):
        self.id = id
        self.user_id = user_id
        self.username = username
        self.ip = ip
        self.action = action
        self.path = path
        self.method = method
        self.status_code = status_code
        self.duration_ms = duration_ms
        self.error_message = error_message
        self.user_agent = user_agent
        self.created_at = created_at or int(time.time())
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'ip': self.ip,
            'action': self.action,
            'path': self.path,
            'method': self.method,
            'status_code': self.status_code,
            'duration_ms': self.duration_ms,
            'error_message': self.error_message,
            'user_agent': self.user_agent,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id'),
            user_id=data.get('user_id'),
            username=data.get('username'),
            ip=data.get('ip'),
            action=data.get('action'),
            path=data.get('path'),
            method=data.get('method'),
            status_code=data.get('status_code'),
            duration_ms=data.get('duration_ms'),
            error_message=data.get('error_message'),
            user_agent=data.get('user_agent'),
            created_at=data.get('created_at')
        )


# ==========================================
# 错误日志模型
# ==========================================
class ErrorLog:
    """
    错误日志模型
    
    字段说明:
        id: 日志ID（自增）
        error_type: 错误类型（Exception/ValueError等）
        error_message: 错误消息
        stack_trace: 堆栈跟踪
        path: 出错请求路径
        user_id: 出错时用户ID
        ip: 出错时客户端IP
        resolved: 是否已解决
        created_at: 创建时间戳
    """
    def __init__(self, id=None, error_type=None, error_message=None,
                 stack_trace=None, path=None, user_id=None, ip=None,
                 resolved=False, created_at=None):
        self.id = id
        self.error_type = error_type
        self.error_message = error_message
        self.stack_trace = stack_trace
        self.path = path
        self.user_id = user_id
        self.ip = ip
        self.resolved = resolved
        self.created_at = created_at or int(time.time())
    
    def to_dict(self):
        return {
            'id': self.id,
            'error_type': self.error_type,
            'error_message': self.error_message,
            'stack_trace': self.stack_trace,
            'path': self.path,
            'user_id': self.user_id,
            'ip': self.ip,
            'resolved': 1 if self.resolved else 0,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id'),
            error_type=data.get('error_type'),
            error_message=data.get('error_message'),
            stack_trace=data.get('stack_trace'),
            path=data.get('path'),
            user_id=data.get('user_id'),
            ip=data.get('ip'),
            resolved=bool(data.get('resolved', 0)),
            created_at=data.get('created_at')
        )