# Telegram 邀请积分与卡密兑换机器人

基于 Python、aiogram 3 和 SQLite，实现主要功能：

> 当前版本：`v0.1.0`（文档更新于 2026-07-19）。本项目只使用
> **SQLite**，默认数据库文件为 `data/bot.db`，不需要安装或配置
> MySQL、PostgreSQL、Redis 等外部数据服务。`aiosqlite` 只是 Python
> 异步访问 SQLite 的驱动。

- 个人中心与积分查询
- 指定群/频道成员验证
- 专属邀请链接、邀请记录与排行榜
- 验证后为邀请人结算积分（只结算一次）
- 按 `Asia/Shanghai` 日期每日签到（每天一次）
- 积分商城、卡密库存和原子兑换
- 积分抽奖、权重奖池、积分/卡密/空奖奖品
- 管理员群抽奖、口令参与、定时/满人开奖和私聊卡密兑奖
- 新人进群人机验证、验证通过后自动解除发言限制
- 一次性兑换确认、防重复扣分和 `/mycards` 卡密找回
- 管理员创建商品、批量导入卡密、上下架和调整积分
- 用户可在私聊中切换中文/English，语言偏好随账号保存
- 私聊隔离、验证冷却与邀请奖励每日上限

## 1. 准备 Telegram 机器人

1. 在 Telegram 中联系 `@BotFather`，使用 `/newbot` 创建机器人并取得 Token。
2. 把机器人加入需要验证的群或频道，并设为管理员。
3. 取得自己的 Telegram 数字 ID，以及群/频道的 `-100...` 数字 ID；公开频道也可以填写 `@username`。

> `getChatMember` 只有在机器人是群/频道管理员时才可靠。若配置多个 `REQUIRED_CHAT_IDS`，用户必须全部加入才算验证通过。
> 群抽奖使用“发送口令参与”时，需要在 `@BotFather` 里把机器人的 privacy mode 设为 Disable，否则机器人收不到群里的普通文本。
> 新人进群人机验证需要机器人在目标群里拥有“限制成员”权限；若要清理验证消息，还需要“删除消息”权限。

## 2. 安装与配置

PowerShell：

```powershell
cd C:\path\to\tujie_bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
BOT_TOKEN=你的机器人Token
ADMIN_IDS=你的Telegram数字ID
REQUIRED_CHAT_IDS=@your_channel
REQUIRED_JOIN_URLS=https://t.me/your_channel
REQUIRED_CHAT_NAMES=通知频道
INVITE_REWARD=5
INVITE_DAILY_REWARD_LIMIT=20
CHECKIN_REWARD=1
LOTTERY_COST=5
VERIFY_COOLDOWN_SECONDS=15
VERIFY_MAX_CONCURRENCY=5
REDEMPTION_INTENT_TTL_SECONDS=600
HUMAN_VERIFY_ENABLED=false
HUMAN_VERIFY_CHAT_IDS=
HUMAN_VERIFY_TIMEOUT_SECONDS=300
TIMEZONE=Asia/Shanghai
DATABASE_PATH=data/bot.db
```

多个必选频道的 ID、链接和名称必须一一对应，并用英文逗号分隔：

```dotenv
REQUIRED_CHAT_IDS=@channel_one,-1001234567890
REQUIRED_JOIN_URLS=https://t.me/channel_one,https://t.me/+privateInvite
REQUIRED_CHAT_NAMES=通知频道,用户交流群
```

启动：

```powershell
python -m app.main
```

首次启动会自动创建 SQLite 数据库和所有表。

## 3. 用户命令

| 命令 | 功能 |
|---|---|
| `/start` | 个人中心和主菜单 |
| `/points` | 当前积分与成功邀请人数 |
| `/verify` | 检查指定群/频道成员身份 |
| `/invite` | 生成 `?start=ref_用户ID` 专属链接 |
| `/myinvites` | 邀请记录与结算状态 |
| `/checkin` | 每日签到，私聊和群聊均可调用，并显示当前积分 |
| `/shop` | 积分商城 |
| `/lottery` | 积分抽奖 |
| `/mycards` | 找回最近兑换的卡密 |
| `/pointrank` | 积分排行榜，私聊和群聊均可调用，用户名脱敏显示 |
| `/rank` | 已验证邀请排行榜 |
| `/language` `/lang` | 切换中文/English |
| `/help` | 使用说明 |

普通群成员的快捷指令菜单只显示 `/checkin` 和 `/pointrank`；群管理员会额外看到 `/grouplottery`、`/lotteries` 和 `/drawlottery`。实际执行仍以 `.env` 的 `ADMIN_IDS` 为准。

语言切换在私聊中使用 `/language` 或主菜单的“语言切换 / Language”按钮；切换后个人中心、积分、签到、商城、个人抽奖、排行榜和群抽奖常用提示会按该用户偏好显示。

邀请必须满足以下条件才会奖励：

1. 被邀请人此前没有启动过机器人；
2. 被邀请人通过邀请人的专属链接首次启动；
3. 被邀请人加入全部指定群/频道并通过 `/verify`；
4. 同一被邀请人只能为一位邀请人结算一次。

默认每位邀请人每天最多获得 20 次邀请奖励，超过后邀请仍会记录，但不再加分。可通过 `INVITE_DAILY_REWARD_LIMIT` 调整，设置为 `0` 表示不限制。

## 4. 管理员命令

只有 `.env` 中 `ADMIN_IDS` 包含的用户可以使用：

```text
/admin
/stats
/products
/addproduct 10 测试卡密
/toggleproduct 1
/lotteryprizes
/addlotteryprize 60 none 谢谢参与
/addlotteryprize 30 points 1 小额积分
/addlotteryprize 10 product 1 测试卡密
/togglelotteryprize 1
/grouplottery points 20 3 time 10m 抽奖 群福利积分抽奖
/grouplottery product 1 1 count 50 抽卡 群福利卡密抽奖
/lotteries
/drawlottery 1
/addpoints 123456789 20
```

批量导入卡密时，每行一条：

```text
/addcards 1
CODE-001
CODE-002
CODE-003
```

重复卡密会自动忽略。兑换在 SQLite `BEGIN IMMEDIATE` 事务中完成，可防止并发重复发放同一条卡密。

Telegram 导入请只在与机器人的私聊中操作。导入成功后，机器人会尽力删除包含卡密的原消息；如果误发到群里，机器人会尝试立即删除并提醒。更推荐使用本地导入，卡密不会经过 Telegram：

```powershell
python -m scripts.import_cards 1 .\codes.txt
```

抽奖每次消耗 `LOTTERY_COST` 积分。奖池按权重随机，支持三种奖品：

```text
/addlotteryprize 60 none 谢谢参与
/addlotteryprize 30 points 1 小额积分
/addlotteryprize 10 product 1 测试卡密
```

`product` 类型会从已有商品库存中发放一条卡密；对应商品下架或库存为 0 时，该奖品不会进入用户抽奖池。抽中的卡密也会写入兑换记录，用户可通过 `/mycards` 找回。

群抽奖只能由 `ADMIN_IDS` 中的管理员在群聊中发起和开奖：

```text
/grouplottery points 20 3 time 10m 抽奖 群福利积分抽奖
/grouplottery product 1 1 count 50 抽卡 群福利卡密抽奖
/lotteries
/drawlottery 1
```

`time` 表示定时开奖，时长支持 `s/m/h/d` 或 `秒/分钟/小时/天`；纯数字按分钟处理。`count` 表示参与人数达到指定数量后自动开奖。群成员在本群发送完全一致的参与口令即可参加，机器人会回复当前参与人数，并在新的成功参与反馈发出后删除上一条反馈。若配置了 `REQUIRED_CHAT_IDS`，参与时也会检查是否已加入全部指定群/频道。积分奖开奖后直接到账；卡密奖不会发在群里，只会私聊中奖者，并写入 `/mycards` 方便找回。

管理员可在群里发送 `/lotteries` 查看当前群未开奖抽奖编号，再用 `/drawlottery <编号>` 提前开奖。

新人进群验证默认关闭。启用后，新入群用户会先被限制发言，机器人会发送一道简单算术题，用户选择正确答案后自动解除限制：

```dotenv
HUMAN_VERIFY_ENABLED=true
HUMAN_VERIFY_CHAT_IDS=-1001234567890
HUMAN_VERIFY_TIMEOUT_SECONDS=300
```

`HUMAN_VERIFY_CHAT_IDS` 为空时表示所有群都启用；也可以填写多个 `-100...` 或 `@username`，用英文逗号分隔。

更完整的本地启动、配置来源和业务操作流程见 [docs/OPERATION_GUIDE.md](docs/OPERATION_GUIDE.md)。

用户操作被限制在与机器人的私聊中。兑换确认使用一次性 token；重复点击只会返回原卡密，不会再次扣分。若卡密消息发送失败，用户可使用 `/mycards` 找回最近 10 条兑换记录。

## 5. 数据与备份

所有用户、积分、邀请关系、签到、商品、卡密和兑换记录都保存在同一个
SQLite 数据库中。普通 Windows/Linux 部署默认使用项目目录下的
`data/bot.db`；Docker 容器内使用 `/app/data/bot.db`，并由 `bot_data`
volume 持久化。Docker volume 不是另一种数据库，它保存的仍然是 SQLite 文件。

停止机器人后复制 `bot.db` 即可备份。运行过程中可能出现
`bot.db-wal` 和 `bot.db-shm`，这是 SQLite WAL 模式的正常文件；不要在机器人
运行时只复制 `bot.db`。本项目按单实例设计，不要让多个机器人进程或服务器
同时操作同一个 SQLite 文件。

不要提交 `.env`、Token 或生产数据库。若 Token 曾泄露，请立即到 `@BotFather` 使用 `/revoke` 重新生成。

## 6. 运行测试

```powershell
python -m unittest discover -s tests -v
python -m scripts.check_config
python -m scripts.check_bot
```

其中 `check_config` 只做本地配置、数据库初始化和完整性检查；`check_bot`
会实际连接 Telegram，验证 Token、频道访问权限和机器人管理员身份。

## 7. 打包与发布

生成不包含 `.env`、数据库和卡密的 ZIP 发布包：

```powershell
.\scripts\package.ps1 -Version 0.1.0
```

Linux systemd 服务器升级推荐把升级脚本固定放在项目上级目录，避免每次解压项目时覆盖脚本权限。首次安装外置升级脚本：

```bash
cd /home/ubuntu/bot
unzip -p tujie_bot-v0.1.2.zip tujie_bot/scripts/upgrade_server.sh > ./upgrade_server.sh
chmod +x ./upgrade_server.sh
```

以后上传新 ZIP 到 `/home/ubuntu/bot` 后，在 `/home/ubuntu/bot` 执行即可。脚本会自动识别项目目录 `/home/ubuntu/bot/tujie_bot`，并选择时间最新的 `tujie_bot-v*.zip`：

```bash
cd /home/ubuntu/bot
bash upgrade_server.sh
```

推荐服务器目录结构：

```text
/home/ubuntu/bot/upgrade_server.sh
/home/ubuntu/bot/tujie_bot
/home/ubuntu/bot/tujie_bot-v0.1.1.zip
/home/ubuntu/bot/tujie_bot-v0.1.2.zip
```

每次升级成功后，项目里的新版 `scripts/upgrade_server.sh` 会自动复制回 `/home/ubuntu/bot/upgrade_server.sh` 并设置可执行权限。需要指定发布包时也可以执行：

```bash
cd /home/ubuntu/bot
bash upgrade_server.sh /home/ubuntu/bot/tujie_bot-v0.1.2.zip
```

Docker 启动：

```powershell
docker compose up -d --build
docker compose logs -f bot
```

完整的本机联调清单、GitHub Release、Windows、Linux systemd、Docker 部署、
备份、升级与回滚步骤见 [测试、打包与发布指南](docs/TESTING_PACKAGING_DEPLOYMENT.md)。
