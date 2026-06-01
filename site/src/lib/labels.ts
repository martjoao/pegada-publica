// The PT display layer: maps canonical English codes (docs/glossario.md) to the
// Portuguese labels shown to users. This is the *only* place EN -> PT happens.

export const STATUS_PT: Record<string, string> = {
  in_office: "Em exercício",
  substitute: "Suplente",
  on_leave: "Licenciado",
  suspended: "Suspenso",
  vacated: "Mandato perdido",
  term_ended: "Mandato encerrado",
};

export const CONDITION_PT: Record<string, string> = {
  titular: "Titular",
  alternate: "Suplente",
};

/** Tailwind badge colour per status. */
export const STATUS_COLOR: Record<string, string> = {
  in_office: "bg-green-700",
  substitute: "bg-slate-500",
  on_leave: "bg-amber-600",
  suspended: "bg-red-700",
  vacated: "bg-stone-500",
  term_ended: "bg-stone-400",
};

export const statusLabel = (s: string | null): string =>
  s ? STATUS_PT[s] ?? s : "—";

export const conditionLabel = (c: string | null): string =>
  c ? CONDITION_PT[c] ?? c : "—";

export const statusColor = (s: string | null): string =>
  s ? STATUS_COLOR[s] ?? "bg-slate-500" : "bg-slate-400";
