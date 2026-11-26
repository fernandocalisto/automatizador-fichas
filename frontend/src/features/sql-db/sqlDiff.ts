export type DiffLineKind = "equal" | "added" | "removed";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  oldLineNumber: number | null;
  newLineNumber: number | null;
}

export interface LineDiffResult {
  lines: DiffLine[];
  addedCount: number;
  removedCount: number;
  equalCount: number;
  hasChanges: boolean;
}

function normalizeLines(input: string): string[] {
  if (!input) return [];
  return input.replace(/\r\n/g, "\n").split("\n");
}

/**
 * Computes a deterministic line-by-line diff between `savedText` (base revision)
 * and `currentText` (editor buffer) using an LCS table with prefix/suffix trimming.
 */
export function computeLineDiff(
  savedText: string,
  currentText: string,
): LineDiffResult {
  const oldLines = normalizeLines(savedText);
  const newLines = normalizeLines(currentText);

  if (oldLines.length === 0 && newLines.length === 0) {
    return {
      lines: [],
      addedCount: 0,
      removedCount: 0,
      equalCount: 0,
      hasChanges: false,
    };
  }

  let prefix = 0;
  const minLen = Math.min(oldLines.length, newLines.length);
  while (prefix < minLen && oldLines[prefix] === newLines[prefix]) {
    prefix++;
  }

  let suffix = 0;
  while (
    suffix < minLen - prefix &&
    oldLines[oldLines.length - 1 - suffix] ===
      newLines[newLines.length - 1 - suffix]
  ) {
    suffix++;
  }

  const oldMid = oldLines.slice(prefix, oldLines.length - suffix);
  const newMid = newLines.slice(prefix, newLines.length - suffix);

  const resultLines: DiffLine[] = [];
  let addedCount = 0;
  let removedCount = 0;
  let equalCount = 0;

  for (let i = 0; i < prefix; i++) {
    resultLines.push({
      kind: "equal",
      text: oldLines[i],
      oldLineNumber: i + 1,
      newLineNumber: i + 1,
    });
    equalCount++;
  }

  const m = oldMid.length;
  const n = newMid.length;

  // Guard against extreme matrix allocations on very large scripts
  if (m * n > 250_000) {
    for (let i = 0; i < m; i++) {
      resultLines.push({
        kind: "removed",
        text: oldMid[i],
        oldLineNumber: prefix + i + 1,
        newLineNumber: null,
      });
      removedCount++;
    }
    for (let j = 0; j < n; j++) {
      resultLines.push({
        kind: "added",
        text: newMid[j],
        oldLineNumber: null,
        newLineNumber: prefix + j + 1,
      });
      addedCount++;
    }
  } else if (m > 0 || n > 0) {
    const dp: number[][] = Array.from({ length: m + 1 }, () =>
      new Array<number>(n + 1).fill(0),
    );
    for (let i = m - 1; i >= 0; i--) {
      for (let j = n - 1; j >= 0; j--) {
        if (oldMid[i] === newMid[j]) {
          dp[i][j] = dp[i + 1][j + 1] + 1;
        } else {
          dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
    }

    let i = 0;
    let j = 0;
    while (i < m && j < n) {
      if (oldMid[i] === newMid[j]) {
        resultLines.push({
          kind: "equal",
          text: oldMid[i],
          oldLineNumber: prefix + i + 1,
          newLineNumber: prefix + j + 1,
        });
        equalCount++;
        i++;
        j++;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        resultLines.push({
          kind: "removed",
          text: oldMid[i],
          oldLineNumber: prefix + i + 1,
          newLineNumber: null,
        });
        removedCount++;
        i++;
      } else {
        resultLines.push({
          kind: "added",
          text: newMid[j],
          oldLineNumber: null,
          newLineNumber: prefix + j + 1,
        });
        addedCount++;
        j++;
      }
    }

    while (i < m) {
      resultLines.push({
        kind: "removed",
        text: oldMid[i],
        oldLineNumber: prefix + i + 1,
        newLineNumber: null,
      });
      removedCount++;
      i++;
    }
    while (j < n) {
      resultLines.push({
        kind: "added",
        text: newMid[j],
        oldLineNumber: null,
        newLineNumber: prefix + j + 1,
      });
      addedCount++;
      j++;
    }
  }

  const oldSuffixStart = oldLines.length - suffix;
  const newSuffixStart = newLines.length - suffix;
  for (let k = 0; k < suffix; k++) {
    resultLines.push({
      kind: "equal",
      text: oldLines[oldSuffixStart + k],
      oldLineNumber: oldSuffixStart + k + 1,
      newLineNumber: newSuffixStart + k + 1,
    });
    equalCount++;
  }

  return {
    lines: resultLines,
    addedCount,
    removedCount,
    equalCount,
    hasChanges: addedCount > 0 || removedCount > 0,
  };
}
