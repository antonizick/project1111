// The gallery's thumbnail size, remembered per viewer. Storage can be missing or throw (a private
// window, blocked site data); the default then stands.

import type { TileSize } from "./layout";

const KEY = "p11.gallery-tile-size";

export function loadTileSize(): TileSize {
  try {
    return localStorage.getItem(KEY) === "small" ? "small" : "medium";
  } catch {
    return "medium";
  }
}

export function saveTileSize(size: TileSize): void {
  try {
    localStorage.setItem(KEY, size);
  } catch {
    // Only a convenience: the choice lasts until the next reload.
  }
}
