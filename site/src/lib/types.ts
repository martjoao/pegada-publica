// Mirrors the build/output JSON (see docs/glossario.md). Keep in sync with build.

export type Status =
  | "in_office"
  | "substitute"
  | "on_leave"
  | "suspended"
  | "vacated"
  | "term_ended"
  | null;

export type Condition = "titular" | "alternate" | null;

export interface PartyInterval {
  party: string;
  start: string;
  end: string | null;
  legislature: number;
}

export interface OfficeInterval {
  condition: string;
  start: string;
  end: string | null;
  legislature: number;
}

export interface NameInterval {
  name: string;
  start: string;
  end: string | null;
}

/** A slim card from deputados/index.json (directory + search). */
export interface Card {
  id: number;
  name: string;
  party: string | null;
  state: string | null;
  status: Status;
  condition: Condition;
  in_office: boolean;
  legislatures: number[];
}

/** Full per-deputy detail from deputados/{id}.json. */
export interface Deputy {
  id: number;
  name: string;
  photo_url: string | null;
  state: string | null;
  current_party: string | null;
  current_condition: Condition;
  current_status: Status;
  in_office: boolean;
  legislatures: number[];
  mandates: { legislature: number; state: string }[];
  parties: PartyInterval[];
  office_periods: OfficeInterval[];
  names: NameInterval[];
}
