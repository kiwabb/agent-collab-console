"use client";

interface Props {
  add: number;
  rm: number;
  /** Total slots in the strip. Design handoff uses 20. */
  cells?: number;
}

/**
 * Inline 20-slot proportion bar used in the design handoff to summarize
 * a diff's +/− distribution without spending pixels on a chart.
 *
 *   ■■■■■■■■■■■■■■■■■■■□
 *   ↑ 19 green (add)  ↑ 1 red (rm)
 */
export function DiffStatBar({ add, rm, cells = 20 }: Props) {
  const total = Math.max(add + rm, 1);
  const addCells = Math.round((add / total) * cells);
  const rmCells = Math.max(0, cells - addCells - (add + rm === 0 ? cells : 0));
  const neutralCells = add + rm === 0 ? cells : cells - addCells - rmCells;
  const slots: ("a" | "r" | "n")[] = [
    ...Array<"a">(addCells).fill("a"),
    ...Array<"r">(rmCells).fill("r"),
    ...Array<"n">(neutralCells).fill("n"),
  ];
  return (
    <span
      className="inline-flex gap-px items-center"
      title={`+${add} / −${rm}`}
    >
      {slots.map((kind, i) => (
        <i
          key={i}
          className="inline-block size-2 rounded-[1px]"
          style={{
            background:
              kind === "a"
                ? "var(--color-status-done)"
                : kind === "r"
                  ? "var(--color-status-failed)"
                  : "var(--color-border-muted)",
          }}
        />
      ))}
    </span>
  );
}
