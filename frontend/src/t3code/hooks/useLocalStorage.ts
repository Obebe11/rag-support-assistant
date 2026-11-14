/*
 * RAG Support Assistant: written for this project, not copied. T3 Code's `useLocalStorage`
 * validates values with Effect Schema; the sidebar only needs to remember one
 * number, so this keeps the two function names and drops the dependency.
 */
type Guard<T> = (value: unknown) => value is T;

export function getLocalStorageItem<T>(key: string, guard: Guard<T>): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return null;
    const value: unknown = JSON.parse(raw);
    return guard(value) ? value : null;
  } catch {
    return null;
  }
}

export function setLocalStorageItem<T>(key: string, value: T, guard: Guard<T>): void {
  if (!guard(value)) return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be full or unavailable; the width then lasts for this page view.
  }
}
