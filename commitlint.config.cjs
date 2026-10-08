/** @type {import('@commitlint/types').UserConfig} */
module.exports = {
  extends: ['@commitlint/config-conventional'],
  parserOptions: {
    // 标题/正文用中文，允许全角标点
    parserPreset: {
      parserOpts: {
        headerPattern: '^(\\w+)(?:\\(([\\w\\s\\.\\-]+)\\))?:\\s*(.+)$',
        headerCorrespondence: ['type', 'scope', 'subject'],
        // subject 长度放宽（中文按字符计）
        subjectPattern: '^(?!\s*$).{1,100}$',
        subjectCorrespondence: ['subject'],
        // type 白名单（与 docs/rules/commit-conventions.md §2 对齐）
        typesPattern: '^(feat|fix|docs|refactor|test|chore|perf|style|ci|revert)$',
        // 允许中文逗号/句号等全角符号
        notesPattern: '^.{0,200}$',
      },
    },
  },
  rules: {
    'header-max-length': [2, 'always', 100],
    'type-empty': [2, 'never'],
    'scope-empty': [0],  // 允许无 scope
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],   // 标题禁句号
    'type-enum': [2, 'always', [
      'feat', 'fix', 'docs', 'refactor', 'test', 'chore',
      'perf', 'style', 'ci', 'revert',
    ]],
  },
  // 允许中文 type-case 检查通过（避免大写报错）
  defaultIgnores: true,
  ignores: [
    // 初始 commit / 合并 commit 等
    (commit) => commit.startsWith('Merge ') || commit.startsWith('Revert '),
  ],
};