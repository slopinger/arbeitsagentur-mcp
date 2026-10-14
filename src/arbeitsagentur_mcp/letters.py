"""Letter templates for written communication with the Agentur für Arbeit / Jobcenter.

The templates produce plain text in the usual German business-letter layout, filled with data
from the case file profile. They are drafts: the user should read, adapt and sign them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, NamedTuple

from .store import parse_date


class Letter(NamedTuple):
    subject: str
    text: str


def _d(value: str | date | None) -> str:
    d = parse_date(value) if value else None
    return d.strftime("%d.%m.%Y") if d else "[Datum]"


def _need(params: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if not params.get(k)]
    if missing:
        raise ValueError(f"Missing parameter(s) for this letter: {', '.join(missing)}")


def _frame(profile: dict[str, str], params: dict[str, Any], subject: str, body: str, *,
           attachments: list[str] | None = None) -> Letter:
    sender = [profile.get("name", "[Vor- und Nachname]")]
    sender += [p.strip() for p in profile.get("address", "[Straße Hausnummer], [PLZ Ort]").split(",")]
    for k in ("phone", "email"):
        if profile.get(k):
            sender.append(profile[k])
    benefit = profile.get("benefit")
    default_recipient = profile.get("jobcenter") if benefit == "grundsicherung" else profile.get("agency")
    recipient = params.get("recipient") or default_recipient or "[Agentur für Arbeit / Jobcenter, Anschrift]"
    ids = []
    if profile.get("customer_number"):
        ids.append(f"Kundennummer: {profile['customer_number']}")
    if profile.get("bg_number"):
        ids.append(f"BG-Nummer: {profile['bg_number']}")
    if params.get("reference"):
        ids.append(f"Ihr Zeichen / Aktenzeichen: {params['reference']}")
    place = params.get("place") or (profile.get("address", "").split(",")[-1].strip().split(" ", 1)[-1] or "[Ort]")
    lines = [*sender, "", *[p.strip() for p in recipient.split(",")], "",
             f"{place}, {_d(params.get('date') or date.today())}", "", subject, *ids, "",
             "Sehr geehrte Damen und Herren,", "", body.strip(), "", "Mit freundlichen Grüßen", "", "",
             "______________________", profile.get("name", "[Unterschrift]")]
    if attachments:
        lines += ["", "Anlagen:", *[f"- {a}" for a in attachments]]
    return Letter(subject, "\n".join(lines) + "\n")


def widerspruch(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "decision_date", "decision_subject")
    reasons = p.get("reasons")
    body = (f"hiermit lege ich gegen Ihren Bescheid vom {_d(p['decision_date'])} über "
            f"{p['decision_subject']} fristgerecht Widerspruch ein.\n\n")
    if reasons:
        body += f"Begründung:\n{reasons.strip()}\n\n"
        if p.get("request"):
            body += f"Ich beantrage, {p['request'].strip()}\n\n"
        else:
            body += "Ich beantrage, den Bescheid aufzuheben bzw. entsprechend zu ändern.\n\n"
    else:
        body += ("Eine Begründung reiche ich nach, sobald ich Einsicht in meine Akte genommen habe. Ich beantrage "
                 "hiermit Akteneinsicht nach § 25 SGB X, vorzugsweise durch Übersendung von Kopien der "
                 "entscheidungserheblichen Unterlagen.\n\n")
    body += "Bitte bestätigen Sie mir den Eingang dieses Widerspruchs schriftlich."
    attachments = p.get("attachments") or []
    return _frame(profile, p, f"Widerspruch gegen den Bescheid vom {_d(p['decision_date'])}", body, attachments=attachments)


def akteneinsicht(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    topic = p.get("topic") or "meine Leistungsakte und meine Vermittlungsakte"
    body = (f"ich beantrage Akteneinsicht nach § 25 SGB X in {topic}. Bitte senden Sie mir Kopien der Unterlagen "
            "zu oder nennen Sie mir einen Termin zur Einsicht in Ihren Räumen.\n\n"
            "Zugleich bitte ich nach Art. 15 DSGVO um Auskunft über alle zu meiner Person gespeicherten Daten, "
            "einschließlich der Vermerke in den IT-Verfahren (z. B. Beratungs- und Vermittlungsvermerke), sowie um "
            "eine kostenlose Kopie dieser Daten (Art. 15 Abs. 3 DSGVO).")
    return _frame(profile, p, "Antrag auf Akteneinsicht und Auskunft nach Art. 15 DSGVO", body)


def ueberpruefungsantrag(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "decision_date", "decision_subject")
    body = (f"ich beantrage die Überprüfung Ihres Bescheides vom {_d(p['decision_date'])} über "
            f"{p['decision_subject']} nach § 44 SGB X.\n\n")
    body += (f"Begründung:\n{p['reasons'].strip()}\n\n" if p.get("reasons") else
             "Ich bin der Auffassung, dass bei Erlass des Bescheides das Recht unrichtig angewandt oder von einem "
             "unrichtigen Sachverhalt ausgegangen wurde. Eine ausführliche Begründung reiche ich nach.\n\n")
    body += "Bitte erteilen Sie mir einen rechtsmittelfähigen Bescheid und erstatten Sie zu Unrecht nicht erbrachte Leistungen nach."
    return _frame(profile, p, "Antrag auf Überprüfung nach § 44 SGB X", body)


def veraenderungsmitteilung(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "change", "effective_date")
    body = (f"hiermit teile ich Ihnen folgende Änderung in meinen Verhältnissen mit (wirksam ab {_d(p['effective_date'])}):\n\n"
            f"{p['change'].strip()}\n\n"
            "Nachweise füge ich bei bzw. reiche ich nach. Bitte berücksichtigen Sie die Änderung und bestätigen Sie mir den Eingang.")
    return _frame(profile, p, "Veränderungsmitteilung", body, attachments=p.get("attachments"))


def terminabsage(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "appointment", "reason")
    body = (f"den Termin am {p['appointment']} kann ich leider nicht wahrnehmen. Grund: {p['reason'].strip()}\n\n"
            "Es handelt sich um einen wichtigen Grund. Ich bitte um einen neuen Termin"
            + (f", möglichst {p['alternatives']}" if p.get("alternatives") else "")
            + ". Einen Nachweis füge ich bei bzw. reiche ich unverzüglich nach.")
    return _frame(profile, p, f"Absage und Bitte um Verlegung des Termins am {p['appointment']}", body,
                  attachments=p.get("attachments"))


def arbeitsunfaehigkeit(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "since")
    until = f" voraussichtlich bis einschließlich {_d(p['until'])}" if p.get("until") else ""
    body = (f"ich teile Ihnen mit, dass ich seit dem {_d(p['since'])}{until} arbeitsunfähig erkrankt bin "
            "(§ 311 SGB III).\n\n"
            "Die ärztliche Arbeitsunfähigkeitsbescheinigung liegt bei bzw. wird Ihnen umgehend nachgereicht.")
    if p.get("appointment"):
        body += f" Den Termin am {p['appointment']} kann ich deshalb nicht wahrnehmen; bitte vergeben Sie einen neuen Termin."
    return _frame(profile, p, "Mitteilung über Arbeitsunfähigkeit", body, attachments=["Arbeitsunfähigkeitsbescheinigung"])


def rueckmeldung_vermittlungsvorschlag(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "position", "employer", "result")
    body = (f"zu Ihrem Vermittlungsvorschlag"
            + (f" vom {_d(p['proposal_date'])}" if p.get("proposal_date") else "")
            + f" für die Stelle \"{p['position']}\" bei {p['employer']}"
            + (f" (Referenznummer {p['job_reference']})" if p.get("job_reference") else "")
            + " melde ich Folgendes zurück:\n\n")
    if p.get("applied_on"):
        body += f"Ich habe mich am {_d(p['applied_on'])} beworben" + (f" ({p['channel']})" if p.get("channel") else "") + ".\n"
    body += f"Ergebnis / Stand: {p['result'].strip()}"
    return _frame(profile, p, "Rückmeldung zum Vermittlungsvorschlag", body, attachments=p.get("attachments"))


def bildungsgutschein(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "course", "provider", "justification")
    body = (f"ich beantrage die Förderung der beruflichen Weiterbildung durch einen Bildungsgutschein (§ 81 SGB III"
            + (", § 16 SGB II" if profile.get("benefit") == "grundsicherung" else "") + ") für folgende Maßnahme:\n\n"
            f"Maßnahme: {p['course']}\nTräger: {p['provider']}\n"
            + (f"Zeitraum: {p['period']}\n" if p.get("period") else "")
            + (f"Maßnahmenummer / Zertifizierung: {p['certification']}\n" if p.get("certification") else "")
            + f"\nBegründung:\n{p['justification'].strip()}\n\n"
            "Ich bitte um ein Beratungsgespräch und um einen schriftlichen Bescheid über meinen Antrag.")
    return _frame(profile, p, "Antrag auf Bildungsgutschein", body, attachments=p.get("attachments"))


def ortsabwesenheit(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "from_date", "to_date")
    body = (f"ich beabsichtige, mich vom {_d(p['from_date'])} bis {_d(p['to_date'])} außerhalb meines Wohnorts "
            + (f"({p['destination']}) " if p.get("destination") else "")
            + "aufzuhalten, und bitte um Ihre vorherige Zustimmung zur Ortsabwesenheit.\n\n"
            + (f"Anlass: {p['reason'].strip()}\n\n" if p.get("reason") else "")
            + "Während dieser Zeit bin ich " + (f"unter {p['reachable']} " if p.get("reachable") else "")
            + "erreichbar. Bitte bestätigen Sie mir die Zustimmung schriftlich.")
    return _frame(profile, p, "Antrag auf Zustimmung zur Ortsabwesenheit", body)


def freitext(profile: dict[str, str], p: dict[str, Any]) -> Letter:
    _need(p, "subject", "body")
    return _frame(profile, p, p["subject"], p["body"], attachments=p.get("attachments"))


LETTERS: dict[str, tuple[Callable[[dict[str, str], dict[str, Any]], Letter], str]] = {
    "widerspruch": (widerspruch, "Widerspruch gegen einen Bescheid. Params: decision_date, decision_subject, "
                    "[reasons, request, reference, attachments]. Ohne reasons: fristwahrender Widerspruch mit Antrag auf Akteneinsicht."),
    "akteneinsicht": (akteneinsicht, "Akteneinsicht (§ 25 SGB X) + DSGVO-Auskunft. Params: [topic, reference]"),
    "ueberpruefungsantrag": (ueberpruefungsantrag, "Überprüfungsantrag nach § 44 SGB X (auch nach Ablauf der "
                             "Widerspruchsfrist). Params: decision_date, decision_subject, [reasons, reference]"),
    "veraenderungsmitteilung": (veraenderungsmitteilung, "Änderung der Verhältnisse melden (Umzug, Nebenjob, "
                                "Arbeitsaufnahme, Familie, Einkommen). Params: change, effective_date, [attachments]"),
    "terminabsage": (terminabsage, "Termin absagen und Verlegung erbitten (nur mit wichtigem Grund). Params: "
                     "appointment (z. B. '20.10.2026, 9:30 Uhr'), reason, [alternatives, attachments]"),
    "arbeitsunfaehigkeit": (arbeitsunfaehigkeit, "Krankmeldung. Params: since, [until, appointment]"),
    "rueckmeldung_vermittlungsvorschlag": (rueckmeldung_vermittlungsvorschlag, "Ergebnis eines Vermittlungsvorschlags "
                                           "melden. Params: position, employer, result, [proposal_date, job_reference, applied_on, channel]"),
    "bildungsgutschein": (bildungsgutschein, "Antrag auf Bildungsgutschein. Params: course, provider, justification, "
                          "[period, certification, attachments]"),
    "ortsabwesenheit": (ortsabwesenheit, "Zustimmung zur Ortsabwesenheit (Urlaub) beantragen. Params: from_date, "
                        "to_date, [destination, reason, reachable]"),
    "freitext": (freitext, "Beliebiges Schreiben im Briefrahmen. Params: subject, body, [attachments]"),
}


def render(kind: str, profile: dict[str, str], params: dict[str, Any]) -> Letter:
    try:
        fn, _ = LETTERS[kind]
    except KeyError:
        raise ValueError(f"Unknown letter kind {kind!r}; available: {', '.join(LETTERS)}") from None
    return fn(profile, params)
