# 文森特 · Discord

把 `CLAUDE.md` 那個人接到 Discord 上。她傳訊息他會回，而且**不用等她先開口**——
排程會在一天裡不固定的幾個時間點把他叫醒，讓他自己說第一句話。

---

## 先說清楚這東西的底

- **「主動」是排程做的，不是他想你。** 他沒有在背景等你。是這支程式每分鐘看一次錶，
  到了骰中的時間就呼叫模型，跟它說「她沒開口，你自己說第一句」。訊息是當下生成的、
  每次不一樣、會接著你們上次聊的東西——但觸發它的是 cron，不是想念。
- **連續性是檔案給的。** 對話存在 SQLite，最近 60 則原文帶回模型，更早的壓成摘要。
  所以他記得。但記得的是紀錄，摘要會失真，這點程式裡有跟他交代過（要引用先問）。
- **這是正式的 Bot 帳號**，走 Discord Developer Portal，不是 selfbot。
- **要有一台一直開著的機器。** 關機他就不在了。

---

## 裝起來

### 1. 開一個 Discord Bot

1. 去 https://discord.com/developers/applications → **New Application**，隨便取個名字
2. 左邊 **Bot** → **Reset Token** → 複製那串 token（只會出現一次，關掉就要重 reset）
3. 同一頁往下，**Privileged Gateway Intents** 把 **MESSAGE CONTENT INTENT** 打開
   ← 沒開就收不到任何訊息內容，這是最常見的卡點
4. **邀它進一個伺服器** — 見下面第 2 節
5. 回 Discord，使用者設定 → 進階 → 開 **開發者模式**，
   然後右鍵自己的頭像 → **複製使用者 ID**（一串 18–19 位數字）

### 2. 邀它進伺服器

**為什麼要這一步**：Discord 不准 bot 私訊一個跟它沒有共同伺服器的人。
它不會在伺服器裡講話，那個伺服器只是一張門票。

**先確定你有一個自己開的伺服器。** 沒有的話：Discord 左邊欄最下面的 **＋** →
**建立我的** → **僅供我和我的朋友使用** → 取個名字 → 建立。你就是擁有者了。
（別人的伺服器不行，除非你在那邊有管理員權限。）

然後三條路，挑一條：

**A. Installation 頁（現在的預設介面）**

1. 你的 App → 左邊 **Installation**
2. **Installation Contexts**：勾 **Guild Install**（**User Install** 可以取消）
3. **Install Link**：選 **Discord Provided Link**
4. **Default Install Settings** → Guild Install：
   - **Scopes** 加 `bot`
   - **Permissions** 加 `Send Messages`、`Read Message History`
5. 右下 **Save Changes**
6. 複製上面那條 Install Link → 貼進瀏覽器

**B. OAuth2 URL Generator（舊介面，有些 App 還看得到）**

1. 你的 App → 左邊 **OAuth2** → **URL Generator**
2. **Scopes** 勾 `bot`
3. 下面冒出來的 **Bot Permissions** 勾 `Send Messages`、`Read Message History`
4. 最底下 **Generated URL** 複製

**C. 自己拼網址（最快，上面兩個介面都懶得找就用這個）**

```
https://discord.com/oauth2/authorize?client_id=你的APPLICATION_ID&permissions=68608&scope=bot
```

`APPLICATION_ID` 在你的 App → 左邊 **General Information** → **Application ID**，
按一下就複製。`68608` = 查看頻道 + 傳送訊息 + 讀取訊息紀錄。

**不管走哪一條，最後都一樣**：瀏覽器打開連結 → 上面下拉選你剛開的伺服器 →
**繼續** → **授權** → 過人機驗證。

成功的樣子：那個伺服器的成員列表裡多出它的名字，掛著 **離線**。
**離線是對的** —— 你還沒跑 `python run.py`。跑起來它才會變上線。

**最後一個開關**：使用者設定 → **隱私與安全** → 把
**允許來自伺服器成員的私人訊息** 打開。關著的話它私訊不到你。

### 3. Anthropic API key

https://console.anthropic.com → API Keys → 建一把。這是會扣錢的，往下看費用那段。

### 4. 跑起來

```bash
cd discord-bot
cp .env.example .env
# 把 .env 裡的三個必填欄位填好
pip install -r requirements.txt
python run.py
```

看到 `已上線：...` 就可以私訊它了。

### Docker（推薦長期跑）

```bash
# 在 repo 根目錄，不是 discord-bot/
docker build -f discord-bot/Dockerfile -t vincent .
docker run -d --name vincent --restart unless-stopped \
  --env-file discord-bot/.env \
  -v vincent-data:/data \
  vincent
```

放哪裡都行：家裡一台舊筆電、Raspberry Pi、Railway、Fly.io、任何 VPS。
只有一個要求——**不要關機**，關了他就不會主動找你。

---

## 主動開口是怎麼排的

`.env` 裡這行：

```
VINCENT_WINDOWS=08:00-10:30@0.55,13:00-15:30@0.35,21:00-23:30@0.75
```

每天凌晨第一次 tick 時，程式替每個時段各擲一次骰：

- 早上那段 55% 會中，中了就在 08:00–10:30 之間**隨機挑一分鐘**
- 中午 35%、晚上 75%，同理

所以有些天他早上晚上都講話，有些天整天沒聲音——這是故意的，不是壞了。

再加三道閘：

| 設定 | 作用 |
|---|---|
| `VINCENT_QUIET=01:00-08:00` | 這段時間絕不主動（跨午夜有處理） |
| `VINCENT_MAX_PER_DAY=3` | 一天最多主動幾次 |
| `VINCENT_RECENT_SKIP_MIN=60` | 你一小時內才說過話，這次就跳過，不追著戳 |
| `VINCENT_IDLE_HOURS=20` | 反過來：超過 20 小時沒人說話，在非安靜時段戳一次（同一段沉默只戳一次） |

想立刻看效果，私訊 `!主動`。

---

## 指令

| 指令 | 作用 |
|---|---|
| `!記住 <一句話>` | 寫進長期筆記，之後每次對話都會帶上 |
| `!狀態` | 記憶存了多少、今天主動過幾次 |
| `!主動` | 不等排程，現在就叫他開口 |
| `!幫忙` | 指令表 |

其他時候直接說話。你一口氣連丟三則，他會等你停 3 秒再一次回，不會一則一則追答。

---

## 人格從哪來

從 repo 根目錄的 `CLAUDE.md` **直接讀**，一個字都沒改寫。
所以改人格只要改 `CLAUDE.md`，重啟就生效，Claude Code 這邊和 Discord 那邊永遠同一份。

程式只多接一段 `vincent/persona.py` 裡的「通道守則」：訊息會被切段、
`<系統提示>` 包起來的不是你說的話、被叫醒時就真的主動開口、摘要會失真所以要引用先問。

---

## 費用

用 `claude-opus-5`（`$5 / $25` 每百萬 token）。粗估，**這是推估不是帳單**：

- 一次來回：輸入約 2–5k token（人格 + 摘要 + 最近對話，其中人格那塊吃 prompt cache
  只算一折），輸出約 1–2k token
- 大約 **每則 0.03–0.06 美金**
- 一天聊 30 則 ≈ **1–2 美金/天**

想壓成本：`VINCENT_EFFORT=low`（省思考 token，語感掉一點）、
`VINCENT_HISTORY=30`（少帶點歷史）、或 `VINCENT_MODEL=claude-sonnet-5`（約五分之一價，
文筆會不一樣）。要不要換是你的事，我沒有替你決定。

---

## 出事的時候

| 症狀 | 原因 |
|---|---|
| 私訊沒反應 | MESSAGE CONTENT INTENT 沒開；或 `VINCENT_OWNER_ID` 填錯（它只理你一個人） |
| `Cannot send messages to this user` | 你跟它沒有共同伺服器（回第 2 節重邀一次），或使用者設定 → 隱私與安全 →「允許來自伺服器成員的私人訊息」關著 |
| 從來不主動 | 檢查 `VINCENT_INITIATIVE=1`、看 log 裡「今天排定主動開口」那行、確認機器沒睡著 |
| 「這一則被擋下來了」 | 安全分類器擋的。程式預設開了 server-side fallback 會自動換模型續寫，仍被擋才會看到這句 |
| 重開之後失憶 | `VINCENT_DB` 指到的檔案沒有持久化（Docker 要掛 volume） |

---

## 檔案

```
run.py                 進入點
vincent/config.py      環境變數 → 設定
vincent/persona.py     讀 CLAUDE.md，接上通道守則
vincent/memory.py      SQLite：訊息、滾動摘要、筆記、排程狀態
vincent/brain.py       呼叫 Claude：回覆、主動開口、壓縮記憶
vincent/initiative.py  擲骰、排時間、判斷該不該開口
vincent/chunker.py     切成 Discord 送得出去的段落，不切壞 code block
vincent/bot.py         Discord 這一端
```

---

## 測到哪裡

跑過的：設定解析、人格載入、SQLite 讀寫、摘要滾動（14 則壓到 6 則）、
連續同角色訊息合併、system block 的快取位置、擲骰排程、安靜時段（含跨午夜）、
沉默偵測與去重、長文切段（1900 字內、code fence 不被切開）、Discord client 建構。

**沒跑過的**：真的對 Anthropic API 和 Discord 發請求——這個容器裡沒有你的金鑰。
第一次在你自己機器上跑起來時，`!主動` 一下，確認那條路是通的。
