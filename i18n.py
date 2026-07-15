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
import json
import os
from functools import lru_cache

import config


SUPPORTED_LANGS = ['zh-CN', 'zh-TW', 'en-US']
DEFAULT_LANG = getattr(config, 'DEFAULT_LANG_CODE', 'zh-TW')
LANG_DIR = os.path.join(os.path.dirname(__file__), 'langs')

LANG_ALIASES = {
    'zh': 'zh-CN',
    'zh-cn': 'zh-CN',
    'zh-hans': 'zh-CN',
    'zh-sg': 'zh-CN',
    'zh-hk': 'zh-TW',
    'zh-mo': 'zh-TW',
    'zh-tw': 'zh-TW',
    'zh-hant': 'zh-TW',
    'en': 'en-US',
    'en-us': 'en-US',
    'en-gb': 'en-US',
}

LANG_FILE_MAP = {
    'zh-CN': 'zh_CN.json',
    'zh-TW': 'zh_TW.json',
    'en-US': 'en_US.json',
}


def normalize_lang_code(lang_code):
    if not lang_code:
        return DEFAULT_LANG

    normalized = str(lang_code).strip()
    if not normalized:
        return DEFAULT_LANG

    alias = LANG_ALIASES.get(normalized.lower())
    if alias:
        return alias

    if normalized in SUPPORTED_LANGS:
        return normalized

    return DEFAULT_LANG


def pick_browser_lang(accept_language):
    if not accept_language:
        return DEFAULT_LANG

    candidates = []
    for item in accept_language.split(','):
        part = item.strip()
        if not part:
            continue
        lang = part.split(';', 1)[0].strip()
        q = 1.0
        if ';q=' in part:
            try:
                q = float(part.split(';q=', 1)[1])
            except ValueError:
                q = 0.0
        candidates.append((q, normalize_lang_code(lang)))

    if not candidates:
        return DEFAULT_LANG

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _load_language_file(lang_code):
    safe_code = normalize_lang_code(lang_code)
    file_name = LANG_FILE_MAP.get(safe_code, f'{safe_code}.json')
    file_path = os.path.join(LANG_DIR, file_name)
    if not os.path.exists(file_path):
        raise RuntimeError(f'Missing language file: {file_path}')

    with open(file_path, 'r', encoding='utf-8') as file_handle:
        data = json.load(file_handle)

    if not isinstance(data, dict) or not data:
        raise RuntimeError(f'Language file is empty or invalid: {file_path}')

    return data


def _validate_language_files():
    baseline = _load_language_file(DEFAULT_LANG)
    baseline_keys = set(baseline.keys())

    for lang_code in SUPPORTED_LANGS:
        data = _load_language_file(lang_code)
        missing_keys = sorted(baseline_keys - set(data.keys()))
        if missing_keys:
            raise RuntimeError(
                f'Language file {lang_code} is missing keys: {", ".join(missing_keys[:20])}'
            )


_validate_language_files()


@lru_cache(maxsize=8)
def load_translations(lang_code):
    safe_code = normalize_lang_code(lang_code)
    return _load_language_file(safe_code)


def translate(lang_code, key, default=''):
    translations = load_translations(lang_code)
    return translations.get(key, '')


def resolve_lang(*, user_lang=None, session_lang=None, accept_language=None, logged_in=False):
    if logged_in and user_lang:
        return normalize_lang_code(user_lang)

    if logged_in and session_lang:
        return normalize_lang_code(session_lang)

    if logged_in:
        return DEFAULT_LANG

    if session_lang:
        return normalize_lang_code(session_lang)

    browser_lang = pick_browser_lang(accept_language)
    if browser_lang:
        return browser_lang

    return DEFAULT_LANG