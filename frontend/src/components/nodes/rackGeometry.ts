import type { Point } from "../../types";

export const EMBEDDED_CONNECTION_WIDTH = 330;
export const EMBEDDED_CONNECTION_HEIGHT = 192;
export const RACK_SLOT_GAP = 16;
export const RACK_PADDING_X = 20;
export const RACK_HEADER_HEIGHT = 64;
export const RACK_CONTENT_PADDING_TOP = 16;
export const RACK_FOOTER_HEIGHT = 52;
export const RACK_MIN_DIMENSION = 1;
export const RACK_MAX_DIMENSION = 10;

function safeDimension(value: number): number {
  if (!Number.isFinite(value)) return RACK_MIN_DIMENSION;
  return Math.min(
    RACK_MAX_DIMENSION,
    Math.max(RACK_MIN_DIMENSION, Math.floor(value)),
  );
}

export function rackDimensions(
  rows: number,
  columns: number,
): { width: number; height: number } {
  const safeRows = safeDimension(rows);
  const safeColumns = safeDimension(columns);
  return {
    width:
      RACK_PADDING_X * 2 +
      safeColumns * EMBEDDED_CONNECTION_WIDTH +
      (safeColumns - 1) * RACK_SLOT_GAP,
    height:
      RACK_HEADER_HEIGHT +
      RACK_CONTENT_PADDING_TOP +
      safeRows * EMBEDDED_CONNECTION_HEIGHT +
      (safeRows - 1) * RACK_SLOT_GAP +
      RACK_FOOTER_HEIGHT,
  };
}

export function rackSlotPosition(row: number, column: number): Point {
  const safeRow = Math.max(0, Math.floor(row));
  const safeColumn = Math.max(0, Math.floor(column));
  return {
    x:
      RACK_PADDING_X +
      safeColumn * (EMBEDDED_CONNECTION_WIDTH + RACK_SLOT_GAP),
    y:
      RACK_HEADER_HEIGHT +
      RACK_CONTENT_PADDING_TOP +
      safeRow * (EMBEDDED_CONNECTION_HEIGHT + RACK_SLOT_GAP),
  };
}

export function rackSlotKey(row: number, column: number): string {
  return `${row}:${column}`;
}
