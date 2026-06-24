# Releasing MyAgentWiki

本文件用于记录 MyAgentWiki 仓库的正式发版流程，帮助后续稳定重复执行。

## 版本策略

- 日常开发和普通 `push` 默认不升级版本号
- 只有准备正式发布时，才统一更新 `pyproject.toml` 中的版本号并创建对应 Git tag / GitHub Release
- 向后兼容的 bugfix 使用 patch 版本，例如 `2.0.1`
- 向后兼容的新能力使用 minor 版本，例如 `2.1.0`
- 阶段性重构或不兼容变更使用 major 版本，例如 `3.0.0`

## 标准发版步骤

1. 确认当前工作树干净，或只包含本次发版需要纳入的变更
2. 更新 [`pyproject.toml`](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/pyproject.toml:7) 中的 `version`
3. 如有必要，同步更新 README、文档中的发布口径
4. 提交发版 commit
5. 基于发版 commit 创建带注释的 Git tag
6. 推送 `main` 和对应 tag
7. 在 GitHub Releases 页面基于该 tag 创建或发布 Release
8. 发布后回查 Release 页面，确认标题、说明、tag 和 commit 指向正确

## 推荐命令

```bash
git status --short
git add pyproject.toml README.md docs
git commit -m "release: cut 3.0.0"
git tag -a v3.0.0 -m "MyAgentWiki 3.0.0"
git push origin main
git push origin v3.0.0
```

如果是在 GitHub 网页端创建 Release，建议：

- Tag 使用 `vX.Y.Z`
- Release title 使用 `MyAgentWiki X.Y.Z`
- Release notes 简要说明本次亮点、兼容性和版本策略变化

## 发布后检查

- [Releases](https://github.com/sunweisheng/MyAgentWiki/releases) 页面出现新版本
- Release 指向的 commit 与本次发版 commit 一致
- 仓库根目录的版本号与 Release tag 一致
- 若发布说明里引用了新规则或新文档，确认链接可正常打开
