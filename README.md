# Telegram 邀请积分与卡密兑换机器人

基于 Python、aiogram 3 和 SQLite，实现截图中的主要功能：

- 个人中心与积分查询
- 指定群/频道成员验证
- 专属邀请链接、邀请记录与排行榜
- 验证后为邀请人结算积分（只结算一次）
- 按 `Asia/Shanghai` 日期每日签到（每天一次）
- 积分商城、卡密库存和原子兑换
- 管理员创建商品、批量导入卡密、上下架和调整积分

## 1. 准备 Telegram 机器人

1. 在 Telegram 中联系 `@BotFather`，使用 `/newbot` 创建机器人并取得 Token。
2. 把机器人加入需要验证的群或频道，并设为管理员。
3. 取得自己的 Telegram 数字 ID，以及群/频道的 `-100...` 数字 ID；公开频道也可以填写 `@username`。

> `getChatMember` 只有在机器人是群/频道管理员时才可靠。若配置多个 `REQUIRED_CHAT_IDS`，用户必须全部加入才算验证通过。

## 2. 安装与配置

PowerShell：

```powershell
cd C:\path\to\chaochao_bot
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
REQUIRED_JOIN_URL=https://t.me/your_channel
INVITE_REWARD=5
CHECKIN_REWARD=1
TIMEZONE=Asia/Shanghai
DATABASE_PATH=data/bot.db
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
| `/checkin` | 每日签到 |
| `/shop` | 卡密商城 |
| `/rank` | 已验证邀请排行榜 |
| `/help` | 使用说明 |

邀请必须满足以下条件才会奖励：

1. 被邀请人此前没有启动过机器人；
2. 被邀请人通过邀请人的专属链接首次启动；
3. 被邀请人加入全部指定群/频道并通过 `/verify`；
4. 同一被邀请人只能为一位邀请人结算一次。

## 4. 管理员命令

只有 `.env` 中 `ADMIN_IDS` 包含的用户可以使用：

```text
/admin
/stats
/products
/addproduct 10 测试卡密
/toggleproduct 1
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

## 5. 数据与备份

默认数据库在 `data/bot.db`。停止机器人后复制该文件即可备份；运行中备份建议同时处理 `bot.db-wal`，或使用 SQLite 在线备份命令。

不要提交 `.env`、Token 或生产数据库。若 Token 曾泄露，请立即到 `@BotFather` 使用 `/revoke` 重新生成。

## 6. 运行测试

```powershell
python -m unittest discover -s tests -v
```

