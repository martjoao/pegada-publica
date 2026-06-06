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
  photo_url: string | null;
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
  civil_name: string | null;
  date_of_birth: string | null;
  date_of_death: string | null;
  sex: string | null;
  birth_state: string | null;
  birth_city: string | null;
  education: string | null;
  social_media: string[];
  website: string | null;
}

/** A senator office period also carries the raw afastamento cause that closed it. */
export interface SenatorOfficeInterval {
  condition: string;
  start: string;
  end: string | null;
  legislature: number | null;
  cause: string | null;
}

/** A senator party affiliation (dated, from /filiacoes — not per-legislature). */
export interface SenatorPartyInterval {
  party: string;
  start: string;
  end: string | null;
}

/** Full per-senator detail from senadores/{id}.json. Mirrors Deputy; the 8-year
 *  mandate spans two legislatures, so `terms` carries one entry per legislature. */
export interface Senator {
  id: number;
  name: string;
  photo_url: string | null;
  state: string | null;
  current_party: string | null;
  current_condition: Condition;
  current_status: Status;
  in_office: boolean;
  legislatures: number[];
  terms: { legislature: number; state: string; condition: string }[];
  parties: SenatorPartyInterval[];
  office_periods: SenatorOfficeInterval[];
  names: NameInterval[];
  civil_name: string | null;
  date_of_birth: string | null;
  birth_state: string | null;
  birth_city: string | null;
  sex: string | null;
  email: string | null;
}
