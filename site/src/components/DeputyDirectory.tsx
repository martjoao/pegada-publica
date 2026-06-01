import { useMemo, useState } from "react";
import type { Card } from "../lib/types";
import { statusLabel, statusColor } from "../lib/labels";

const norm = (s: string) =>
  s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

const BASE = import.meta.env.BASE_URL;

export default function DeputyDirectory({ deputies }: { deputies: Card[] }) {
  const [q, setQ] = useState("");
  const [onlyInOffice, setOnlyInOffice] = useState(true);
  const [party, setParty] = useState("");
  const [uf, setUf] = useState("");

  const parties = useMemo(
    () =>
      [...new Set(deputies.map((d) => d.party).filter(Boolean) as string[])].sort(),
    [deputies],
  );
  const ufs = useMemo(
    () =>
      [...new Set(deputies.map((d) => d.state).filter(Boolean) as string[])].sort(),
    [deputies],
  );

  const nq = norm(q.trim());
  const filtered = deputies.filter(
    (d) =>
      (!onlyInOffice || d.in_office) &&
      (!party || d.party === party) &&
      (!uf || d.state === uf) &&
      (!nq || norm(d.name).includes(nq)),
  );

  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="🔍  Buscar por nome…"
        className="mb-3 w-full rounded border border-slate-300 px-3 py-2"
      />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <button
          onClick={() => setOnlyInOffice((v) => !v)}
          className={`rounded-full px-3 py-1 font-medium ${
            onlyInOffice ? "bg-[#1f3a5f] text-white" : "bg-slate-200 text-slate-700"
          }`}
        >
          {onlyInOffice ? "✓ " : ""}Em exercício
        </button>
        <select
          value={party}
          onChange={(e) => setParty(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1"
        >
          <option value="">Partido</option>
          {parties.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <select
          value={uf}
          onChange={(e) => setUf(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1"
        >
          <option value="">UF</option>
          {ufs.map((u) => (
            <option key={u} value={u}>{u}</option>
          ))}
        </select>
        <span className="ml-auto text-slate-500">{filtered.length} deputados</span>
      </div>

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((d) => (
          <li key={d.id}>
            <a
              href={`${BASE}deputados/${d.id}`}
              className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 hover:border-[#1f3a5f]"
            >
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-slate-200 text-sm font-semibold text-slate-600">
                {d.name.slice(0, 1)}
              </span>
              <span className="min-w-0">
                <span className="block truncate font-semibold">{d.name}</span>
                <span className="block text-xs text-slate-600">
                  {d.party ?? "—"} · {d.state ?? "—"}
                </span>
                <span
                  className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] text-white ${statusColor(
                    d.status,
                  )}`}
                >
                  {statusLabel(d.status)}
                </span>
              </span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
