import { useCallback, useEffect, useSyncExternalStore } from "react";
import {
  editorHistoryStore,
  type EditorHistoryCommand,
  type EditorHistoryStore,
  type ExecutableEditorHistoryCommand,
} from "../editor/history";

export interface UseEditorHistoryOptions {
  store?: EditorHistoryStore;
  enabled?: boolean;
  keyboardShortcuts?: boolean;
  onError?: (error: unknown) => void;
}

function elementBlocksHistoryShortcut(element: Element): boolean {
  if (
    element.matches(
      "input, textarea, select, option, [role='textbox'], [data-history-shortcuts='ignore']",
    )
  ) {
    return true;
  }
  const editable = element.closest("[contenteditable]");
  if (
    editable &&
    editable.getAttribute("contenteditable")?.toLowerCase() !== "false"
  ) {
    return true;
  }
  return element instanceof HTMLElement && element.isContentEditable;
}

/** True for controls where the browser must retain native text/value undo. */
export function isHistoryShortcutBlocked(
  target: EventTarget | null,
  activeElement: Element | null =
    typeof document === "undefined" ? null : document.activeElement,
): boolean {
  if (target instanceof Element) {
    if (elementBlocksHistoryShortcut(target)) return true;
    const interactiveAncestor = target.closest(
      "input, textarea, select, option, [role='textbox'], [data-history-shortcuts='ignore']",
    );
    if (interactiveAncestor) return true;
  }
  return activeElement instanceof Element
    ? elementBlocksHistoryShortcut(activeElement)
    : false;
}

export type EditorHistoryShortcut = "undo" | "redo";

export function getEditorHistoryShortcut(
  event: Pick<
    KeyboardEvent,
    "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey"
  >,
): EditorHistoryShortcut | null {
  if (!event.ctrlKey || event.metaKey || event.altKey) return null;
  const key = event.key.toLowerCase();
  if (key === "y" && !event.shiftKey) return "redo";
  if (key === "z") return event.shiftKey ? "redo" : "undo";
  return null;
}

/**
 * Handle one keyboard event. Returns true only when ConnectMap consumed it.
 */
export function handleEditorHistoryShortcut(
  event: KeyboardEvent,
  store: EditorHistoryStore,
  onError?: (error: unknown) => void,
): boolean {
  if (
    event.defaultPrevented ||
    isHistoryShortcutBlocked(event.target) ||
    store.getSnapshot().busy
  ) {
    return false;
  }

  const shortcut = getEditorHistoryShortcut(event);
  if (!shortcut) return false;
  const state = store.getSnapshot();
  if (
    (shortcut === "undo" && !state.canUndo) ||
    (shortcut === "redo" && !state.canRedo)
  ) {
    return false;
  }

  event.preventDefault();
  const operation = shortcut === "undo" ? store.undo() : store.redo();
  void operation.catch((error: unknown) => onError?.(error));
  return true;
}

export function useEditorHistory(options: UseEditorHistoryOptions = {}) {
  const {
    store = editorHistoryStore,
    enabled = true,
    keyboardShortcuts = true,
    onError,
  } = options;
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  );

  useEffect(() => {
    if (!enabled || !keyboardShortcuts) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      handleEditorHistoryShortcut(event, store, onError);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [enabled, keyboardShortcuts, onError, store]);

  const record = useCallback(
    (command: EditorHistoryCommand) => store.record(command),
    [store],
  );
  const execute = useCallback(
    (command: ExecutableEditorHistoryCommand) => store.execute(command),
    [store],
  );
  const undo = useCallback(() => store.undo(), [store]);
  const redo = useCallback(() => store.redo(), [store]);
  const clear = useCallback((reason?: string) => store.clear(reason), [store]);
  const invalidate = useCallback(
    (reason?: string) => store.invalidate(reason),
    [store],
  );

  return {
    ...snapshot,
    record,
    execute,
    undo,
    redo,
    clear,
    invalidate,
  };
}
