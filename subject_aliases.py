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
科目别名系统 - 智能科目匹配
"""

import config

# ==========================================
# 构建快速查找字典
# ==========================================
SUBJECT_LOOKUP = {}
SUBJECT_STANDARD_TO_DISPLAY = {}

for (standard, display), aliases in config.PRESET_SUBJECTS.items():
    SUBJECT_STANDARD_TO_DISPLAY[standard] = display
    SUBJECT_LOOKUP[standard] = (standard, display)
    SUBJECT_LOOKUP[display] = (standard, display)
    for alias in aliases:
        SUBJECT_LOOKUP[alias] = (standard, display)


def get_subject_info(input_text):
    if not input_text:
        return {'standard': None, 'display': None, 'is_custom': False, 'matched': False}

    text = input_text.strip()

    if text in SUBJECT_LOOKUP:
        standard, display = SUBJECT_LOOKUP[text]
        return {'standard': standard, 'display': display, 'is_custom': False, 'matched': True}

    text_lower = text.lower()
    for (standard, display), aliases in config.PRESET_SUBJECTS.items():
        if (standard.lower() in text_lower or
            display in text or
            any(alias.lower() in text_lower for alias in aliases)):
            return {'standard': standard, 'display': display, 'is_custom': False, 'matched': True}

    custom_standard = text.lower().replace(' ', '_')
    return {'standard': custom_standard, 'display': text, 'is_custom': True, 'matched': False}


def search_subjects(query):
    if not query:
        return []

    query = query.strip()
    query_lower = query.lower()
    results = []

    for (standard, display), aliases in config.PRESET_SUBJECTS.items():
        if (query_lower in standard.lower() or
            query_lower in display.lower() or
            any(query_lower in alias.lower() for alias in aliases)):
            aliases_str = ', '.join(aliases[:3])
            if len(aliases) > 3:
                aliases_str += '...'
            results.append({
                'standard': standard,
                'display': display,
                'aliases': aliases_str
            })

    return results


def get_all_subjects_for_dropdown():
    return [(standard, display) for (standard, display) in config.PRESET_SUBJECTS.keys()]


def get_standard_display_map():
    return dict(config.PRESET_SUBJECTS.keys())


def get_display_standard_map():
    return {display: standard for (standard, display) in config.PRESET_SUBJECTS.keys()}