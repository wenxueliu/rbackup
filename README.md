# rbackup

跨系统的 rclone 加密备份工具：**A 本地明文 → rclone crypt 流式加密 → B 本地同步目录 → 网盘客户端 → 云端**。每台设备一个前缀；只 `copy` 不 `sync`；覆盖旧版时把旧文件移到 B 内的 `_versions`；B 的变化由 `watch` 轮询发现，但是否处理由用户决定。

```text
A（明文目录）──rclone crypt（流式加密）──▶ B（本地同步目录，密文）
                                              │
                                              ├─ 当前版本：<device>/<类别>/
                                              ├─ 旧版本：_versions/<device>/<日期>/<类别>/
                                              ├─ 状态：_state/<device>/last-run.json
                                              │
                                              └── 网盘同步客户端 ──▶ 云端

A：零密文、零索引、零镜像
B：密文 + 版本 + 状态（会随 B 同步上云，因此占用 B 所在磁盘）
```

> 下文 A = 本地明文源目录/设备，B = 本机另一个用于同步到网盘的目录。  
> 如果 B 不是本地目录，而是直接指向云端的 crypt remote，本工具同样支持，但版本和状态不会落在本地；本文按“B 是本地同步目录”说明。  
> **B 在本机时，B 目录必然有密文、版本和状态；这里的“零密文”指 A 目录，不是整台机器。** 如果要求整机不落密文，B 不能放在本机。

## 1. 它解决什么问题

- A 加密备份到 B 后，A 的本地文件可能被删除；B 和云端仍然保留。
- A 需要知道 B 发生了什么变化（包括网盘客户端从云端同步下来的变化），但不能被自动覆盖。
- 覆盖旧版时不能丢失旧内容，旧版本放在 B 的 `_versions`，随 B 同步上云。
- 多台设备共用一个 B/云端时，设备之间不能互相覆盖。

因此工具遵循四条硬规则：

1. **只 `copy`，绝不 `sync`**：A 删除文件不会导致 B 删除；B 多出的文件也不会被自动清理。
2. **一设备一前缀**：设备只写 `b_crypt:<device>/`，不同设备互不干扰。
3. **覆盖必留版本**：`rclone copy --backup-dir b_crypt:_versions/<device>/<version>/<类别>`，旧密文在 B 内移动，随后由同步客户端上传。
4. **B 漂移不静默覆盖**：`backup` 发现 B 相对 `_state` 基线变化时，默认退出码 3；必须检查后加 `--force` 才覆盖。

## 2. B 的目录布局

假设 rclone crypt remote `b_crypt` 的底层是 `D:/QuarkSync/rbackup`：

```text
D:/QuarkSync/rbackup/                 # B，本地同步目录
├── <device>/
│   ├── documents/                    # 当前版本（密文）
│   └── photos/
├── _versions/
│   └── <device>/
│       └── 20261030T235653Z-a1b2c3/
│           ├── documents/            # 被覆盖的旧文件
│           └── photos/
└── _state/
    └── <device>/
        └── last-run.json             # rclone rcat 写入的状态
```

说明：

- `<version>` 使用 UTC 时间 `YYYYMMDDTHHMMSSZ-<6位随机>`，同秒运行也不会冲突。
- 状态放在 `_state/<device>/` 而不是全局 `_state/last-run.json`，是为了遵守“一设备一前缀”，避免两台设备互相覆盖状态。
- `_state` 只记录设备、版本、每类文件数/字节数/摘要，不保存文件清单。
- **B 在本地，所以 `_versions` 和 `_state` 会占用 B 所在磁盘。** 这是“B 是本地同步目录”的必然结果；它们会随 B 同步到云端。A 本身仍然没有密文、索引或镜像。
- 如果严格要求版本“完全不落本地”，只能让 crypt remote 直接指向云端，而不是本地 B；那是另一种部署方式。
- B 里看到的都是密文名（目录名同样加密）；如何还原成明文、如何按明文路径删除，见 [6.7](#67-查看密文对应的明文以及删除-b-中的数据)。

## 3. 安装与准备

要求：

- Python **3.11+**（标准库 `tomllib`，无第三方 Python 依赖）。
- rclone **1.60+**，并已在 `PATH` 中，或在配置里写绝对路径。
- 一个本地目录 B，由网盘客户端同步到云端。
- 一个底层指向 B 的 rclone **crypt** remote。

```bash
python -m pip install -e .
# 或者不安装，直接在项目目录：
python -m rbackup --help
```

### 3.1 创建 B 和网盘同步

1. 创建 B 本地目录，例如 `D:/QuarkSync/rbackup`。
2. 在网盘客户端中把该目录设置为同步目录，确认 B → 云端的同步正常。
3. **B 不能放在 A 的类别目录里面，A 也不能放在 B 里面**。工具会检查并拒绝嵌套路径：
   - B 在 A 内：rclone 会把 B 的密文再次备份进自己，可能递归；
   - A 在 B 内：同步客户端会把 A 的明文也上传，破坏加密边界。

### 3.2 配置 rclone 的本地 crypt remote

注意：这里 crypt remote 的 `remote` 指向 **B 本地目录的绝对路径**，不是 Quark 云端路径。云端同步由网盘客户端负责。使用绝对路径，工具才能自动识别并校验 B。

```bash
rclone config
# n -> 名称 b_crypt -> 类型 crypt
# remote = D:/QuarkSync/rbackup
# filename_encryption = standard
# directory_name_encryption = true
# password / password2 自行设置并妥善保存
```

验证：

```bash
rclone lsd b_crypt:
```

> **非常重要**：crypt 的密码和 `rclone.conf` 丢失后，云端数据无法恢复。请把密码/`rclone.conf` 放到密码管理器或离线安全位置。`rclone.conf` 里的密码只是“混淆”，不是强加密；必要时启用 rclone 的配置加密。启用后请设置 `RCLONE_CONFIG_PASS` 环境变量，`rbackup` 会继承它。

## 4. 快速开始

推荐先用配置页面，再回到终端执行备份：

```bash
# 启动本地配置页（只监听 127.0.0.1，会打印带令牌的 URL）
rbackup web

# 或指定配置文件
rbackup web --config "配置路径" --port 8765
```

页面中填写设备名、crypt remote、A 类别，确认自动检测出的 B 路径，点“检查配置”，通过后“保存配置”。之后：

```bash
# 如果不用页面，也可以用 init 生成模板再编辑（Windows 默认 %APPDATA%\rbackup\config.toml）
# rbackup init --device my-laptop --remote b_crypt

# 1. 检查配置
rbackup --config "配置路径" doctor

# 2. 先看计划
rbackup --config "配置路径" backup --dry-run

# 3. 正式备份
rbackup --config "配置路径" backup

# 4. 监听 B 的变化（只报告，不自动处理）
rbackup --config "配置路径" watch --interval 5

# 5. 需要时把备份恢复回来（详见 6.6）
rbackup --config "配置路径" restore documents --dest ./restore-docs
```

`init` 只生成配置，不会创建 rclone remote，也不会向 B 或云端写数据。

除 `init`/`doctor` 外的命令会先读取 `rclone config show <remote>` 的 `type`；如果不是 `crypt`，直接拒绝执行，避免把明文误传到 B。因此 `remote` 要填**直接的 crypt remote**，不要填 alias。

如果 crypt remote 的底层是本机绝对路径，工具会自动识别 B，并在 `doctor` 中检查它存在、是目录、且与 A 不嵌套。

### 4.1 配置页面

```bash
rbackup web
# 指定端口 / 不自动打开浏览器
rbackup web --port 8765 --no-browser
```

启动后终端会打印类似：

```text
rbackup 配置页：http://127.0.0.1:50483/?token=......
配置文件：C:\Users\you\AppData\Roaming\rbackup\config.toml
```

页面功能：

- 编辑设备名、crypt remote、rclone 可执行文件/配置路径；
- 从 rclone 读取 remote 列表，检测 remote 类型和底层 B 本地路径；
- 动态增删数据类别、A 目录、排除规则、启用状态；
- 编辑轮询间隔、并发、限速、状态/版本前缀、保留版本数、符号链接等高级项；
- **检查配置**：验证 TOML、crypt 类型、B 存在、A/B 不嵌套、类别目录、状态文件；
- **保存配置**：先写临时文件并用正式加载器校验，再原子替换；旧配置自动备份为 `config.toml.bak`；
- 配置不存在时显示默认值，可直接新建；配置无效时回退默认值并显示错误，便于修复；
- **对比与操作**：A/B 逐项对比、勾选后上传或删除（B 或 A）、重设基线（见 [4.2](#42-对比与操作页)）。

安全设计：

- 只绑定 `127.0.0.1`，不对外网开放；
- 随机访问令牌，页面 URL 与 API 请求都校验；
- POST 校验 `Origin`，不启用 CORS；
- 不执行任意 shell；只通过现有配置校验器和 rclone 参数数组；
- 页面无外部 CDN/字体依赖，可离线使用。

> 页面保存会生成规范化 TOML，原有注释不会保留；旧文件在 `.bak` 中。保存后建议再运行 `doctor` 和 `backup --dry-run`。

### 4.2 对比与操作页

`rbackup web` 的第二个区块用来直接操作备份，不必记 CLI 参数。它用的是**页面当前填写的配置**，不需要先保存。

操作流程：选择类别 → 点「对比」→ 勾选行 → 点「上传到 B」「从 B 删除」或「从 A 删除」。

对比结果分「文件夹」和「文件」两组，逐项标注状态：

| 状态 | 含义 | 可做的操作 |
|---|---|---|
| 一致 | A 与 B 同名同大小同时间 | 无需处理，可删掉 A 的本地副本 |
| 大小/时间不同 | 两边都有但不一样 | 上传（用 A 覆盖 B）或删除 B 中的那份 |
| 只在 A | A 有、B 没有 | 上传 |
| 只在 B | B 有、A 没有 | 删除 B、从 A 删除后留下的历史副本、或保留 |
| 文件夹 只在 A / 只在 B | 目录层面的差异 | 上传整个目录 / 删除整个目录 |

三个动作的语义：

| 动作 | 作用对象 | 版本记录 | 对 `_state` 的影响 |
|---|---|---|---|
| 上传到 B | 写 B | 旧内容进 `_versions/<device>/<vid>/<类别>/...` | 基线过期，需重设 |
| 从 B 删除 | 删 B（含云端） | **不产生** | 基线过期，需重设 |
| 从 A 删除 | 删本机明文 | 不涉及 | **不影响**，基线仍有效 |

- **上传**走 `rclone copy`/`copyto --backup-dir`，布局与命令行 `backup` 一致；
- **从 A 删除**只删本机文件，B 里的备份原样保留；之后对比里这些项会变成「只在 B」，随时可以恢复。这是“清空本地、保留云端”的正规路径；
- **从 B 删除**会随网盘客户端同步到云端，删掉就没了（不进 `_versions`）；
- 上传和从 B 删除会让 `_state` 过期，接口返回 `state_stale`。消除漂移有两个办法：
  - 点「重设基线」：按 B 的当前内容重写 `_state`，不动任何数据；
  - 点「整类别备份到 B」：正常跑一次 `backup`，内容一致时不会重复上传。
- 「整类别备份到 B」默认会被漂移拦住（退出码 3）；需要覆盖时先勾选「覆盖远端漂移」，等价于 `backup --force`。

安全约束：

- 勾选「仅预演」后，上传/删除只打印计划，不写入（rclone `--dry-run`；从 A 删除则只是遍历后跳过实际删除）；
- 删除必须二次确认，两种删除的提示文案不同（一个警告会同步云端，一个强调只动本机、B 仍保留）；
- 路径只接受类别内的相对路径，`..`、绝对路径、盘符一律拒绝；从 A 删除时还会把解析后的真实路径再校验一次，防止符号链接指向 A 之外；
- 上传源必须是 A 中真实存在的文件或目录，删除目标必须存在于对应的 A/B，否则逐项报错但不会中断其余项；
- 默认「只看差异」，大目录下可用它隐藏一致项；超过 3000 行会截断并提示。

## 5. 配置说明

完整示例见 [`rbackup.example.toml`](rbackup.example.toml)。

```toml
device = "my-laptop"          # 必填；设备唯一前缀
remote = "b_crypt"            # 必填；底层指向 B 的 rclone crypt remote
rclone_bin = "rclone"         # 可选；绝对路径或 PATH 中的命令
rclone_config = ""            # 可选；rclone.conf 路径
poll_interval = 5             # watch 轮询秒数；B 在本地可设 2-5
transfers = 4
checkers = 8
retries = 3
# bwlimit = "8M:off"          # 可选；上传 8MiB/s，下载不限
state_prefix = "_state"
versions_prefix = "_versions"
follow_symlinks = false
create_empty_dirs = true
keep_versions = 30

[categories.documents]
path = "~/Documents"
excludes = ["**/.git/**", "**/node_modules/**"]
enabled = true
```

- 类别名会成为 B 内的目录名，允许中文和内部空格，但不能含 `/ \ : * ? " < > |`。
- `path` 支持 `~`、`$VAR`（Windows 也支持 `%VAR%`）；相对路径相对于配置文件所在目录。
- `excludes` 使用 rclone 过滤语法，作为 `--exclude=<pattern>` 传给 `copy`/`cryptcheck`/本地比较。
- `excludes` **不会删除** B 中已存在的旧文件；它只影响本次上传和校验范围。
- `poll_interval` 对本地 B 可以设小一些；每次轮询只是本地 rclone 列表，成本远低于云端 API 轮询。

配置文件查找顺序：

1. `--config PATH`
2. 环境变量 `RBACKUP_CONFIG`
3. 当前目录的 `rbackup.toml`
4. 系统配置目录：
   - Windows：`%APPDATA%\rbackup\config.toml`
   - macOS：`~/Library/Application Support/rbackup/config.toml`
   - Linux：`$XDG_CONFIG_HOME/rbackup/config.toml` 或 `~/.config/rbackup/config.toml`

## 6. 命令

| 命令 | 作用 | 是否写数据 |
|---|---|---|
| `init` | 生成配置模板 | 否 |
| `web` | 启动本地 Web 配置页面 | 否（保存时写配置文件） |
| `doctor` | 检查 rclone、remote、B、目录、状态 | 否 |
| `backup` | 本地类别 `copy` 到 B 的本设备前缀 | 是（写 B） |
| `watch` | 轮询 B 的变化并报告/交互处理 | B 变化时只报告；交互选 `u` 时写 B |
| `status` | 显示状态基线、检查 B 漂移 | 否 |
| `diff` | 比较 A 与 B 当前版本 | 否 |
| `verify` | `rclone cryptcheck` 校验 | 否 |
| `versions` | 列出 B 内历史版本 | 否 |
| `prune` | 删除 B 内旧历史版本 | 是（需 `--yes`） |
| `restore` | 从当前版/历史版恢复到本地 | 否（写本地目标） |

> `rbackup` 不提供通用删除命令：唯一会删数据的是 `prune`，且只动 `_versions/`。删除当前版本中的数据要用 rclone，见 [6.7](#67-查看密文对应的明文以及删除-b-中的数据)。

### 6.1 backup

```bash
rbackup backup                 # 所有启用类别
rbackup backup documents       # 只备份一个类别
rbackup backup --dry-run       # 只显示 rclone 计划
rbackup backup --verify        # 上传后用 cryptcheck 单向校验
rbackup backup --force         # B 漂移时仍用 A 覆盖（旧 B 内容进 _versions）
```

流程：

1. 读取 `_state/<device>/last-run.json`。
2. 递归列出 `<device>/` 当前树，按类别计算摘要。
3. 与状态里的摘要比较；有漂移则打印提示：
   - 终端交互：询问是否覆盖；
   - 非交互/`--json`：直接退出 3；
   - `--force`：跳过询问。
4. 对每个存在的 A 类别执行 `rclone copy`，`--backup-dir` 指向本次版本目录。
5. 重新列出 B，写入每类文件数、字节数、摘要。
6. 用 `rclone rcat` 写入状态。

**copy 的语义**：A 删除的文件不会从 B 删除；B 独有的文件会保留。这是备份工具，不是双向同步工具。

如果整个类别目录已经被永久删除、不再需要备份，请把该类别设为 `enabled = false` 或从配置中移除；否则 `backup` 会把它记为 `local_missing` 并返回 1，提醒你确认。

如果 B 已有数据但找不到 `_state` 基线（例如状态文件被删、换了配置），`backup` 也会拒绝覆盖，先提示你用 `diff` 检查；确认后才加 `--force`。

### 6.2 watch：B 变了，A 怎么知道

B 是本地目录，网盘客户端从云端拉取的变化最终也会落到 B。`watch` 每隔 `--interval` 秒递归列出本设备前缀，在内存中与上一份快照比较，输出：

- `baseline`：监听开始时的 B 概况；
- `drift`：启动时发现 B 与 `_state` 基线不同（没有本地索引，所以只报告类别级漂移，具体用 `diff` 查看）；
- `batch`：运行期间检测到新增/修改/删除；
- `error`：轮询失败（带连续失败次数）。

JSONL 示例：

```json
{"event":"baseline","files":12,"bytes":34567,"categories":{"documents":{"files":12,"bytes":34567}}}
{"event":"batch","added":1,"modified":0,"deleted":0,"changes":[{"kind":"added","category":"documents","path":"new.pdf","new_size":1024}]}
```

运行：

```bash
rbackup watch                       # 只报告
rbackup watch --interval 2          # B 本地，2 秒轮询
rbackup watch --json                # 给通知脚本/程序消费
rbackup watch --exit-on-change      # 第一批变化后退出，适合 CI/通知
rbackup watch --interactive         # 在终端询问 r/u/i/q
```

交互选择：

- `r`：把新增/修改的 B 文件恢复到 `--restore-dir`（默认 `./rbackup-restore`），**不覆盖已存在文件**；
- `u`：用 A 覆盖 B 同名文件（旧内容进 `_versions`）；
- `i`：忽略本次，继续监听；
- `q`：退出。

删除项无法从“当前版本”恢复；用 `versions` 找到历史版本后再 `restore --version`。

**实时性的边界**：这是轮询，不是文件系统事件推送。B 在本地时，2-5 秒已经很接近实时；间隔越短，CPU/磁盘扫描越多。若要真正的事件驱动，可在此基础上接 `watchdog`（本工具未内置）。网盘客户端自身同步到云端也有延迟，`watch` 感知的是 B 本地变化。

### 6.3 status / diff

```bash
rbackup status                 # 状态 + 实时 B 摘要，显示是否漂移
rbackup status --check         # 有漂移退出 3，适合监控脚本
rbackup status --offline       # 只读 _state，不列举当前 B 数据
rbackup diff                   # A vs B：B 独有/本地未备份/大小时间不同
rbackup diff --json
```

`diff` 的“B 独有”正是 A 删除后仍保留在 B/云端的文件，可直接选择 `restore`。

`status --offline` 仍会读取 B 内的 `_state` 文件，只是不递归列举当前数据；它不是“完全不访问磁盘”。

### 6.4 verify

```bash
rbackup verify
rbackup verify --one-way       # 只要求 A 的文件都能在 B 找到（A 已删除部分文件时用）
```

底层命令：

```bash
rclone cryptcheck <A 本地明文目录> b_crypt:<device>/<类别>
```

它把 A 的文件按 B 中 nonce 加密后比较 B 对象的校验和，**不需要把 B 文件完整读一遍再解密到本地**。B 底层是本地文件系统时支持 checksum，因此这个校验很直接。

`backup --verify` 使用 `--one-way`，因为它只验证“本次 A 文件都已正确上传”，不会把 A 已删除的 B 文件误判为错误。

### 6.5 versions / prune

```bash
rbackup versions
rbackup versions documents --json
rbackup prune --keep 30                 # 只显示计划，不删除
rbackup prune --keep 30 --yes           # 保留最新 30 个版本
rbackup prune --older-than 90 --yes     # 删除 90 天前的版本
rbackup prune --keep 30 --dry-run       # 明确 dry-run
```

`prune` 只动 `_versions/<device>/`，不碰当前数据。它会先列计划；没有 `--yes` 不会删除。删除后，网盘客户端会同步删除云端对应版本。

### 6.6 restore：把备份恢复回来

恢复的方向是 **B → 本地**，经由 rclone crypt 解密，与 `backup` 正好相反。三种场景：

| 要恢复什么 | 命令 |
|---|---|
| 单个文件（当前版） | `rbackup restore <类别> <相对路径> --dest <目标文件>` |
| 整个类别（当前版） | `rbackup restore <类别> --dest <目标目录>` |
| 某个历史版本 | `rbackup restore <类别> <相对路径> --version <版本号> --dest <目标文件>` |

```bash
# 先弄清远端有什么、和本地差在哪
rbackup status                 # 基线是否一致
rbackup versions               # 有哪些历史版本（从未覆盖过则为空）
rbackup diff                   # B 独有 / 本地未备份

# 当前版本的单文件
rbackup restore documents reports/2026/a.pdf --dest ./restore/a.pdf

# 历史版本
rbackup restore documents reports/2026/a.pdf \
  --version 20261030T235653Z-a1b2c3 --dest ./restore-old/a.pdf

# 整个类别
rbackup restore documents --dest ./restore-docs

# 只想看计划、不写盘
rbackup restore documents --dest ./restore-docs --dry-run
```

#### 推荐的恢复流程

不要一步直接覆盖 A，按“暂存 → 比对 → 归位”走：

1. `rbackup restore <类别> --dest ./restore-staging`，恢复到**空目录**（暂存区）；
2. 打开暂存区或用 `rbackup diff` 确认内容正确；
3. 确认后手动拷回 A，或直接 `--dest <A 内的目录> --force` 覆盖；
4. 回到 A 后跑一次 `rbackup backup --force`：内容一致时 rclone 会跳过上传，只把新的 B 基线写回 `_state`，漂移提示随之消失。

#### 恢复的语义与限制

- 单文件恢复：`--dest` 是目标文件；若给的是**已存在目录**，会自动拼上文件名。
- 整个类别恢复：`--dest` 是目标目录；**非空目录必须加 `--force`**，否则报错退出（退出码 2）。
- 已存在的目标文件默认拒绝覆盖；确认后加 `--force`。
- 恢复是 `copy`/`copyto`，**不会删除目标目录中多出的文件**，也不是跨文件事务；中断后已恢复的部分会保留，重跑即可补齐。
- `--dest` 绝不能指向 B（crypt 底层目录）：那会把明文写进密文区，破坏备份。
- 相对路径拒绝绝对路径、盘符和 `..`，防止写到目标目录之外。
- 恢复**不加锁**；若同时有 `backup` 在跑，可能读到传输中的中间状态。

#### 配置不在默认位置时

`restore` 与其他命令一样，按 `--config` → `RBACKUP_CONFIG` → `./rbackup.toml` → 系统配置目录的顺序查找配置。配置放在自定义位置时，每条命令都要带 `--config`，或设置一次环境变量：

```bash
rbackup --config "D:\backup\config.toml" restore documents --dest ./restore-docs
# 或
export RBACKUP_CONFIG="D:\backup\config.toml"     # PowerShell: $env:RBACKUP_CONFIG="D:\backup\config.toml"
```

#### B 和本地副本都没了

`restore` 只依赖 B。若 B 本机目录丢失，先让网盘客户端把云端数据**完整同步回 B**（确认 `_state`、`<device>`、`_versions` 都在），再执行上述恢复。

也可以绕过 rbackup，用 rclone 直接从云端 crypt remote 解密拷贝，但**必须**持有 crypt 的 `password`/`password2`：

```bash
# 设备名、类别换成实际值；--config 指向 rbackup 配置里 rclone_config 的那个文件
rclone --config rclone.conf copy "kuake:my-laptop/documents" ./restore-docs
```

密码丢失，云端数据即永久无法解密——这是整套方案唯一的单点故障。请把 `rclone.conf` 与密码单独离线备份（见 [3.2](#32-配置-rclone-的本地-crypt-remote)）。

### 6.7 查看密文对应的明文，以及删除 B 中的数据

B 里存的是密文，但**不需要、也不应该去解读密文名**：crypt remote 本身就是明文视图，rclone 读它时实时解密目录名、文件名、大小和时间，且不下载文件内容。

```bash
# 明文全树（最快）
rclone --config rclone.conf lsf b_crypt: -R

# 带大小/时间的明文元数据（JSON）
rclone --config rclone.conf lsjson b_crypt:my-laptop/documents

# 树状结构
rclone --config rclone.conf tree b_crypt:my-laptop

# 交互式浏览：可按大小排序，按 d 直接删除
rclone --config rclone.conf ncdu b_crypt:my-laptop
```

单个名字双向互查：

```bash
# 密文名 → 明文（可一次给多个）
rclone --config rclone.conf cryptdecode b_crypt: k9m2vq7t1s4p8n3r6b0c5d2e1f
#   → reports/2026/a.pdf

# 明文 → 磁盘上的真实密文路径（想在资源管理器里定位某个文件时用）
rclone --config rclone.conf cryptdecode --reverse b_crypt: "my-laptop/documents/reports/2026/a.pdf"
#   → <密文设备目录>/<密文类别目录>/<密文文件名>
```

注意事项：

- **目录名同样加密**，且每段独立加密：同一个文件名在不同类别下密文名不同。因此 `cryptdecode` 一次只处理一个名字段，不能直接喂完整路径。
- 文件名按 `filename_encryption = standard` 补齐，只泄露长度区间；没有 `password`/`password2` 无法还原。
- `_state`、`_versions` 也是密文目录，同样可以这样查看。
- 工具内的明文对比用 `status` / `diff`，不必手写 rclone 命令。

#### 删除数据

`rbackup` **不提供通用删除命令**，只有 `prune` 会删数据且只动 `_versions/`。删除当前版本要用 rclone，且**必须用明文路径**，不要对着 B 里的密文名操作：

| 需求 | 命令 |
|---|---|
| 删除单个文件 | `rclone deletefile b_crypt:<device>/<类别>/<路径>` |
| 删除目录内的文件（保留目录本身） | `rclone delete b_crypt:<device>/<类别>/<目录>` |
| 删除目录连同自身 | `rclone purge b_crypt:<device>/<类别>/<目录>` |

```bash
# 一律先预演：只打印，不删除
rclone --config rclone.conf deletefile --dry-run b_crypt:my-laptop/documents/reports/2026/a.pdf
rclone --config rclone.conf deletefile           b_crypt:my-laptop/documents/reports/2026/a.pdf
```

删除的是 B 中的密文对象。B 是网盘同步目录，这次删除会被客户端同步到云端——本地与云端一次生效，也意味着不可逆（网盘回收站不能依赖）。

**只删 B 不够。** `copy` 不传播删除，但下一次 `backup` 会用 A 的内容把文件补回去：

```text
只从 B 删除、A 仍保留该文件
  → status 报漂移
  → backup 退出码 3（拒绝写入）
  → backup --force 会把文件重新传回 B
```

正确顺序：

1. 从 A 删除源文件（或确认不再需要）；
2. 用 rclone 按明文路径从 B 删除；
3. `rbackup backup --force` 重新对齐基线，漂移提示随之消失（内容已一致，不会重复上传）。

#### 三条禁止

- **不要手删 `_state/<device>/last-run.json`**：基线丢失后，`backup` 会把 B 判为“有数据但无基线”并拒绝覆盖，需要重新 `--force` 建立信任。
- **不要手工 purge `_versions/`**：用 `rbackup prune --keep N --yes`，否则保留策略与实际目录会脱节。
- **不要凭密文名直接在 B 里删文件**：先用 `cryptdecode --reverse` 确认那一串 base32 到底是谁，否则可能删掉 `_state` 或其他类别的数据，并且绕过了 `--dry-run` 这层保险。

删除完成后，用 `rbackup status --check`（有漂移返回 3）或 `rbackup diff`（“远端独有”归零）确认结果。

## 7. 用户决策流程

当 B 发生变化（网盘客户端从云端拉取、另一台设备误写、手工修改等）：

```text
watch 报告 / status --check 发现漂移
        │
        ├─ diff 看清楚：B 新增了什么、改了什么、A 删除了什么
        │
        ├─ 想保留 B 的变化 → restore（可先到 staging 目录）
        │
        ├─ 想用 A 覆盖 B → backup --force（B 旧内容自动进 _versions）
        │
        └─ 暂时不处理 → 忽略；漂移会继续显示，不会被静默吞掉
```

没有任何路径会自动把 B 的修改合并进 A，也不会自动把 A 的修改覆盖 B。

如果你已经把 B 的版本 restore 到 A 并确认接受它，想清除“漂移”提示，可以再运行一次 `backup --force`：内容已经一致时 rclone 会跳过上传，只把新的 B 摘要写入 `_state`。

## 8. 状态文件示例

`b_crypt:_state/<device>/last-run.json`（实际文件在 B 内）：

```json
{
  "schema": 1,
  "device": "my-laptop",
  "remote": "b_crypt",
  "run_id": "20261030T235653Z-a1b2c3",
  "version_id": "20261030T235653Z-a1b2c3",
  "started_at": "2026-10-30T23:56:53Z",
  "finished_at": "2026-10-30T23:57:10Z",
  "status": "ok",
  "error": null,
  "hostname": "my-laptop",
  "rclone": "rclone v1.75.2",
  "categories": {
    "documents": {
      "status": "ok",
      "files": 12,
      "bytes": 34567,
      "digest": "d58ec6ab…",
      "version_id": "20261030T235653Z-a1b2c3",
      "updated_at": "2026-10-30T23:57:10Z",
      "verified": true
    }
  }
}
```

`digest` 是“类别内路径+大小+mtime”的 SHA-256，只用于判断 B 是否相对上次记录发生变化，不包含文件内容。

## 9. 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | rclone/传输/状态读写失败，或有本地类别缺失 |
| `2` | 配置/用法错误 |
| `3` | B 相对状态基线漂移，且未加 `--force`；或 `--check` 发现差异 |
| `4` | `cryptcheck` 未通过（上传可能已成功） |
| `130` | Ctrl+C 中断 |

## 10. 定时运行与同步

推荐顺序：

1. 网盘客户端持续把 B 同步到云端；
2. 定时运行 `rbackup backup`；
3. 需要感知 B 的变化时，运行 `watch`。

Linux/macOS cron：

```cron
15 3 * * * cd /opt/rbackup && /usr/bin/python3 -m rbackup --config /etc/rbackup.toml backup >> /var/log/rbackup.log 2>&1
```

Windows 计划任务（在“程序”里填 Python，参数填模块）：

```text
程序:   C:\Python312\python.exe
参数:   -m rbackup --config C:\Users\you\AppData\Roaming\rbackup\config.toml backup
起始于: C:\path\to\rbackup
```

如果要持续感知 B 的变化，把 `watch --exit-on-change --json` 放到一个由 systemd/计划任务拉起的循环里，或将输出接到通知程序。`watch` 本身不是系统服务。

注意：rbackup 只负责 A → B；B → 云端由网盘客户端负责。若 B 本地丢失，需要先让客户端把云端数据恢复到 B，再用 `rbackup restore`。

## 11. 安全与限制

**安全**

- crypt 密码丢失 = 数据不可恢复。请单独备份密码。
- `rclone.conf` 中的 crypt 密码是轻度混淆；建议启用 rclone 配置加密，或限制配置文件权限。
- `rbackup` 不把密码写入自己的配置/状态；它只调用 rclone。
- 状态文件只有设备名、类别计数和摘要，没有文件清单；但 B 内的目录结构/文件名是否可见取决于 crypt 的 `filename_encryption` 设置。
- B 是同步目录：确认网盘客户端同步的是 **B 的密文**，不要把 A 明文目录也放进同一个同步范围。
- 命令日志可能包含本地路径和 B 路径，注意日志权限。

**限制**

- `watch` 是轮询，不是文件系统事件；B 在本地时延迟可降到 2-5 秒。
- 漂移检测基于路径/大小/mtime。若 B 的内容被改但大小和 mtime 完全不变，轮询不会发现；需要 `verify` 做内容校验。
- `rclone copy` 也默认按大小+mtime 判断是否传输。若 A 的文件内容变了但大小和 mtime 都没变，备份可能跳过它；可在修改后 touch 文件，或把这类数据放到单独类别并用 `verify` 定期抽查。
- B 内的 `_versions`/`_state` 会占用本地磁盘，并依赖网盘客户端完整同步；部分客户端可能忽略隐藏文件/目录，需要确认。
- 网盘客户端在冲突时可能生成“冲突副本”。crypt 文件名被追加后缀后，rclone 可能无法解密；因此同一 `<device>` 前缀只应由一台设备写入，避免云端冲突副本。
- 覆盖/恢复不是跨文件事务；大量文件传输中断时，已传部分会保留。再次 `backup` 会继续补齐；状态可能因失败而保持旧基线，下次会提示漂移。
- `--backup-dir` 依赖底层 remote 支持 server-side move/copy；B 是本地文件系统时支持，但网络盘/同步盘的语义取决于挂载方式。
- 不合并冲突；同一文件在 A/B 都修改时，由用户选择 `restore` 或 `backup --force`。
- 不传播删除；不镜像空目录（除非 `create_empty_dirs` 且源目录存在）。
- 符号链接默认保存为 `.rclonelink`；`follow_symlinks = true` 会跟随链接，可能导致目录环/重复数据。
- 同一设备的 `backup`/`prune` 有本地临时锁，防止并发；`watch`/`restore` 不加锁，可能看到传输中的中间状态。

## 12. 开发与测试

```bash
python -m compileall -q rbackup tests
python -m unittest discover -s tests -p "test_*.py" -v
```

端到端测试需要 rclone；可用 `RBACKUP_RCLONE` 指定：

```bash
RBACKUP_RCLONE=/path/to/rclone python -m unittest discover -s tests -p "test_integration.py" -v
```

测试会在 `.test-tmp/` 下创建本地 `A` + 本地 crypt `B`，不需要 Quark 账号，也不会访问外网。
