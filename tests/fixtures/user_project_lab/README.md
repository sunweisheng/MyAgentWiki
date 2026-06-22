# 用户工程测试实验场

这个目录只保存测试定义，不保存运行时生成的工作区、派生数据和结果数据。

## 结构

- `fixture_manifest.json`
  - 定义样本源文件、图片、查询场景和增量场景

## 运行

使用仓库脚本生成并执行本地实验场：

```bash
python3 scripts/run_user_workspace_lab.py --clean
python3 scripts/run_user_workspace_lab.py --scenario baseline --keep-runtime
```

默认运行目录：

- `tests/runtime/user_project_lab/`

其中会生成：

- `raw/`
- `assets/`
- `workspace/`
- `reports/`

这些数据只保留在本地，不提交到 Git。
