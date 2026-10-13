import { useCallback, useEffect, useMemo, useState } from "react";
import type { ThemePreference } from "../types";

const THEME_STORAGE_KEY = "connectmap.theme";

function isThemePreference(value: string | null): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system";
}

export function useTheme(initialPreference: ThemePreference = "system") {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : initialPreference;
  });
  const [systemDark, setSystemDark] = useState(
    () =>
      window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ?? false,
  );

  const resolvedTheme = useMemo(
    () => (preference === "system" ? (systemDark ? "dark" : "light") : preference),
    [preference, systemDark],
  );

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media?.addEventListener) return undefined;
    const listener = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.style.colorScheme = resolvedTheme;
    const themeColor = document.querySelector<HTMLMetaElement>(
      'meta[name="theme-color"]',
    );
    themeColor?.setAttribute(
      "content",
      resolvedTheme === "dark" ? "#111820" : "#f5f7fa",
    );
  }, [resolvedTheme]);

  const setPreference = useCallback((next: ThemePreference) => {
    localStorage.setItem(THEME_STORAGE_KEY, next);
    setPreferenceState(next);
  }, []);

  return { preference, resolvedTheme, setPreference };
}
