// Reads the JSON produced by the /build stage (the open-data artifact) at build
// time. Path is resolved relative to this module so it works regardless of cwd.
import { readFileSync } from "node:fs";
import type { Card, Deputy, Senator } from "./types";

const DEPUTADOS_DIR = new URL(
  "../../../build/output/deputados/",
  import.meta.url,
);
const SENADORES_DIR = new URL(
  "../../../build/output/senadores/",
  import.meta.url,
);

export function loadIndex(): Card[] {
  const raw = readFileSync(new URL("index.json", DEPUTADOS_DIR), "utf-8");
  return JSON.parse(raw) as Card[];
}

export function loadDeputy(id: number | string): Deputy {
  const raw = readFileSync(new URL(`${id}.json`, DEPUTADOS_DIR), "utf-8");
  return JSON.parse(raw) as Deputy;
}

export function loadSenatorIndex(): Card[] {
  const raw = readFileSync(new URL("index.json", SENADORES_DIR), "utf-8");
  return JSON.parse(raw) as Card[];
}

export function loadSenator(id: number | string): Senator {
  const raw = readFileSync(new URL(`${id}.json`, SENADORES_DIR), "utf-8");
  return JSON.parse(raw) as Senator;
}
