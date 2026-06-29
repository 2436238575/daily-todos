# DailyTodo - 每日模板化待办清单

一款基于 Python 与 Qt 的桌面待办软件。核心设计理念为“每日填充，永不删数据”。系统每天在指定时刻自动检查当日任务，若为空则从用户预设的母本中生成新清单，历史数据按月自动归档。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Qt](https://img.shields.io/badge/Qt-PySide6-green)](https://doc.qt.io/qtforpython/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 核心功能

- 模板化每日重置：用户可预设日常任务母本。系统在每日重置时刻（如凌晨 3:00）或开机启动时（若已过重置点）自动检查今日任务，若为空则批量生成。
- 数据永续留存：所有任务（包括已完成和未完成）均保留在主数据库中，绝不因跨天而物理删除，支持任意历史日期的回顾查询。
- 月度自动归档：每月首次启动时，自动将上月及更早的数据迁移至独立的归档数据库，保证主库轻量高效。
- 多主题适配：内置浅色与深色主题，支持跟随操作系统配色方案动态切换。
- 系统托盘驻留：关闭主窗口自动隐藏至系统托盘，后台持续运行以保障定时任务准时触发。
- 多语言界面：内置中英文界面翻译，支持运行时动态切换。
- 开机自启动：一键启用或关闭操作系统自启动功能。

## 技术栈

- 语言：Python 3.10+
- GUI框架：PySide6 (Qt for Python)
- 数据库：SQLite (内置 sqlite3 模块)
- 定时机制：QThread 后台轮询 + 启动时一次性补偿检查
- 样式管理：QSS 变量化配置，响应系统主题信号

## 项目结构

```text
DailyTodo/
├── main.py                         # 应用入口（单例检查、全局异常捕获、初始化）
├── requirements.txt                # 依赖清单（仅 PySide6）
├── README.md
├── .gitignore
│
├── core/                           # 业务核心层
│   ├── __init__.py
│   ├── database.py                 # SQLite 连接、表结构初始化、月度归档执行器
│   ├── task_manager.py             # 任务 CRUD、按日期查询、母本批量插入
│   └── scheduler.py                # 定时调度器（含启动补偿检查与每日轮询）
│
├── lib/                            # 工具与封装层
│   ├── __init__.py
│   ├── utils.py                    # 配置读写、系统托盘操作、开机自启设置
│   ├── widgets/                    # 自定义 Qt 控件
│   │   ├── __init__.py
│   │   └── task_list_widget.py
│   └── resources/                  # 编译后的资源文件
│       ├── __init__.py
│       └── resources_rc.py
│
├── ui/                             # 界面层
│   ├── __init__.py
│   ├── main_window.py              # 主窗口类（加载 .ui，绑定信号）
│   ├── dialogs/
│   │   ├── __init__.py
│   │   ├── task_edit_dialog.py
│   │   └── settings_dialog.py      # 设置对话框（含母本编辑器）
│   └── resources/
│       ├── main_window.ui
│       ├── dialogs/
│       │   ├── task_edit_dialog.ui
│       │   └── settings_dialog.ui
│       └── icons.qrc
│
├── config/                         # 用户配置（运行时生成）
│   ├── settings.json               # 含 reset_time, theme, language, daily_template
│   └── style.qss                   # 样式表
│
├── data/                           # 数据存储
│   ├── todo.db                     # 当前活跃数据库
│   └── archive/                    # 月度归档库 (todo_2026-06.db)
│
├── logs/                           # 日志
│   └── app.log
│
└── translations/                   # 多语言
    ├── zh_CN.qm
    ├── en_US.qm
    └── source/                     # .ts 源文件
```

## 配置说明

初次运行后，`config/settings.json` 自动生成，主要字段含义如下：

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `reset_time` | string | 每日重置时刻，格式 `"HH:MM"`，默认 `"03:00"` |
| `auto_start` | boolean | 是否开机自启 |
| `theme` | string | 可选 `"light"`, `"dark"`, `"system"`，默认 `"system"` |
| `language` | string | 可选 `"zh_CN"` 或 `"en_US"` |
| `daily_template` | array | 日常任务母本，每项包含 `content` 和 `sort_order` |

`daily_template` 示例：
```json
[
    { "content": "晨会复盘", "sort_order": 0 },
    { "content": "核心功能开发", "sort_order": 1 },
    { "content": "代码审查", "sort_order": 2 }
]
```

## 开发路线

- 基础 CRUD 与今日视图
- 定时调度与启动补偿填充
- 月度自动归档
- 系统托盘与开机自启
- 主题跟随与多语言切换
- 任务拖拽排序

## 许可证

MIT License