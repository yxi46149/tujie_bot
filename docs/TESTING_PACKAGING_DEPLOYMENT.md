# tujie_bot 测试、打包与发布指南

本指南按“本机自检 → Telegram 联调 → 打包 → 发布 → 部署 → 升级/回滚”的顺序执行。项目是长期运行的 Telegram 服务，不建议打成单个 EXE；推荐发布源码 ZIP，生产环境使用 Linux systemd 或 Docker。

> 适用版本：`tujie_bot v0.1.0`
>
> 最后更新：2026-07-17
>
> 数据库：SQLite（仅 SQLite）

## 当前技术栈与数据库说明

| 项目 | 当前实现 |
|---|---|
| 语言 | Python 3.11 |
| Telegram 框架 | aiogram 3.29.1 |
| 数据库 | SQLite |
| Python 数据库驱动 | aiosqlite |
| 默认数据库配置 | `DATABASE_PATH=data/bot.db` |
| 部署方式 | Windows、Linux systemd 或 Docker，均使用同一套 SQLite 实现 |

本项目没有使用 MySQL、PostgreSQL、MongoDB 或云数据库，也不需要单独启动数据库服务。`aiosqlite` 是异步读写 SQLite 的 Python 驱动，不是另一种数据库。

不同部署方式下，数据库位置如下：

| 部署方式 | SQLite 文件位置 | 持久化方式 |
|---|---|---|
| Windows 本机/服务 | `<项目目录>\data\bot.db` | 普通本地文件 |
| Linux systemd | `/opt/tujie_bot/data/bot.db` | 普通本地文件 |
| Docker | 容器内 `/app/data/bot.db` | Compose 的 `bot_data` volume |

Docker volume 只是保存 `/app/data/bot.db`，其中仍然是 SQLite 文件，并没有切换数据库类型。首次启动会自动创建表；已有旧库启动时会增量补齐当前版本缺少的表和索引，不会主动清空用户数据。

## 1. 发布前必须知道的事项

- 测试时使用单独的测试机器人 Token、测试频道和测试卡密，不要直接操作生产数据。
- `.env`、`data/bot.db`、卡密文件和备份文件不能提交 Git，也不能放入 Release ZIP。
- 一个 Token 同一时间只运行一个轮询实例，否则 Telegram 会返回 `Conflict`。
- SQLite 适合单实例部署。本项目的积分结算和卡密兑换使用事务防重，但不要同时启动两个机器人进程，也不要让多个服务器共享同一数据库文件。
- 机器人必须加入每个必选群/频道并设为管理员，否则无法可靠调用 `getChatMember`。

## 2. Windows 本机安装

推荐使用 Python 3.11；当前发布包的测试基线为 Python 3.11。PowerShell 中运行：

```powershell
cd C:\path\to\tujie_bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，至少正确填写：

```dotenv
BOT_TOKEN=测试机器人的Token
ADMIN_IDS=你的Telegram数字ID
REQUIRED_CHAT_IDS=@test_channel
REQUIRED_JOIN_URLS=https://t.me/test_channel
REQUIRED_CHAT_NAMES=测试频道
DATABASE_PATH=data/bot.db
```

若是私有频道，`REQUIRED_CHAT_IDS` 建议填写 `-100...` 数字 ID，加入按钮则使用有效邀请链接。多个频道的 ID、链接、名称必须按相同顺序用英文逗号分隔。

## 3. 三层测试

### 3.1 自动化测试

```powershell
python -m unittest discover -s tests -v
```

期望所有用例显示 `ok`，最后显示 `OK`。这些测试会使用临时数据库，不会修改 `data/bot.db`，覆盖：

- 邀请只绑定新用户、奖励只结算一次；
- 每日签到幂等；
- 邀请奖励每日上限；
- 卡密库存与积分原子扣减；
- 兑换确认不可盗用、过期不可使用、重复/并发点击不重复扣分；
- 私聊隔离与多频道菜单配置。

### 3.2 本地配置和数据库自检

```powershell
python -m scripts.check_config
```

这个命令不会连接 Telegram，也不会打印 Token。它会验证配置格式、初始化/升级数据库结构、执行 SQLite `quick_check`，并检查管理员和必选频道是否已配置。返回码为 0 才算通过。

如果这里使用的是生产数据库，建议先停止机器人并备份数据库，再首次运行新版本自检。

### 3.3 Telegram 联通性检查

```powershell
python -m scripts.check_bot
```

这个命令会连接 Telegram，检查 Token 是否有效、每个必选频道是否可访问、机器人是否是管理员；它不会发消息，也不会修改频道。

## 4. Telegram 手工验收清单

准备两个普通测试账号 A、B。清空测试库时必须先停止机器人，然后删除测试环境的 `data/bot.db`；不要对生产库这样做。

1. 启动：`python -m app.main`，日志出现“机器人已启动”。
2. A 私聊发送 `/start`，确认个人中心、频道按钮和全部菜单正常。
3. A 发送 `/invite`，复制专属链接给此前从未启动过该测试机器人的 B。
4. B 从邀请链接启动，但不加入频道，执行 `/verify`，应提示尚未加入且 A 不加分。
5. B 加入所有频道再验证，应通过；A 增加一次邀请奖励。
6. B 再次验证、反复点击验证按钮，A 的奖励不能重复增加；高频点击应触发冷却提示。
7. A 连续执行两次 `/checkin`，只允许第一次加分。
8. 管理员运行 `/addproduct 10 测试卡`，再用本地文件导入测试卡密：

   ```powershell
   python -m scripts.import_cards 1 .\test-codes.txt
   ```

9. 给 A 足够积分：`/addpoints A的数字ID 20`。在 `/shop` 中确认兑换并快速重复点击，只能扣一次积分、发一条库存卡密。
10. A 运行 `/mycards`，应能找回兑换记录；卡密消息应带 Telegram 内容保护。
11. 在群里发送 `/points`，机器人只提示转到私聊，不泄露积分或卡密。
12. 管理员检查 `/stats`、`/products`、上下架商品。用 `/addcards` 直接粘贴卡密时，确认原消息已删除；生产环境优先用本地导入脚本。
13. 停止进程后再次启动，确认积分、邀请、库存和卡密仍在。

验收完成后，不要把测试卡密或测试数据库复制到生产环境。

## 5. 生成 ZIP 发布包

项目版本保存在 `VERSION`。打包命令：

```powershell
.\scripts\package.ps1 -Version 0.1.0
```

产物位于 `dist\tujie_bot-v0.1.0.zip`，命令同时打印 SHA256。脚本只打包程序、测试、文档和部署模板，明确排除 `.env`、数据库、虚拟环境、Git 历史与缓存。

发布前检查 ZIP：

```powershell
Get-ChildItem .\dist
Get-FileHash .\dist\tujie_bot-v0.1.0.zip -Algorithm SHA256
```

把 ZIP 解压到一个全新目录，重新创建 `.env` 和虚拟环境，再运行以下命令，能排除“只在开发目录可运行”的问题：

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m scripts.check_config
```

## 6. 推送代码与创建私有 GitHub Release

先确认没有敏感文件：

```powershell
git status --short
git diff --check
git ls-files | Select-String -Pattern '(^|/)(\.env|data/|dist/)|\.db(-wal|-shm)?$'
git push origin main
```

本项目仓库是私有仓库。Release 也只对有仓库权限的账号可见。无需重新使用 CLI 登录：

1. 浏览器打开仓库的 **Releases** 页面，选择 **Draft a new release**。
2. 创建新标签，例如 `v0.1.0`，目标分支选择 `main`。
3. 标题填写 `tujie_bot v0.1.0`，说明中列出功能、配置变化、数据库变化和升级步骤。
4. 上传 `dist\tujie_bot-v0.1.0.zip`，并粘贴脚本输出的 SHA256。
5. 确认附件中没有 `.env`、数据库和真实卡密后发布。

不要把 `.env` 作为 GitHub Actions Secret 之外的仓库文件上传。仅仅把仓库设为私有，也不能代替 Token 和卡密隔离。

## 7. Windows 发布与常驻运行

1. 把 ZIP 解压到固定目录，例如 `C:\Services\tujie_bot`。
2. 创建 `.venv`、安装依赖、复制并填写 `.env`。
3. 依次运行自动化测试、`check_config`、`check_bot`。
4. 前台运行 `python -m app.main` 完成一次手工验收。
5. 用 Windows“任务计划程序”创建任务：
   - 触发器：系统启动时；
   - 程序：`C:\Services\tujie_bot\.venv\Scripts\python.exe`；
   - 参数：`-m app.main`；
   - 起始于：`C:\Services\tujie_bot`；
   - 失败时每 1 分钟重新启动，连续重试；
   - 使用专用低权限 Windows 账号运行。

更新前先在任务计划程序中停止任务，备份数据库，替换程序文件、更新依赖、自检后再启动。

## 8. Linux + systemd 部署

以下示例适用于 Debian/Ubuntu，部署目录为 `/opt/tujie_bot`：

```bash
sudo useradd --system --home /opt/tujie_bot --shell /usr/sbin/nologin tujie-bot
sudo mkdir -p /opt/tujie_bot
sudo chown tujie-bot:tujie-bot /opt/tujie_bot
```

把发布 ZIP 解压到该目录，然后：

```bash
cd /opt/tujie_bot
sudo -u tujie-bot python3 -m venv .venv
sudo -u tujie-bot .venv/bin/python -m pip install -r requirements.txt
sudo -u tujie-bot cp .env.example .env
sudo chmod 600 .env
sudo -u tujie-bot .venv/bin/python -m scripts.check_config
sudo -u tujie-bot .venv/bin/python -m scripts.check_bot
sudo cp deploy/tujie-bot.service /etc/systemd/system/tujie-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now tujie-bot
sudo systemctl status tujie-bot
sudo journalctl -u tujie-bot -f
```

复制 `.env.example` 后必须先填写真实配置。service 模板只允许写 `/opt/tujie_bot/data`；如修改 `DATABASE_PATH` 到其他目录，也要同步修改 `ReadWritePaths`。

## 9. Docker 部署

在项目目录创建 `.env` 后执行：

```bash
docker compose build
docker compose run --rm bot python -m scripts.check_config
docker compose run --rm bot python -m scripts.check_bot
docker compose up -d
docker compose logs -f bot
```

SQLite 数据文件位于容器内 `/app/data/bot.db`，并保存在名为 `bot_data` 的 Docker volume 中。这个 volume 保存的仍然是 SQLite 文件。不要同时执行两个 `docker compose up` 实例。更新：

```bash
docker compose down
docker compose build --pull
docker compose run --rm bot python -m scripts.check_config
docker compose up -d
```

## 10. 数据库备份、升级和回滚

以下全部操作针对 SQLite 文件。无需导出 SQL，也没有数据库账号密码。运行时出现 `bot.db-wal` 和 `bot.db-shm` 是 WAL 模式的正常现象；最简单可靠的备份方式是先停止机器人，让 WAL 正常合并，再复制 `bot.db`。

### 普通/Windows/systemd 部署

最稳妥的备份方式是先停止机器人，再复制 `data/bot.db`。停止后 WAL 会正常合并，避免漏掉 `bot.db-wal` 中尚未合并的数据。

Linux systemd 部署推荐使用一键升级脚本。先把新 ZIP 上传到服务器，例如 `/home/ubuntu/bot/tujie_bot-v0.1.1.zip`，然后：

```bash
cd /home/ubuntu/bot/tujie_bot
bash scripts/upgrade_server.sh /home/ubuntu/bot/tujie_bot-v0.1.1.zip
```

如果 ZIP 放在项目上级目录，且文件名为 `tujie_bot-v*.zip`，可以省略 ZIP 路径，脚本会自动选择最新包：

```bash
cd /home/ubuntu/bot/tujie_bot
bash scripts/upgrade_server.sh
```

脚本默认会停止 `tujie-bot` 服务、备份 `data/bot.db*` 到 `../backups`、同步新程序、保留 `.env`/`.venv`/`data`、安装依赖、执行 `check_config` 和 `check_bot`，最后启动服务并显示状态。常用参数：

```bash
bash scripts/upgrade_server.sh --skip-check-bot /home/ubuntu/bot/tujie_bot-v0.1.1.zip
bash scripts/upgrade_server.sh --run-tests /home/ubuntu/bot/tujie_bot-v0.1.1.zip
bash scripts/upgrade_server.sh --project-dir /opt/tujie_bot --service tujie-bot /tmp/tujie_bot-v0.1.1.zip
```

脚本会检查 systemd 的 `WorkingDirectory` 是否和项目目录一致；如果不一致，会拒绝继续，防止升级错目录。

手工升级步骤：

1. 停止机器人，确认没有其他实例。
2. 复制 `data/bot.db` 到带日期的安全备份目录，并限制访问权限。
3. 保存当前版本号或 Git commit。
4. 替换程序文件并运行 `python -m pip install -r requirements.txt`。
5. 运行自动化测试、`python -m scripts.check_config` 和 `python -m scripts.check_bot`。
6. 启动机器人，完成 `/start`、`/verify`、`/shop` 的冒烟测试。

程序启动时会使用 `CREATE TABLE IF NOT EXISTS` 自动补齐当前数据库对象。不要拿生产库测试未知旧版本；跨多个版本升级时应逐版阅读 Release 说明。

回滚时停止新版本，恢复旧程序和升级前的数据库备份，再启动旧版本。不要在新旧版本之间来回复用已经写入过的新数据库。

### Docker named volume 备份

先停止服务：

```bash
docker compose stop bot
docker compose run --rm -v "$PWD:/backup" bot sh -c 'cp /app/data/bot.db /backup/bot.db.backup'
docker compose start bot
```

备份文件含用户、积分、邀请和真实卡密，必须像密码一样保护。恢复前先停止服务，并先保留当前数据库副本。

## 11. 常见故障

| 现象 | 处理 |
|---|---|
| `TelegramConflictError` / `terminated by other getUpdates` | 同一 Token 有两个实例；停止旧进程、旧容器或旧服务器。 |
| `/verify` 总提示暂时无法检查 | 运行 `python -m scripts.check_bot`；检查 chat ID、机器人管理员身份和网络。 |
| 用户已加入但验证失败 | 私有频道使用正确的 `-100...` ID；确认测试的是同一账号，机器人仍是管理员。 |
| `database is locked` | 确认只有一个实例、数据库不是网络共享盘；检查磁盘与权限。 |
| 启动提示 Token 无效 | 检查 `.env` 空格/换行；若 Token 泄露，到 `@BotFather` 撤销并换新。 |
| Docker 重建后数据为空 | 确认仍使用同一个 Compose 项目和 `bot_data` volume，没有误删 volume。 |
| 卡密已扣积分但消息没看到 | 用户运行 `/mycards` 找回；查看服务日志中的发送失败记录。 |

## 12. 最终发布门禁

发布前逐项确认：

- 自动化测试全部通过；
- `check_config` 和 `check_bot` 返回码均为 0；
- 手工验收覆盖邀请防重、签到防重、兑换并发与 `/mycards`；
- ZIP 中没有 `.env`、数据库、日志、真实卡密；
- 生产 Token 未用于测试环境，机器人已是所有必选频道管理员；
- 数据库已备份并验证能恢复；
- 生产环境只有一个运行实例；
- 已记录版本号、Git commit、ZIP SHA256 和回滚版本。
