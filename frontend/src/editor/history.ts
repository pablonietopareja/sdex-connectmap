export const DEFAULT_EDITOR_HISTORY_LIMIT = 100;

export type HistoryEffect = () => void | Promise<void>;

/**
 * One browser-session-only visual editor operation.
 *
 * `before` and `after` are deliberately opaque: callers can retain the smallest
 * immutable snapshot needed to restore the affected visual entities. The
 * callbacks are the source of truth for applying those snapshots and may call
 * asynchronous ConnectMap-local APIs.
 */
export interface EditorHistoryCommand<TBefore = unknown, TAfter = TBefore> {
  action: string;
  affectedIds?: readonly string[];
  before?: TBefore;
  after?: TAfter;
  timestamp?: number;
  undo: HistoryEffect;
  redo: HistoryEffect;
}

/** A command whose initial mutation has not been applied yet. */
export interface ExecutableEditorHistoryCommand<
  TBefore = unknown,
  TAfter = TBefore,
> extends EditorHistoryCommand<TBefore, TAfter> {
  execute: HistoryEffect;
}

export interface SnapshotHistoryCommandOptions<TSnapshot> {
  action: string;
  affectedIds?: readonly string[];
  before: TSnapshot;
  after: TSnapshot;
  apply: (snapshot: TSnapshot) => void | Promise<void>;
  timestamp?: number;
}

export interface EditorHistorySnapshot {
  canUndo: boolean;
  canRedo: boolean;
  busy: boolean;
  undoDepth: number;
  redoDepth: number;
  lastAction: string | null;
  revision: number;
  invalidationReason: string | null;
}

type NormalizedHistoryCommand = Readonly<
  EditorHistoryCommand & {
    affectedIds: readonly string[];
    timestamp: number;
  }
>;

export function createSnapshotHistoryCommand<TSnapshot>(
  options: SnapshotHistoryCommandOptions<TSnapshot>,
): EditorHistoryCommand<TSnapshot> {
  return {
    action: options.action,
    affectedIds: options.affectedIds,
    before: options.before,
    after: options.after,
    timestamp: options.timestamp,
    undo: () => options.apply(options.before),
    redo: () => options.apply(options.after),
  };
}

function normalizeCommand(
  command: EditorHistoryCommand,
): NormalizedHistoryCommand {
  const action = command.action.trim();
  if (!action) {
    throw new Error("An editor history command requires a non-empty action.");
  }
  if (typeof command.undo !== "function" || typeof command.redo !== "function") {
    throw new Error("An editor history command requires undo and redo callbacks.");
  }

  const affectedIds = Object.freeze(
    [...new Set(command.affectedIds ?? [])].filter((id) => id.length > 0),
  );
  return Object.freeze({
    ...command,
    action,
    affectedIds,
    timestamp: command.timestamp ?? Date.now(),
  });
}

/**
 * In-memory command history for one browser session.
 *
 * The store intentionally writes neither localStorage nor SQLite. Persisted
 * visual state remains the responsibility of the command callbacks. A
 * generation token prevents a pending async command from resurrecting entries
 * after `clear()`/`invalidate()`.
 */
export class EditorHistoryStore {
  readonly maxEntries: number;

  private undoStack: NormalizedHistoryCommand[] = [];
  private redoStack: NormalizedHistoryCommand[] = [];
  private listeners = new Set<() => void>();
  private generation = 0;
  private revision = 0;
  private busy = false;
  private invalidationReason: string | null = null;
  private snapshot: EditorHistorySnapshot;

  constructor(maxEntries = DEFAULT_EDITOR_HISTORY_LIMIT) {
    if (!Number.isInteger(maxEntries) || maxEntries < 1) {
      throw new Error("Editor history maxEntries must be a positive integer.");
    }
    this.maxEntries = maxEntries;
    this.snapshot = this.buildSnapshot();
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): EditorHistorySnapshot => this.snapshot;

  /**
   * Record one already-applied visual operation. A drag should call this once,
   * on drag stop, with the drag-start and drag-stop snapshots.
   */
  record(command: EditorHistoryCommand): boolean {
    if (this.busy) return false;
    this.pushUndo(normalizeCommand(command));
    this.redoStack = [];
    this.invalidationReason = null;
    this.publish();
    return true;
  }

  /** Execute and record one not-yet-applied operation. */
  async execute(command: ExecutableEditorHistoryCommand): Promise<boolean> {
    if (this.busy) return false;
    const normalized = normalizeCommand(command);
    const generation = this.beginOperation();
    try {
      await command.execute();
      if (generation !== this.generation) return false;
      this.pushUndo(normalized);
      this.redoStack = [];
      this.invalidationReason = null;
      return true;
    } finally {
      this.endOperation();
    }
  }

  async undo(): Promise<boolean> {
    if (this.busy) return false;
    const command = this.undoStack.at(-1);
    if (!command) return false;

    const generation = this.beginOperation();
    try {
      await command.undo();
      if (
        generation !== this.generation ||
        this.undoStack.at(-1) !== command
      ) {
        return false;
      }
      this.undoStack.pop();
      this.redoStack.push(command);
      this.invalidationReason = null;
      return true;
    } finally {
      this.endOperation();
    }
  }

  async redo(): Promise<boolean> {
    if (this.busy) return false;
    const command = this.redoStack.at(-1);
    if (!command) return false;

    const generation = this.beginOperation();
    try {
      await command.redo();
      if (
        generation !== this.generation ||
        this.redoStack.at(-1) !== command
      ) {
        return false;
      }
      this.redoStack.pop();
      this.pushUndo(command);
      this.invalidationReason = null;
      return true;
    } finally {
      this.endOperation();
    }
  }

  /**
   * Discard history immediately. Pending async effects may finish, but their
   * stale command can no longer modify either stack.
   */
  clear(reason = "cleared"): void {
    this.generation += 1;
    this.undoStack = [];
    this.redoStack = [];
    this.invalidationReason = reason;
    this.publish();
  }

  /** Semantic alias for invalidating history after an incompatible reload. */
  invalidate(reason = "invalidated"): void {
    this.clear(reason);
  }

  private beginOperation(): number {
    this.busy = true;
    this.publish();
    return this.generation;
  }

  private endOperation(): void {
    this.busy = false;
    this.publish();
  }

  private pushUndo(command: NormalizedHistoryCommand): void {
    this.undoStack.push(command);
    if (this.undoStack.length > this.maxEntries) {
      this.undoStack.splice(0, this.undoStack.length - this.maxEntries);
    }
  }

  private buildSnapshot(): EditorHistorySnapshot {
    return Object.freeze({
      canUndo: !this.busy && this.undoStack.length > 0,
      canRedo: !this.busy && this.redoStack.length > 0,
      busy: this.busy,
      undoDepth: this.undoStack.length,
      redoDepth: this.redoStack.length,
      lastAction: this.undoStack.at(-1)?.action ?? null,
      revision: this.revision,
      invalidationReason: this.invalidationReason,
    });
  }

  private publish(): void {
    this.revision += 1;
    this.snapshot = this.buildSnapshot();
    for (const listener of this.listeners) listener();
  }
}

export function createEditorHistoryStore(
  maxEntries = DEFAULT_EDITOR_HISTORY_LIMIT,
): EditorHistoryStore {
  return new EditorHistoryStore(maxEntries);
}

/** Shared store: it lives until the current browser document is reloaded. */
export const editorHistoryStore = createEditorHistoryStore();
