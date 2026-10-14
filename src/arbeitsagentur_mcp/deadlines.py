"""Statutory deadline calculations for dealings with the Bundesagentur für Arbeit / Jobcenter.

Everything here is pure date arithmetic so it can be unit-tested without network or storage.
The rules implemented (as of 2026):

* Fristberechnung: § 26 SGB X / § 64 SGG with §§ 187-193 BGB - a period in months ends on the
  day of the last month that has the same number as the triggering day (or the month's last day
  if it has no such day); if it ends on a Saturday, Sunday or public holiday, it moves to the
  next working day.
* Bekanntgabe (deemed notification) of administrative acts: § 37 Abs. 2 SGB X - since
  2025-01-01 on the 4th day after posting / sending electronically (before: 3rd day).
* Widerspruch: § 84 SGG - one month after notification; one year if the Rechtsbehelfsbelehrung
  is missing or wrong (§ 66 Abs. 2 SGG).
* Arbeitsuchendmeldung: § 38 Abs. 1 SGB III - at least three months before the job ends, or
  within three days of learning about the end if that is less than three months away.
* Arbeitslosmeldung: § 141 SGB III - on the first day of unemployment at the latest.
* Anspruchsdauer Arbeitslosengeld: § 147 SGB III.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

STATES = {
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}

_STATE_ALIASES = {name.lower(): code for code, name in STATES.items()} | {
    "baden-wuerttemberg": "BW",
    "nrw": "NW",
    "nordrhein westfalen": "NW",
    "thueringen": "TH",
    "rlp": "RP",
}


def normalize_state(state: str | None) -> str | None:
    """Map a state code or name ("BY", "Bayern", "nrw") to its two-letter code."""
    if not state:
        return None
    s = state.strip()
    if s.upper() in STATES:
        return s.upper()
    code = _STATE_ALIASES.get(s.lower())
    if code is None:
        raise ValueError(f"Unknown Bundesland {state!r}; use one of {', '.join(STATES)}")
    return code


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def public_holidays(year: int, state: str | None = None) -> dict[date, str]:
    """Statutory public holidays for Germany, optionally including those of one Bundesland.

    Only holidays that apply to a whole state are included (e.g. not Mariä Himmelfahrt in parts
    of Bavaria or the Augsburger Friedensfest).
    """
    st = normalize_state(state)
    easter = easter_sunday(year)
    h: dict[date, str] = {
        date(year, 1, 1): "Neujahr",
        easter - timedelta(days=2): "Karfreitag",
        easter + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit",
        easter + timedelta(days=39): "Christi Himmelfahrt",
        easter + timedelta(days=50): "Pfingstmontag",
        date(year, 10, 3): "Tag der Deutschen Einheit",
        date(year, 12, 25): "1. Weihnachtsfeiertag",
        date(year, 12, 26): "2. Weihnachtsfeiertag",
    }
    if st is None:
        return h

    def add(states: set[str], day: date, name: str, since: int = 0) -> None:
        if st in states and year >= since:
            h[day] = name

    add({"BW", "BY", "ST"}, date(year, 1, 6), "Heilige Drei Könige")
    add({"BE"}, date(year, 3, 8), "Internationaler Frauentag", since=2019)
    add({"MV"}, date(year, 3, 8), "Internationaler Frauentag", since=2023)
    add({"BB"}, easter, "Ostersonntag")
    add({"BB"}, easter + timedelta(days=49), "Pfingstsonntag")
    add({"BW", "BY", "HE", "NW", "RP", "SL"}, easter + timedelta(days=60), "Fronleichnam")
    add({"SL"}, date(year, 8, 15), "Mariä Himmelfahrt")
    add({"TH"}, date(year, 9, 20), "Weltkindertag", since=2019)
    add({"BB", "MV", "SN", "ST", "TH"}, date(year, 10, 31), "Reformationstag")
    add({"HB", "HH", "NI", "SH"}, date(year, 10, 31), "Reformationstag", since=2018)
    add({"BW", "BY", "NW", "RP", "SL"}, date(year, 11, 1), "Allerheiligen")
    if st == "SN":
        # Buß- und Bettag: the Wednesday before 23 November.
        d = date(year, 11, 22)
        h[d - timedelta(days=(d.weekday() - 2) % 7)] = "Buß- und Bettag"
    if st == "BE" and year == 2025:
        h[date(2025, 5, 8)] = "80. Jahrestag der Befreiung"
    return h


def non_working_reason(day: date, state: str | None = None) -> str | None:
    """Why `day` is not a working day for deadline purposes (None if it is one)."""
    if day.weekday() == 5:
        return "Samstag"
    if day.weekday() == 6:
        return "Sonntag"
    return public_holidays(day.year, state).get(day)


def next_working_day(day: date, state: str | None = None) -> date:
    while non_working_reason(day, state):
        day += timedelta(days=1)
    return day


def add_months(day: date, months: int) -> date:
    """Same day number `months` later (or earlier); clamps to the end of shorter months."""
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass
class Deadline:
    """A computed deadline plus the reasoning that led to it."""

    deadline: date
    steps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "deadline": self.deadline.isoformat(),
            "weekday": WEEKDAYS[self.deadline.weekday()],
            "steps": self.steps,
            "notes": self.notes,
        }


WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def fmt(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.strftime('%d.%m.%Y')}"


def period_end(
    start: date,
    *,
    months: int = 0,
    weeks: int = 0,
    days: int = 0,
    state: str | None = None,
    shift: bool = True,
) -> Deadline:
    """End of a period triggered by an event on `start` (§ 26 SGB X, § 64 SGG, §§ 187 ff. BGB).

    The trigger day itself is not counted. A period in weeks or months ends on the weekday /
    day number matching `start`; if that day is a Saturday, Sunday or public holiday (in
    `state`, or nationwide if no state is given), the period ends on the next working day.
    """
    if months < 0 or weeks < 0 or days < 0:
        raise ValueError("period lengths must not be negative")
    end = add_months(start, months) + timedelta(weeks=weeks, days=days)
    parts = [f"{n} {unit}" for n, unit in ((months, "Monat(e)"), (weeks, "Woche(n)"), (days, "Tag(e)")) if n]
    steps = [f"Fristbeginn: Ereignis am {fmt(start)} (Ereignistag zählt nicht mit)",
             f"{' + '.join(parts) or '0 Tage'} -> rechnerisches Fristende {fmt(end)}"]
    if shift:
        reason = non_working_reason(end, state)
        if reason:
            moved = next_working_day(end, state)
            steps.append(f"{fmt(end)} ist {reason} -> Fristende verschiebt sich auf {fmt(moved)} "
                         "(§ 26 Abs. 3 SGB X / § 64 Abs. 3 SGG)")
            end = moved
    notes = []
    if state is None and shift:
        notes.append("Nur bundesweite Feiertage berücksichtigt; Bundesland angeben, um Landesfeiertage "
                     "einzubeziehen (maßgeblich ist der Sitz der Behörde).")
    return Deadline(end, steps, notes)


BEKANNTGABE_REFORM = date(2025, 1, 1)


def deemed_notification(sent: date, received: date | None = None) -> tuple[date, list[str]]:
    """Bekanntgabe of a letter from the agency (§ 37 Abs. 2 SGB X).

    Letters posted (or sent electronically) from 2025-01-01 on count as notified on the 4th day
    after posting, earlier ones on the 3rd day. If the letter demonstrably arrived later, the
    actual receipt date counts.
    """
    offset = 4 if sent >= BEKANNTGABE_REFORM else 3
    fiction = sent + timedelta(days=offset)
    steps = [f"Bescheid zur Post gegeben / versendet am {fmt(sent)}; gilt als bekanntgegeben am "
             f"{offset}. Tag danach: {fmt(fiction)} (§ 37 Abs. 2 SGB X"
             f"{', Fassung ab 01.01.2025' if offset == 4 else ', Fassung bis 31.12.2024'})"]
    if received and received > fiction:
        steps.append(f"Tatsächlicher Zugang erst am {fmt(received)} -> dieser Tag ist maßgeblich "
                     "(im Zweifel muss die Behörde den früheren Zugang beweisen; Umschlag/Eingangsdatum aufheben)")
        return received, steps
    if received and received < fiction:
        steps.append(f"Früherer tatsächlicher Zugang ({fmt(received)}) ändert nichts: die Fiktion "
                     "begünstigt den Empfänger, maßgeblich bleibt der spätere fiktive Tag")
    return fiction, steps


def objection_deadline(
    letter_date: date,
    *,
    received: date | None = None,
    delivery: str = "post",
    state: str | None = None,
    legal_remedy_instruction_ok: bool = True,
) -> Deadline:
    """Deadline for a Widerspruch against a Bescheid (§ 84 SGG, § 66 SGG, § 37 SGB X).

    delivery: "post" (or "electronic") applies the Bekanntgabe fiction to `letter_date` (the date
    the letter was posted, usually its date); "personal" means handed over in person on
    `letter_date`.
    """
    if delivery not in {"post", "electronic", "personal"}:
        raise ValueError("delivery must be 'post', 'electronic' or 'personal'")
    if delivery == "personal":
        notified, steps = letter_date, [f"Persönlich ausgehändigt am {fmt(letter_date)} -> an diesem Tag bekanntgegeben"]
    else:
        notified, steps = deemed_notification(letter_date, received)
    if legal_remedy_instruction_ok:
        d = period_end(notified, months=1, state=state)
        d.steps = steps + ["Widerspruchsfrist: 1 Monat nach Bekanntgabe (§ 84 Abs. 1 SGG)"] + d.steps
    else:
        d = period_end(notified, months=12, state=state)
        d.steps = steps + ["Rechtsbehelfsbelehrung fehlt oder ist fehlerhaft -> Jahresfrist (§ 66 Abs. 2 SGG)"] + d.steps
    d.notes += [
        "Der Widerspruch muss bis 24:00 Uhr am letzten Tag bei der Behörde eingegangen sein, die den "
        "Bescheid erlassen hat (schriftlich, elektronisch über die eServices / mit qualifizierter "
        "Signatur, oder zur Niederschrift vor Ort). Eine einfache E-Mail genügt nicht.",
        "Zugang nachweisbar machen: Einwurf-Einschreiben, Fax mit Sendebericht, eService mit "
        "Eingangsbestätigung oder persönliche Abgabe mit Eingangsstempel auf einer Kopie.",
        "Frist verpasst? Ein Überprüfungsantrag nach § 44 SGB X ist auch danach noch möglich.",
    ]
    return d


def job_seeker_registration(employment_end: date, learned_on: date) -> Deadline:
    """When to register as job-seeking (arbeitsuchend melden, § 38 Abs. 1 SGB III).

    `employment_end` is the last day of the employment/training, `learned_on` the day the person
    learned about the end (e.g. received the notice of termination).
    """
    if learned_on > employment_end:
        raise ValueError("learned_on must not be after employment_end")
    three_months_before = add_months(employment_end + timedelta(days=1), -3) - timedelta(days=1)
    steps = [f"Beschäftigung endet mit Ablauf des {fmt(employment_end)}"]
    notes = [
        "Die Meldung geht online (arbeitsagentur.de/eServices), telefonisch oder persönlich; "
        "sie ist sofort möglich und kostet nichts. Je früher, desto besser.",
        "Eine verspätete Meldung führt beim Arbeitslosengeld zu einer Sperrzeit von einer Woche "
        "(§ 159 Abs. 1 Nr. 7, Abs. 6 SGB III).",
        "Die Arbeitsuchendmeldung ersetzt nicht die Arbeitslosmeldung (spätestens am ersten Tag der "
        "Arbeitslosigkeit, siehe registration_deadlines).",
    ]
    if learned_on <= three_months_before:
        steps.append(f"Mehr als drei Monate Vorlauf -> Meldung spätestens drei Monate vor dem Ende: {fmt(three_months_before)}")
        return Deadline(three_months_before, steps, notes)
    raw = learned_on + timedelta(days=3)
    steps.append(f"Kenntnis vom Ende am {fmt(learned_on)}, weniger als drei Monate vorher -> Meldung "
                 f"innerhalb von drei Tagen: {fmt(raw)}")
    d = Deadline(next_working_day(raw), steps, notes)
    if d.deadline != raw:
        d.steps.append(f"Fällt auf {non_working_reason(raw)} -> nächster Werktag {fmt(d.deadline)}")
        d.notes.insert(0, "Sicherer ist es, sich schon vorher online zu melden - das geht auch am Wochenende.")
    return d


def unemployment_registration(employment_end: date) -> Deadline:
    """When to register as unemployed (arbeitslos melden, § 141 SGB III)."""
    first = employment_end + timedelta(days=1)
    return Deadline(
        first,
        [f"Erster Tag der Arbeitslosigkeit: {fmt(first)}",
         "Arbeitslosmeldung spätestens an diesem Tag (§ 141 SGB III); Arbeitslosengeld gibt es "
         "frühestens ab dem Tag der Meldung."],
        ["Die Arbeitslosmeldung ist bis zu drei Monate im Voraus möglich (online mit BundID/"
         "Online-Ausweis oder persönlich).",
         "Den Antrag auf Arbeitslosengeld gleich mit stellen; fehlende Unterlagen "
         "(Arbeitsbescheinigung) können nachgereicht werden."],
    )


# (minimum months of insurance, minimum age, entitlement in months) - § 147 Abs. 2 SGB III
_ALG_TABLE = [
    (12, 0, 6),
    (16, 0, 8),
    (20, 0, 10),
    (24, 0, 12),
    (30, 50, 15),
    (36, 55, 18),
    (48, 58, 24),
]


def alg_entitlement_months(months_insured_5y: int, age: int, months_insured_30m: int | None = None) -> dict:
    """Duration of Arbeitslosengeld (§ 147 SGB III).

    months_insured_5y: months of compulsory insurance (Versicherungspflicht) in the last five
    years before the claim (extended Rahmenfrist used for the duration table).
    months_insured_30m: months of compulsory insurance within the 30-month Rahmenfrist; at least
    12 are needed for any claim (Anwartschaftszeit, §§ 142, 143 SGB III).
    """
    eligible_by_anwartschaft = months_insured_30m is None or months_insured_30m >= 12
    months = 0
    for need, min_age, dur in _ALG_TABLE:
        if months_insured_5y >= need and age >= min_age:
            months = dur
    notes = [
        "Anwartschaftszeit: mindestens 12 Monate versicherungspflichtige Beschäftigung in den "
        "letzten 30 Monaten (Rahmenfrist). Für Kurzzeitbeschäftigte gibt es Sonderregeln (§ 142 Abs. 2 SGB III).",
        "Höhe: 60 % des pauschalierten Nettoentgelts, 67 % mit Kind im Sinne des Steuerrechts (§ 149 SGB III).",
        "Sperrzeiten mindern die Anspruchsdauer; bei einer Sperrzeit wegen Arbeitsaufgabe "
        "(Eigenkündigung/Aufhebungsvertrag ohne wichtigen Grund) um mindestens ein Viertel (§ 148 SGB III).",
        "Restansprüche aus einem früheren Anspruch können hinzukommen. Verbindlich ist nur der Bescheid.",
    ]
    if not eligible_by_anwartschaft:
        return {"entitlement_months": 0, "entitled": False,
                "reason": "Anwartschaftszeit nicht erfüllt (weniger als 12 Monate in 30 Monaten)",
                "notes": notes}
    if months == 0:
        return {"entitlement_months": 0, "entitled": False,
                "reason": "Weniger als 12 Versicherungsmonate", "notes": notes}
    return {"entitlement_months": months, "entitlement_days": months * 30, "entitled": True, "notes": notes}
