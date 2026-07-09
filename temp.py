#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sqlite3

conn = sqlite3.connect('school.db')
cursor = conn.cursor()

# 查看当前数据
cursor.execute("SELECT id, standard_name, display_name FROM subjects")
rows = cursor.fetchall()
print("当前数据：")
for row in rows:
    print(f"  id={row[0]}, standard_name={row[1]}, display_name={row[2]}")

# 更新 display_name
updates = [
    ('chinese', '语文'),
    ('math', '数学'),
    ('english', '英语'),
    ('physics', '物理'),
    ('chemistry', '化学'),
    ('biology', '生物'),
    ('history', '历史'),
    ('geography', '地理'),
    ('politics', '政治'),
    ('art', '美术'),
    ('music', '音乐'),
    ('pe', '体育'),
    ('it', '信息技术'),
    ('science', '科学'),
    ('social', '社会'),
]

for standard, display in updates:
    cursor.execute(
        "UPDATE subjects SET display_name = ? WHERE standard_name = ?",
        (display, standard)
    )
    print(f"✅ 更新 {standard} → {display}")

conn.commit()

# 验证结果
cursor.execute("SELECT id, standard_name, display_name FROM subjects")
rows = cursor.fetchall()
print("\n更新后：")
for row in rows:
    print(f"  id={row[0]}, standard_name={row[1]}, display_name={row[2]}")

conn.close()
print("\n✅ 完成！")