# Git 训练手册：从会 push/pull 到公司可用

目标：培养你在公司日常开发中稳定、安全、可协作地使用 Git 的能力。

---

## 1. 先理解 Git 的四个区域

你可以把 Git 理解成四个区域之间的流转：

```text
工作区 Working Tree
  ↓ git add
暂存区 Staging Area / Index
  ↓ git commit
本地仓库 Local Repository
  ↓ git push
远程仓库 Remote Repository / GitHub
```

对应关系：

| 操作 | 作用 | 你可以理解为 |
|---|---|---|
| `git add` | 把工作区的改动放入暂存区 | 选择本次准备提交哪些改动 |
| `git commit` | 把暂存区内容保存成本地版本 | 在本地创建一个版本快照 |
| `git push` | 把本地提交上传到远程仓库 | 把你的版本同步给 GitHub 或团队 |
| `git pull` | 拉取远程更新并合并到本地 | 获取别人或远程的新版本 |

一句话：

> add 是选菜，commit 是下单，push 是把订单发给远程仓库。

---

## 2. git add、git commit、git push 的区别

### 2.1 git add

`git add` 不会产生版本记录，也不会上传到 GitHub。

它只是告诉 Git：

> 这些改动我要放进下一次提交里。

常用命令：

```bash
git add .
git add README.md
git add app/tool_registry.py
```

说明：

- `git add .`：添加当前目录下所有变更。
- `git add 文件名`：只添加指定文件。
- 工作中更推荐先用 `git status` 看清楚，再决定 add 哪些文件。

---

### 2.2 git commit

`git commit` 会在本地仓库生成一个版本快照。

它不会自动上传 GitHub。

常用命令：

```bash
git commit -m "feat: add downtime analysis tool"
```

一次 commit 应该表达一个清晰目的，比如：

- 新增一个功能
- 修复一个 bug
- 调整一段文档
- 重构一块代码

不建议一个 commit 同时包含很多不相关的改动。

---

### 2.3 git push

`git push` 会把本地 commit 上传到远程仓库。

常用命令：

```bash
git push
```

第一次推送新分支时常用：

```bash
git push -u origin main
```

其中：

- `origin`：远程仓库的默认名字。
- `main`：本地分支名。
- `-u`：建立本地分支和远程分支的跟踪关系，以后直接 `git push` 即可。

---

## 3. 公司日常开发最常用工作流

### 3.1 每天开始写代码前

```bash
git status
git pull
```

目的：

- 确认本地有没有未提交改动。
- 获取远程最新代码，减少冲突。

---

### 3.2 开发一个新需求

推荐不要直接在 main 上开发，而是创建功能分支：

```bash
git checkout -b feat/downtime-summary
```

或者新版本命令：

```bash
git switch -c feat/downtime-summary
```

分支命名习惯：

| 类型 | 示例 | 用途 |
|---|---|---|
| feat | `feat/login-page` | 新功能 |
| fix | `fix/login-error` | 修复问题 |
| docs | `docs/update-readme` | 文档 |
| refactor | `refactor/tool-registry` | 重构 |
| chore | `chore/update-deps` | 杂项维护 |

---

### 3.3 写完一小段后自查

```bash
git status
git diff
```

如果已经 add 过，查看暂存区差异：

```bash
git diff --cached
```

你需要养成习惯：

> commit 前必须看 diff。

这能避免把调试代码、临时文件、敏感信息提交上去。

---

### 3.4 提交代码

```bash
git add .
git commit -m "feat: add downtime summary report"
```

建议提交信息格式：

```text
类型: 简短说明
```

常见类型：

| 类型 | 含义 |
|---|---|
| feat | 新功能 |
| fix | 修 bug |
| docs | 文档变更 |
| style | 格式调整，不影响逻辑 |
| refactor | 重构，不新增功能也不修 bug |
| test | 测试相关 |
| chore | 构建、依赖、配置等杂项 |

---

### 3.5 推送分支

```bash
git push -u origin feat/downtime-summary
```

然后在 GitHub 上创建 Pull Request，也就是 PR。

公司里通常不是直接 push main，而是：

```text
创建分支 → 开发 → commit → push → PR → Code Review → 合并到 main
```

---

## 4. 你必须熟练掌握的 15 个命令

### 基础状态

```bash
git status
git log --oneline
git branch
git remote -v
```

### 提交流程

```bash
git add .
git commit -m "message"
git push
git pull
```

### 分支操作

```bash
git checkout -b branch-name
git checkout branch-name
git switch -c branch-name
git switch branch-name
```

### 查看差异

```bash
git diff
git diff --cached
```

### 撤销操作

```bash
git restore file-name
git restore --staged file-name
git reset --soft HEAD~1
```

---

## 5. 撤销操作怎么理解

### 5.1 改了文件但还没 add，想撤销

```bash
git restore app/tool_registry.py
```

效果：丢弃工作区中该文件的修改。

注意：这个操作会丢失未保存到 Git 的修改。

---

### 5.2 已经 add 了，但不想放进这次提交

```bash
git restore --staged app/tool_registry.py
```

效果：从暂存区移除，但文件内容仍保留在工作区。

---

### 5.3 已经 commit 了，但还没 push，想撤回 commit

```bash
git reset --soft HEAD~1
```

效果：撤销最近一次 commit，但保留文件改动，并且通常保留在暂存区。

---

## 6. 冲突是什么

冲突通常发生在：

- 你改了某一行。
- 别人也改了同一行。
- Git 不知道该保留谁的版本。

冲突文件里会出现类似内容：

```text
<<<<<<< HEAD
你的版本
=======
别人的版本
>>>>>>> branch-name
```

解决步骤：

1. 打开冲突文件。
2. 手动决定保留哪些内容。
3. 删除冲突标记。
4. 执行：

```bash
git add 冲突文件
git commit
```

如果是 pull 过程中产生冲突，解决后继续提交即可。

---

## 7. 你的训练路线

### 第 1 阶段：会看状态

目标：任何时候都知道当前仓库发生了什么。

每天练习：

```bash
git status
git log --oneline --graph --decorate --all
git branch -vv
```

你要能回答：

- 当前在哪个分支？
- 有哪些文件被修改了？
- 哪些文件已经暂存？
- 本地是否领先远程？
- 本地是否落后远程？

---

### 第 2 阶段：会做小而清晰的提交

目标：一个 commit 只解决一个问题。

练习方式：

1. 改一处 README。
2. `git status`
3. `git diff`
4. `git add README.md`
5. `git diff --cached`
6. `git commit -m "docs: update project description"`
7. `git push`

---

### 第 3 阶段：会用分支开发

目标：不直接污染 main。

练习方式：

```bash
git switch -c docs/git-practice
```

然后修改文档、提交、推送：

```bash
git add .
git commit -m "docs: add git practice notes"
git push -u origin docs/git-practice
```

再到 GitHub 创建 PR。

---

### 第 4 阶段：会处理常见错误

你要练熟：

- add 错文件怎么撤回。
- commit 写错信息怎么修改。
- commit 后发现漏文件怎么补。
- 本地分支和远程分支不同步怎么办。
- pull 产生冲突怎么办。

---

## 8. 建议你从今天开始养成的习惯

1. 写代码前先 `git status`。
2. 开始任务前先 `git pull`。
3. 每个任务单独建分支。
4. commit 前必须 `git diff`。
5. commit 信息要能说明为什么改。
6. 不把临时文件、密钥、缓存、虚拟环境提交到仓库。
7. push 前确保代码能运行。
8. 遇到冲突不要慌，先看冲突文件，再手动整理。

---

## 9. 最常用心智模型

Git 不是只有 push 和 pull。

你应该把它理解成：

```text
我现在改了什么？          git status / git diff
我要把哪些改动组成一次版本？ git add
我要给这个版本起什么说明？   git commit
我要不要同步给别人？        git push
我要不要获取别人的更新？     git pull
我要不要隔离当前任务？       git branch / git switch
```

掌握这个模型后，你就能从“会用 Git 命令”升级成“会管理代码历史”。

---

## 10. 你的下一步实战任务

建议你用当前项目做一个安全练习：

1. 新建分支：`docs/git-practice`
2. 修改 README.md，加一行项目说明。
3. 查看状态和差异。
4. 只提交 README.md。
5. 推送这个分支。
6. 在 GitHub 上创建 PR。

推荐命令：

```bash
git switch -c docs/git-practice
git status
git diff
git add README.md
git diff --cached
git commit -m "docs: update project description"
git push -u origin docs/git-practice
```

完成这个练习后，你就真正走过了一遍公司开发中的基础分支流程。
