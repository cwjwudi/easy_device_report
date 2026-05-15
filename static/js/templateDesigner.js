export function clone(value) {
  return structuredClone(value || {});
}

export function generateTableId(kind) {
  const prefix = kind === "custom" ? "c" : "q";
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}
