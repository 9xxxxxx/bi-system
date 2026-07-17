export function parseCalculatedLiteral(
  value: string,
  dataType: string,
): string | number | boolean | null {
  const normalized = value.trim();
  if (!normalized) return null;
  if (dataType === "integer") {
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed) || !Number.isInteger(parsed)) {
      throw new Error("请输入有效整数");
    }
    return parsed;
  }
  if (dataType === "decimal") {
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed)) throw new Error("请输入有效数字");
    return parsed;
  }
  if (dataType === "boolean") {
    if (normalized === "true") return true;
    if (normalized === "false") return false;
    throw new Error("布尔值只能填写 true 或 false");
  }
  return normalized;
}
