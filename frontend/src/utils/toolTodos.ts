/** 兼容历史里的 Python Command 文本；只读取 todos 数组，绝不执行工具返回值。 */
export function parseToolTodos(result: string) {
  const start = /["']todos["']\s*:\s*\[/.exec(result);
  const offset = start ? start.index + start[0].length - 1 : result.search(/^\s*\[/);
  if (offset < 0) return [];
  let quote = "";
  let depth = 0;
  let normalized = "";
  let value = "";
  for (let index = offset; index < result.length; index++) {
    const char = result[index];
    if (quote) {
      if (char === "\\") {
        const next = result[++index];
        if (next === undefined) return [];
        if (next === quote || next === "'") value += next;
        else {
          try {
            value += JSON.parse(
              `"\\${next}${next === "u" ? result.slice(index + 1, index + 5) : ""}"`,
            );
          } catch {
            value += `\\${next}`;
          }
          if (next === "u") index += 4;
        }
      } else if (char === quote) {
        normalized += JSON.stringify(value);
        quote = "";
      } else value += char;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      value = "";
      continue;
    }
    normalized += char;
    if (char === "[") depth++;
    if (char === "]" && --depth === 0) {
      try {
        const todos = JSON.parse(normalized);
        return todos.filter(
          (todo: { content?: unknown; status?: unknown }) =>
            typeof todo?.content === "string" &&
            ["pending", "in_progress", "completed"].includes(String(todo.status)),
        ) as { content: string; status: string }[];
      } catch {
        return [];
      }
    }
  }
  return [];
}
