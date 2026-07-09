#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
请求日志中间件
"""

import time
import traceback
from flask import request, g, session


class RequestLogger:
    def __init__(self, app, storage):
        self.app = app
        self.storage = storage
        self._setup_handlers()

    def _setup_handlers(self):
        app = self.app

        @app.before_request
        def before_request():
            g.start_time = time.time()

        @app.after_request
        def after_request(response):
            duration_ms = int((time.time() - g.start_time) * 1000)

            user_id = session.get('user_id')
            username = session.get('username')

            path = request.path
            method = request.method

            if path.startswith('/static'):
                return response

            action = self._get_action(path, method)

            self.storage.log_operation(
                user_id=user_id,
                username=username,
                ip=request.remote_addr,
                action=action,
                path=path,
                method=method,
                status_code=response.status_code,
                duration_ms=duration_ms,
                error_message=None,
                user_agent=request.headers.get('User-Agent', '')
            )

            return response

        @app.errorhandler(Exception)
        def handle_exception(e):
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()

            user_id = session.get('user_id')

            self.storage.log_error(
                error_type=error_type,
                error_message=error_message,
                stack_trace=stack_trace,
                path=request.path,
                user_id=user_id,
                ip=request.remote_addr
            )

            duration_ms = int((time.time() - g.start_time) * 1000)
            self.storage.log_operation(
                user_id=user_id,
                username=session.get('username'),
                ip=request.remote_addr,
                action='error',
                path=request.path,
                method=request.method,
                status_code=500,
                duration_ms=duration_ms,
                error_message=error_message[:200],
                user_agent=request.headers.get('User-Agent', '')
            )

            raise e

    def _get_action(self, path, method):
        if path == '/login' and method == 'POST':
            return 'login'
        if path == '/logout':
            return 'logout'
        if path == '/change_password':
            return 'change_password'
        if path.startswith('/assignment/complete/'):
            return 'complete_assignment'
        if path.startswith('/assignment/uncomplete/'):
            return 'uncomplete_assignment'
        if path.startswith('/assignment/delete/'):
            return 'delete_assignment'
        if path == '/monitor':
            return 'view_monitor'
        if path.startswith('/resolve_error/'):
            return 'resolve_error'
        if path.startswith('/admin'):
            return 'admin_action'
        if method == 'GET':
            return 'page_view'
        return 'unknown'