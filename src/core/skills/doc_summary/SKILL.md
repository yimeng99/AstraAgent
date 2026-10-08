---
name: doc-summary
description: 对单篇飞书 Docx 文档做结构化摘要、抽取大纲 / 关键信息 / 表格数据 / 回答针对该文档的具体问题。当用户给一个具体 wiki 节点并要求理解 / 解释 / 总结时使用。
---

# 单文档摘要技能

对**单篇**飞书 Docx 文档做结构化理解。不跨文档汇总。

## 何时使用

- 「帮我看下这篇 wiki 说了什么」「总结一下这篇文档」
- 「这个文档的接口是什么」「这个 wiki 提到了哪些参数」
- 「在这个文档里搜 X」

## 工具调用

```bash
# 1) 解析 wiki 节点 → 拿 doc token
lark-cli api POST /open-apis/wiki/v2/spaces/get_node \
  --data '{"token":"wikdXXXX"}' --as bot

# 2) 拉 docx 内容（markddown 格式）
lark-cli docs +fetch --api-version v2 --doc doccnXXXX --as bot
```

## 输出结构

```markdown
## 文档元信息
- 标题：...
- Wiki 节点：wikdXXXX
- Docx token：doccnYYYY

## 大纲
1. 第一节
   1.1 ...
2. 第二节
   ...

## 关键信息
- 接口 / API：...
- 配置项 / 参数：...
- 注意事项：...

## 针对用户问题的回答
（直接回答用户原问题，引用文档段落或 block 编号）
```

## 行为规范

- 答案必须基于文档内容，**不能**凭记忆补全
- 找不到答案时明确说「文档未提及」，不要假装有
- 引用具体段落用 `> 引用文本` + block 编号

## 限制

- 不修改文档、不搜索其他 wiki
- 不执行 shell 或代码