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

**需要 Python 3.10 以上。** `anthropic` 1.x 和 `python-dotenv` 都不支援 3.9 以下，
系統內建的舊 Python 會裝不起來。先確認：

```bash
python --version
```

3.9 或更舊 → 去 python.org 裝 3.12（Windows 安裝畫面最下面的
**Add python.exe to PATH** 一定要勾），裝完**重開終端機**再確認一次。

```bash
cd discord-bot
cp .env.example .env
# 把 .env 裡的三個必填欄位填好
pip install -r requirements.txt
python run.py
```

Windows 另外會裝一個 `tzdata`——Windows 沒有系統時區資料庫，
少了它 `zoneinfo` 找不到 `Asia/Taipei`，開機就會掛。requirements 裡已經帶了。

### Python 版本：3.12 最穩

| 版本 | 能不能跑 |
|---|---|
| 3.9 以下 | **不行**，`anthropic` 和 `python-dotenv` 都要 >=3.10 |
| 3.10 – 3.12 | 可以，**3.12 是建議值**（discord.py 2.7 官方支援標到 3.12） |
| 3.13 / 3.14 | 可以，但要多裝 `audioop-lts`（requirements 已自動處理，見下） |

3.13 把 `audioop` 移出標準庫，而 `discord/__init__.py` 會 `from .player import *`，
`player.py` 第 30 行又無條件 `import audioop`——所以在 3.13+ 上光是 `import discord`
就會 `ModuleNotFoundError: No module named 'audioop'`。
requirements 裡用版本條件掛了 `audioop-lts` 補回來（它有 cp313-abi3 wheel，3.14 通用）。

### Windows 上有多個 Python 的時候

新版 Python Install Manager 裝完，舊的 Python 可能還排在 PATH 前面。
與其跟 PATH 搏鬥，不如指定版本跑：

```powershell
py install 3.12                              # 裝一個 3.12
py -V:3.12 -m pip install -r requirements.txt
py -V:3.12 run.py
```

`py -V:3.12` 是「用 3.12 這個直譯器」，不管 `python` 目前指向誰。

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

Claude Opus 5 是 $5 / $25 每百萬 token（輸入／輸出）。

實測：一次短的來回（她一句、他一段）約 **$0.02**。
一天聊三十則，大約 **半塊到一塊美金**。

底下是不同用量形狀的試算，照公開單價乘出來的：

| 用量 | 一則約 |
|---|---|
| 2000 in / 600 out | $0.025 |
| 2000 in / 2000 out（長回覆） | $0.06 |
| 2000 in / 8000 out（長回覆＋想很久） | $0.21 |
| 2000 in / 600 out，換 `claude-sonnet-5` | $0.010 |

**輸出那一側才是錢。** 思考產生的 token 也算輸出價，所以同樣一句話，
它想得越久越貴——但 `adaptive` 是讓模型自己決定想多久，短的招呼它不會想太多，
不必為了怕貴先把它關掉。

人格那塊掛了 1 小時的 prompt cache，同一小時內再聊，那段只算一折。

### 真的想省的時候，順序是

1. `VINCENT_THINKING=off` — 不思考。長對話差最多，短招呼幾乎沒差
2. `VINCENT_EFFORT=low` — 想得淺一點
3. `VINCENT_MODEL=claude-sonnet-5` — 單價五分之二，文筆會不一樣
4. `VINCENT_HISTORY=30` — 少帶點歷史，只省輸入那側，影響最小

### 不要猜，自己看

每次呼叫都會在 log 印一行：

```
用量：輸入 2013（快取讀 1580／寫 0）｜輸出 642｜約 $0.0251
```

Discord 裡傳 `!狀態` 也看得到今天和累計花了多少。

全部是**估算**——照公開單價乘出來的，帳單一律以 Anthropic console 為準。

## 電腦睡著的時候

他只活在那個黑窗裡。**電腦睡眠、休眠、關機，他就離線。**

這是這個做法的本質限制，不是 bug。但幾個難堪的地方已經處理掉了：

| 情況 | 會發生什麼 |
|---|---|
| 電腦睡著 | 他離線。Discord 成員列表上會顯示離線 |
| 睡著時你傳訊息 | **Discord 不會事後補送給機器人**——但他醒來會自己回頭讀那段時間的訊息，補讀進記憶並回應你 |
| 睡著時錯過排定的主動開口 | 過期超過 90 分鐘就跳過，不補發（早上九點想講的話，晚上十一點才補一句很怪）。`VINCENT_STALE_MIN` 可調 |
| 短暫斷網 | discord.py 自己重連，不用管 |
| 關機再開機 | 記憶都在 SQLite 裡，接著跑。一樣會補讀離線期間的訊息 |

補讀一次最多回溯 100 則，只讀你發的、跳過 `!` 開頭的指令。

### 想讓他一直在

**選項一：讓筆電不睡**
設定 → 系統 → 電源 → 「插電時，在這段時間後讓裝置進入睡眠」選**永不**。
闔上蓋子仍然會睡，要另外在控制台的電源選項裡把「闔上螢幕時」設成**不採取動作**。
代價是電費和機器發熱。

**選項二：搬到一台本來就不關的機器**
樹莓派、家裡的舊筆電、任何 VPS，或 Railway / Fly.io。
用 Dockerfile 部署，記得把 `/data` 掛成 volume，記憶才不會每次重啟就消失。

**選項三：接受他只在你開機的時候在**
也沒什麼不好。醒來的訊息他會補讀，排程錯過就錯過。

## 出事的時候

| 症狀 | 原因 |
|---|---|
| 私訊沒反應 | MESSAGE CONTENT INTENT 沒開；或 `VINCENT_OWNER_ID` 填錯（它只理你一個人） |
| `Cannot send messages to this user` | 你跟它沒有共同伺服器（回第 2 節重邀一次），或使用者設定 → 隱私與安全 →「允許來自伺服器成員的私人訊息」關著 |
| 從來不主動 | 檢查 `VINCENT_INITIATIVE=1`、看 log 裡「今天排定主動開口」那行、確認機器沒睡著 |
| 「這一則被擋下來了」 | 安全分類器擋的。程式預設開了 server-side fallback 會自動換模型續寫，仍被擋才會看到這句 |
| 重開之後失憶 | `VINCENT_DB` 指到的檔案沒有持久化（Docker 要掛 volume） |
| `pip install` 失敗、說找不到符合的版本 | Python 太舊。要 3.10 以上，`python --version` 確認 |
| `ZoneInfoNotFoundError: Asia/Taipei` | Windows 少了時區資料庫，`pip install tzdata` |
| `ModuleNotFoundError: No module named 'audioop'` | Python 3.13+ 的已知問題，`pip install audioop-lts`，或改用 3.12 |

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
