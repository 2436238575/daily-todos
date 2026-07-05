# DailyTodo - 每日模板化待办清单

一款基于 Python 与 Qt 的桌面待办软件。核心设计理念为“每日填充，永不删数据”。系统每天在指定时刻自动检查当日任务，若为空则从用户预设的母本中生成新清单，历史数据统一保存在单一主数据库中。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Qt](https://img.shields.io/badge/Qt-PySide6-green)](https://doc.qt.io/qtforpython/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 核心功能

- 模板化每日重置：用户可预设日常任务母本。系统在每日重置时刻（如凌晨 3:00）或开机启动时（若已过重置点）自动检查今日任务，若为空则批量生成。
- 数据永续留存：所有任务（包括已完成和未完成）均保留在单一主数据库中，绝不因跨天而物理删除，支持任意历史日期的回顾查询。
- 归档兼容导入：旧版本生成的月度归档库会在新版首次启动时自动合并回主数据库，原归档文件保留为备份。
- 多主题适配：内置浅色与深色主题，支持跟随操作系统配色方案动态切换。
- 系统托盘驻留：关闭主窗口自动隐藏至系统托盘，后台持续运行以保障定时任务准时触发。
- 多语言界面：内置中英文界面翻译，支持运行时动态切换。
- 开机自启动：一键启用或关闭操作系统自启动功能。
- 多端同步：可在设置页填写 DailyTodo Server 地址并登录账号，支持手动同步、启动/退出尝试同步、离线 dirty 数据重放和冲突中心手动选择版本。

## 技术栈

- 语言：Python 3.10+
- GUI 框架：PySide6 (Qt for Python)
- 数据库：SQLite（内置 `sqlite3` 模块）
- 同步协议：标准库 HTTP JSON 客户端，对接独立 `daily-todos-server` 后端
- 定时机制：`QThread` 后台轮询 + 启动时一次性补偿检查
- 样式管理：QSS 变量化配置，响应系统主题信号

## 项目结构

```text
DailyTodo/
├── main.py                         # 应用入口（单例检查、全局异常捕获、初始化）
├── requirements.txt                # 依赖清单
├── README.md
├── .gitignore
├── build_windows.bat               # Windows 构建脚本
├── build_linux.sh                  # Linux 构建脚本
│
├── core/                           # 业务核心层
│   ├── __init__.py
│   ├── database.py                 # SQLite 连接、表结构初始化、旧归档导入
│   ├── scheduler.py                # 定时调度器（含启动补偿检查与每日轮询）
│   ├── sync_client.py              # DailyTodo Server HTTP API 客户端
│   ├── sync_manager.py             # 同步流程、token 刷新、冲突状态管理
│   └── task_manager.py             # 任务 CRUD、按日期查询、母本批量插入
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
│   │   ├── conflict_dialog.py      # 同步冲突中心
│   │   ├── task_edit_dialog.py
│   │   └── settings_dialog.py      # 设置对话框（含同步入口与母本编辑器）
│   └── resources/
│       ├── main_window.ui
│       ├── dialogs/
│       │   ├── task_edit_dialog.ui
│       │   └── settings_dialog.ui
│       └── icons.qrc
│
├── config/                         # 用户配置（运行时生成）
│   ├── settings.json               # 含 reset_time, theme, language, sync, daily_template
│   └── style.qss                   # 样式表
│
├── data/                           # 数据存储
│   ├── todo.db                     # 单一主数据库
│   └── archive/                    # 旧版本归档备份（首次启动后导入主库）
│
├── logs/                           # 日志
│   └── app.log
│
├── tools/                          # 开发与打包辅助脚本
│   ├── build_translations.py
│   └── write_deploy_spec.py
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
| `sync` | object | 同步服务器、用户名、refresh token、last server version 等状态 |
| `daily_template` | array | 日常任务母本，每项包含 `uid`, `content`, `sort_order`, `base_version`, `deleted`, `sync_dirty` |

开发版为了便于联调，`sync.refresh_token` 暂时明文保存在 `settings.json`；正式发布前应切换为系统凭据管理器。

`daily_template` 示例：

```json
[
    { "content": "晨会复盘", "sort_order": 0 },
    { "content": "核心功能开发", "sort_order": 1 },
    { "content": "代码审查", "sort_order": 2 }
]
```

## 构建与打包


构建类型可选 `dev` 或 `release`，不传时默认 `dev`。

Windows/Linux 构建流程会自动：

- 创建并激活虚拟环境（如果不存在）
- 安装依赖
- 编译翻译文件
- 生成 `pyside6-deploy` 打包规范
- 构建并生成平台包

## 多端同步

桌面端已接入独立后端 `daily-todos-server`。在设置页“同步”区域填写服务器地址、用户名和密码后登录，可选择“立即同步”。首次同步会询问：

- 上传本机：先上传本地 dirty 数据，再拉取云端增量。
- 下载云端：先备份本地数据库，再用云端快照替换本地同步数据。
- 合并两边：上传本地 dirty 数据并拉取云端数据，冲突进入冲突中心。

普通同步顺序为 refresh token、push 本地变更、pull 增量。网络失败不会影响本地使用，任务和母本的 dirty 状态会保留到下次同步。启动和退出时会在已登录且完成首次同步后静默尝试一次普通同步。

当前冲突中心 v1 支持查看本地版和服务端版，并选择使用其中一版；暂不提供字段级合并编辑。

## 许可证

MIT License
