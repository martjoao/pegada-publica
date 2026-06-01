import { useMemo, useState } from "react";
import type { Card } from "../lib/types";
import { statusLabel, statusColor } from "../lib/labels";

const norm = (s: string) =>
  s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

// BASE_URL has no trailing slash in the static build; normalize before concat.
const BASE = import.meta.env.BASE_URL.replace(/\/?$/, "/");

/** Photo with a graceful fallback to the senator's initial. */
function Avatar({ name, src }: { name: string; src: string | null }) {
  const [ok, setOk] = useState(Boolean(src));
  if (ok && src) {
    return (
      <img
        src={src}
        alt=""
        width={44}
        height={44}
        loading="lazy"
        onError={() => setOk(false)}
        className="h-11 w-11 shrink-0 rounded-full bg-slate-200 object-cover"
      />
    );
  }
  return (
    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-slate-200 text-sm font-semibold text-slate-600">
      {name.slice(0, 1)}
    </span>
  );
}

/**
 * Live party-distribution chart over the given set. Click a party to toggle it
 * as the active filter; the chart still lists every party so it stays a picker.
 */
function PartyChart({
  senators,
  selected,
  onSelect,
}: {
  senators: Card[];
  selected: string;
  onSelect: (party: string) => void;
}) {
  const rows = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of senators) {
      const p = s.party ?? "—";
      counts.set(p, (counts.get(p) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [senators]);
  const max = rows.length ? rows[0][1] : 1;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Senadores por partido
      </h2>
      <ul className="max-h-72 space-y-0.5 overflow-y-auto pr-1">
        {rows.map(([party, n]) => {
          const isSelected = party === selected;
          const clickable = party !== "—";
          return (
            <li key={party}>
              <button
                type="button"
                disabled={!clickable}
                onClick={() => onSelect(party)}
                title={clickable ? `Filtrar por ${party}` : undefined}
                className={`flex w-full items-center gap-2 rounded px-1 py-0.5 text-xs ${
                  isSelected
                    ? "bg-slate-100 ring-1 ring-[#1f3a5f]"
                    : clickable
                      ? "hover:bg-slate-50"
                      : "cursor-default"
                }`}
              >
                <span className="w-32 shrink-0 whitespace-nowrap text-right text-slate-600">
                  {party}
                </span>
                <span className="flex-1">
                  <span
                    className={`block h-3 rounded ${isSelected ? "bg-[#0f2747]" : "bg-[#1f3a5f]"}`}
                    style={{ width: `${Math.max((n / max) * 100, 1)}%` }}
                  />
                </span>
                <span className="w-7 text-right tabular-nums text-slate-500">{n}</span>
              </button>
            </li>
          );
        })}
        {rows.length === 0 && (
          <li className="text-xs text-slate-400">Nenhum senador.</li>
        )}
      </ul>
    </div>
  );
}

export default function SenatorDirectory({ senators }: { senators: Card[] }) {
  const [q, setQ] = useState("");
  const [onlyInOffice, setOnlyInOffice] = useState(true);
  const [party, setParty] = useState("");
  const [uf, setUf] = useState("");

  const parties = useMemo(
    () =>
      [...new Set(senators.map((s) => s.party).filter(Boolean) as string[])].sort(),
    [senators],
  );
  const ufs = useMemo(
    () =>
      [...new Set(senators.map((s) => s.state).filter(Boolean) as string[])].sort(),
    [senators],
  );

  const nq = norm(q.trim());
  // chartBase = everything except the party filter, so the chart stays a full picker.
  const passesBase = (s: Card) =>
    (!onlyInOffice || s.in_office) &&
    (!uf || s.state === uf) &&
    (!nq || norm(s.name).includes(nq));
  const chartBase = senators.filter(passesBase);
  const filtered = chartBase.filter((s) => !party || s.party === party);

  const toggleParty = (p: string) => setParty((prev) => (prev === p ? "" : p));

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
        {party && (
          <button
            onClick={() => setParty("")}
            className="rounded-full bg-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-300"
          >
            {party} ✕
          </button>
        )}
        <span className="ml-auto text-slate-500">{filtered.length} senadores</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <aside className="lg:sticky lg:top-4 lg:self-start">
          <PartyChart senators={chartBase} selected={party} onSelect={toggleParty} />
        </aside>

        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {filtered.map((s) => (
            <li key={s.id}>
              <a
                href={`${BASE}senadores/${s.id}`}
                className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 hover:border-[#1f3a5f]"
              >
                <Avatar name={s.name} src={s.photo_url} />
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{s.name}</span>
                  <span className="block text-xs text-slate-600">
                    {s.party ?? "—"} · {s.state ?? "—"}
                  </span>
                  {s.status && s.status !== "in_office" && (
                    <span
                      className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] text-white ${statusColor(
                        s.status,
                      )}`}
                    >
                      {statusLabel(s.status)}
                    </span>
                  )}
                </span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
