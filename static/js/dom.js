export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => Array.from(document.querySelectorAll(selector));

export function setStatus(selector, message, isError = false) {
  const el = $(selector);
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? "#b42318" : "#657184";
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
