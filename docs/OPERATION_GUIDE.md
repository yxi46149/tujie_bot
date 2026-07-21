# 图杰机器人本地调试与运营操作文档

本文按实际使用顺序整理：本地启动、`.env` 参数来源、商品卡密管理、个人抽奖、群抽奖和测试清理。

## 1. 本地启动

PowerShell：

```powershell
cd C:\Users\huanwen\IdeaProjects\tujie_bot
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m scripts.check_config
python -m scripts.check_bot
python -m app.main
```

如果没有 `.venv`：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

启动成功后，机器人会自动创建或升级 SQLite 数据库。默认数据库是 `data/bot.db`。

## 2. `.env` 参数从哪里来

先复制模板：

```powershell
Copy-Item .env.example .env
```

常用配置：

```dotenv
BOT_TOKEN=从 @BotFather 获取的机器人 Token
ADMIN_IDS=你的 Telegram 数字 ID，多个用英文逗号分隔
REQUIRED_CHAT_IDS=@your_channel,-1001234567890
REQUIRED_JOIN_URLS=https://t.me/your_channel,https://t.me/+privateInvite
REQUIRED_CHAT_NAMES=通知频道,用户交流群
INVITE_REWARD=5
INVITE_DAILY_REWARD_LIMIT=20
CHECKIN_REWARD=1
LOTTERY_COST=5
HUMAN_VERIFY_ENABLED=false
HUMAN_VERIFY_CHAT_IDS=
HUMAN_VERIFY_TIMEOUT_SECONDS=120
STOCK_NOTIFY_CHAT_IDS=-1001234567890
TIMEZONE=Asia/Shanghai
DATABASE_PATH=data/bot.db
```

参数来源：

| 参数 | 获取方式 |
|---|---|
| `BOT_TOKEN` | Telegram 里找 `@BotFather`，用 `/newbot` 创建机器人 |
| `ADMIN_IDS` | 你自己的 Telegram 数字 ID，可用 ID 查询机器人获取 |
| `REQUIRED_CHAT_IDS` | 公开频道/群可填 `@username`；私密频道/群通常是 `-100...` 数字 ID |
| `REQUIRED_JOIN_URLS` | 用户点击加入用的公开链接或私密邀请链接 |
| `REQUIRED_CHAT_NAMES` | 按钮展示名称，数量要和 `REQUIRED_CHAT_IDS` 一致 |
| `LOTTERY_COST` | 用户个人 `/lottery` 每抽一次消耗多少积分 |
| `STOCK_NOTIFY_CHAT_IDS` | 管理员新增卡密库存后发送群通知的目标群/频道；为空表示不通知 |
| `DATABASE_PATH` | 本地 SQLite 文件路径，测试环境可换成单独文件 |

`REQUIRED_CHAT_IDS`、`REQUIRED_JOIN_URLS`、`REQUIRED_CHAT_NAMES` 必须一一对应。例如有一个频道和一个群：

```dotenv
REQUIRED_CHAT_IDS=@my_channel,-1001234567890
REQUIRED_JOIN_URLS=https://t.me/my_channel,https://t.me/+abcdef
REQUIRED_CHAT_NAMES=通知频道,交流群
```

## 3. Telegram 权限准备

1. 把机器人加入需要检查关注的频道/群。
2. 在频道和群里把机器人设为管理员，否则 `getChatMember` 检查不稳定。
3. 群抽奖如果用“发送口令参与”，需要找 `@BotFather` 执行 `/setprivacy`，选择你的机器人后设为 `Disable`。
4. 新人进群验证需要给机器人“限制成员/移除成员”权限。
5. 新人验证会销毁验证消息，群抽奖会删除上一条参与反馈，建议在群里给机器人“删除消息”权限；启用新人验证时必须具备该权限。

注意：管理员命令只认 `.env` 的 `ADMIN_IDS`，不是谁在群里是群管理员谁就能操作。

群成员可以直接在群里发送 `/checkin` 完成每日签到；群聊回复会提示本次签到结果和当前总积分。

普通用户私聊快捷指令只显示个人可用命令；普通群成员的快捷指令菜单只显示 `/checkin` 和 `/pointrank`；群管理员会额外看到 `/grouplottery`、`/lotteries` 和 `/drawlottery`。实际执行仍以 `.env` 的 `ADMIN_IDS` 为准，不是群管理员就一定能操作。

`.env` 中 `ADMIN_IDS` 里的管理员在私聊机器人时，会额外看到 `/admin`、`/products`、`/addproduct`、`/addcards`、`/toggleproduct`、`/lotteryprizes`、`/addlotteryprize`、`/togglelotteryprize`、`/addpoints` 等快捷指令。点击 `/addproduct` 或 `/addcards` 后，如果没有带参数，机器人会回复对应用法。

用户可以在私聊中发送 `/language` 或 `/lang`，也可以点击主菜单里的“语言切换 / Language”按钮，在中文和 English 之间切换。语言偏好会随用户账号保存在数据库中；切换后个人中心、积分、签到、商城、个人抽奖、排行榜和群抽奖常用提示会按该用户偏好显示。

## 4. 新人进群人机验证

默认关闭。需要启用时，在 `.env` 里配置：

```dotenv
HUMAN_VERIFY_ENABLED=true
HUMAN_VERIFY_CHAT_IDS=-1001234567890
HUMAN_VERIFY_TIMEOUT_SECONDS=120
```

说明：

| 参数 | 含义 |
|---|---|
| `HUMAN_VERIFY_ENABLED` | 是否启用新人进群验证 |
| `HUMAN_VERIFY_CHAT_IDS` | 启用验证的群；为空表示所有群都启用 |
| `HUMAN_VERIFY_TIMEOUT_SECONDS` | 验证有效期，默认 120 秒 |

启用后，新人进群会先被禁言。机器人会在群里发送一条本人专属算术题验证消息；用户选择正确答案后自动解除发言限制。别人点击该用户的验证按钮不会通过。

如果 2 分钟内没有完成验证，机器人会自动删除验证消息，并把该用户移出群；移出后会立即解除封禁，用户后续仍可重新进群触发新验证。

## 5. 商品和卡密

目前没有独立 Web 管理后台，管理都通过机器人管理员命令完成。只有 `ADMIN_IDS` 里的用户能使用 `/admin` 和相关命令。

创建商品：

```text
/addproduct 10 测试卡密
```

查看商品：

```text
/products
```

上架/下架商品：

```text
/toggleproduct 1
```

导入卡密，推荐本地导入，卡密不会经过 Telegram：

```powershell
python -m scripts.import_cards 1 .\codes.txt
```

也可以在与机器人的 Telegram 管理员私聊里导入：

```text
/addcards 1
CODE-001
CODE-002
CODE-003
```

机器人会尽量删除原始卡密消息；如果误发到群里，机器人会尝试立即删除并提醒。重复卡密会自动忽略。

如果 `.env` 配置了 `STOCK_NOTIFY_CHAT_IDS`，管理员通过 Telegram `/addcards` 成功新增库存后，机器人会向指定群/频道发送库存通知：

```text
📦 管理员新增 codex接码CDK 商品库存 20 个。
```

库存通知只包含商品名和新增数量，不包含任何卡密内容。重复卡密或空行导致实际新增数量为 0 时，不发送群通知。本地 `python -m scripts.import_cards ...` 导入不经过 Telegram，不会自动发送群通知。

测试环境清空数据最简单的方法是停掉机器人后删除测试数据库：

```powershell
Remove-Item .\data\bot.db
```

如果是生产库，不建议直接清空。先备份 `data/bot.db`，再决定是否只下架商品或新建测试数据库。

## 6. 个人积分抽奖

用户私聊机器人发送：

```text
/lottery
```

每次抽奖消耗 `.env` 的 `LOTTERY_COST` 积分。

管理员配置奖池：

```text
/lotteryprizes
/addlotteryprize 60 none 谢谢参与
/addlotteryprize 30 points 1 小额积分
/addlotteryprize 10 product 1 测试卡密
/togglelotteryprize 1
```

奖品类型：

| 类型 | 含义 |
|---|---|
| `none` | 空奖，不发积分也不发卡密 |
| `points` | 发积分 |
| `product` | 从商品库存里发一条卡密 |

商品下架或库存为 0 时，对应卡密奖不会进入个人抽奖池。

## 7. 群抽奖

群抽奖只能由 `ADMIN_IDS` 里的管理员在群聊里发起。

### 7.1 定时开奖

语法：

```text
/grouplottery points <积分> <中奖人数> time <时长> <参与口令> <标题>
/grouplottery product <商品ID> <中奖人数> time <时长> <参与口令> <标题>
/grouplottery product <商品ID> <中奖人数> time <时长> cost <报名积分> <参与口令> <标题>
```

示例：

```text
/grouplottery points 20 3 time 10m 抽奖 群福利积分抽奖
/grouplottery product 1 5 time 10m cost 2 兔姐666 codex接码CDK
```

`10m` 后自动开奖。时长支持：

| 写法 | 含义 |
|---|---|
| `30s` / `30秒` | 30 秒 |
| `10m` / `10分钟` | 10 分钟 |
| `2h` / `2小时` | 2 小时 |
| `1d` / `1天` | 1 天 |
| `10` | 10 分钟 |

### 7.2 满人开奖

语法：

```text
/grouplottery points <积分> <中奖人数> count <参与人数> <参与口令> <标题>
/grouplottery product <商品ID> <中奖人数> count <参与人数> <参与口令> <标题>
/grouplottery product <商品ID> <中奖人数> count <参与人数> cost <报名积分> <参与口令> <标题>
```

示例：

```text
/grouplottery product 1 1 count 50 抽卡 群福利卡密抽奖
```

达到 50 人参与后自动开奖。

### 7.3 报名扣积分

需要“拿积分抽卡密”时，在群抽奖命令里加入 `cost <报名积分>`：

```text
/grouplottery product 1 5 time 10m cost 2 兔姐666 codex接码CDK
```

这条命令表示：抽商品 ID 为 `1` 的卡密，中奖名额 `5` 个，`10m` 后开奖，群友发送 `兔姐666` 参与，每个成功参与者扣 `2` 积分，抽奖标题是 `codex接码CDK`。

处理规则：

1. 积分在参与成功时立即扣除；
2. 积分不足的用户不会进入抽奖名单；
3. 同一个用户重复发送口令不会重复扣分；
4. 抽到卡密后，机器人私聊中奖用户发卡密，并写入 `/mycards`；
5. 定时或满人开奖失败并自动取消时，已扣的报名积分会退回。

### 7.4 多行写法

如果参与口令或标题比较长，推荐多行写：

```text
/grouplottery points 20 3 time 10m
我要抽奖
群福利积分抽奖
```

群成员发送完全一致的口令，例如 `我要抽奖`，即可参与。

参与成功后机器人会：

1. @ 当前参与用户；
2. 回复当前参与人数，例如 `2/50`；
3. 从第二条成功反馈开始，自动删除上一条反馈。

如果配置了 `REQUIRED_CHAT_IDS`，参与群抽奖时也会检查用户是否已经加入全部指定频道/群。

### 7.5 手动开奖

管理员可以对未开奖抽奖手动开奖：

```text
/lotteries
/drawlottery 1
```

`/lotteries` 会列出当前群所有未开奖抽奖，包括编号、标题、参与人数、开奖模式和口令。`/drawlottery 1` 中的 `1` 是抽奖编号。

### 7.6 兑奖方式

积分奖：开奖后直接给中奖用户加积分。

卡密奖：开奖后机器人私聊中奖用户发送卡密，不会把卡密发到群里。用户没收到私聊时，先私聊机器人，然后发送：

```text
/mycards
```

即可找回最近兑换或中奖的卡密。

## 8. 服务器一键升级

先在本机打包并把 ZIP 上传到服务器，例如 `/home/ubuntu/bot/tujie_bot-v0.1.1.zip`。

首次把升级脚本固定到项目上级目录，避免每次解压项目时覆盖脚本权限：

```bash
cd /home/ubuntu/bot
unzip -p tujie_bot-v0.1.1.zip tujie_bot/scripts/upgrade_server.sh > ./upgrade_server.sh
chmod +x ./upgrade_server.sh
```

以后升级时在 `/home/ubuntu/bot` 执行即可。脚本会自动识别项目目录 `/home/ubuntu/bot/tujie_bot`，并选择时间最新的 `tujie_bot-v*.zip`：

```bash
cd /home/ubuntu/bot
bash upgrade_server.sh
```

脚本会自动完成：停止 `tujie-bot` 服务、按 `.env` 的 `DATABASE_PATH` 备份真实 SQLite 文件、解压新包、覆盖程序文件、保留 `.env`/`.venv`/`data`/`logs`/`backups`、安装依赖、执行 `check_config` 和 `check_bot`、重新启动服务并显示状态。

为避免覆盖或误删生产数据，脚本会在正式同步前先预检查删除清单。只有 `app`、`deploy`、`docs`、`scripts`、`tests` 等程序目录中的旧文件允许自动删除；如果项目根目录里有生产卡密、临时资料或其他手工文件，脚本会中止并提示你先移动或备份。

每次升级成功后，项目里的新版 `scripts/upgrade_server.sh` 会自动复制回 `/home/ubuntu/bot/upgrade_server.sh` 并设置可执行权限。

常用参数：

```bash
bash upgrade_server.sh --skip-check-bot /home/ubuntu/bot/tujie_bot-v0.1.1.zip
bash upgrade_server.sh --run-tests /home/ubuntu/bot/tujie_bot-v0.1.1.zip
bash upgrade_server.sh --project-dir /opt/tujie_bot --service tujie-bot /tmp/tujie_bot-v0.1.1.zip
```

如果 systemd 里的 `WorkingDirectory` 和当前项目目录不一致，脚本会拒绝升级并提示修正，避免升级错目录。

## 9. 常用检查命令

```powershell
python -m scripts.check_config
python -m scripts.check_bot
python -m unittest discover -s tests -v
python -m compileall app scripts tests
```

`check_config` 检查 `.env` 格式，`check_bot` 会调用 Telegram API 验证 Token 和基础连接。

## 10. 常见问题

### 群里发口令没反应

检查三件事：

1. `@BotFather` 的 privacy mode 是否已经设为 Disable；
2. 机器人是否在这个群里；
3. 参与口令是否和抽奖公告中的口令完全一致。

### 用户参与时提示未加入频道

检查用户是否加入了 `.env` 中 `REQUIRED_CHAT_IDS` 配置的全部群/频道。机器人也必须在这些群/频道里，并有管理员权限。

### 卡密抽奖创建失败，提示库存不足

先确认商品已创建、已上架，并且未兑换卡密数量大于等于中奖人数：

```text
/products
```

### `/admin` 谁都能用吗

不能。只有 `.env` 的 `ADMIN_IDS` 包含的 Telegram 用户 ID 才能使用管理员命令。
