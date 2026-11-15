"use client";

const KEY = "spinescope.reviewKey";

/** The local reviewer key lives in tab-scoped storage only. */
export function getReviewKey(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function setReviewKey(value: string) {
  try {
    sessionStorage.setItem(KEY, value);
  } catch {
    /* storage disabled */
  }
}
