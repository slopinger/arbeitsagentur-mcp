"""Short, sourced explanations of the rules a customer of the Agentur für Arbeit / Jobcenter must
know. As of autumn 2026; SGB III = Arbeitslosengeld (Agentur für Arbeit), SGB II = Grundsicherung
für Arbeitsuchende / Bürgergeld (Jobcenter). This is general information, not legal advice.
"""

TOPICS: dict[str, str] = {
    "meldepflichten": """\
Meldepflichten rund um das Ende einer Beschäftigung
- Arbeitsuchend melden (§ 38 Abs. 1 SGB III): spätestens 3 Monate vor dem Ende des Arbeits- oder
  Ausbildungsverhältnisses; erfährt man es kurzfristiger, innerhalb von 3 Tagen nach Kenntnis.
  Gilt auch bei befristeten Verträgen und wenn noch über eine Fortsetzung verhandelt wird.
  Online (eServices), telefonisch oder persönlich. Verspätet -> 1 Woche Sperrzeit (§ 159 Abs. 6 SGB III).
- Arbeitslos melden (§ 141 SGB III): spätestens am ersten Tag ohne Beschäftigung, bis zu 3 Monate
  vorher möglich. Leistungen frühestens ab dem Tag der Meldung.
- Während des Leistungsbezugs: jede Änderung (Arbeitsaufnahme, Nebenjob, Umzug, Krankheit,
  Ortsabwesenheit, Einkommen, Familienstand) unverzüglich mitteilen (§ 60 SGB I). Zu viel gezahlte
  Leistungen werden sonst zurückgefordert, ggf. mit Bußgeld.
Tool: registration_deadlines""",
    "termine": """\
Termine und Meldeversäumnis
- Einer Einladung (Meldeaufforderung, § 309 SGB III / § 59 SGB II) muss man folgen, auch zum
  ärztlichen oder psychologischen Dienst.
- Wer ohne wichtigen Grund nicht erscheint: beim Arbeitslosengeld 1 Woche Sperrzeit
  (§ 159 Abs. 1 Nr. 6 SGB III); beim Jobcenter Leistungsminderung (§ 32 SGB II).
- Verhindert? VOR dem Termin absagen (Telefon, eServices, Brief), Grund nennen und belegen
  (z. B. Arbeitsunfähigkeitsbescheinigung, Vorstellungsgespräch-Einladung). Eine AU-Bescheinigung
  allein entschuldigt nicht immer - bei Zweifeln eine "Wegeunfähigkeitsbescheinigung" erbitten.
- Absage schriftlich dokumentieren: Tool draft_letter(kind="terminabsage"), danach log_correspondence.""",
    "krankheit": """\
Krankheit während der Arbeitslosigkeit
- Arbeitsunfähigkeit und voraussichtliche Dauer unverzüglich melden; dauert sie länger als 3
  Kalendertage, die ärztliche Bescheinigung spätestens am darauffolgenden Arbeitstag vorlegen
  (§ 311 SGB III).
- Arbeitslosengeld wird bis zu 6 Wochen weitergezahlt (§ 146 SGB III), danach zahlt die Krankenkasse
  Krankengeld.
- Tool: draft_letter(kind="arbeitsunfaehigkeit").""",
    "ortsabwesenheit": """\
Urlaub / Ortsabwesenheit
- Wer Leistungen bezieht, muss für die Vermittlung erreichbar sein (§ 138 Abs. 5 SGB III mit
  Erreichbarkeits-Verordnung; § 7b SGB II).
- Abwesenheit vom Wohnort (auch Urlaub zu Hause ohne Erreichbarkeit) VORHER genehmigen lassen; in der
  Regel bis zu 3 Wochen im Kalenderjahr. Ohne Zustimmung entfällt der Anspruch für die Abwesenheit.
- Tool: draft_letter(kind="ortsabwesenheit").""",
    "nebeneinkommen": """\
Nebenjob und Einkommen
- Arbeitslosengeld: Nebentätigkeit unter 15 Stunden pro Woche ist erlaubt; Freibetrag 165 EUR netto im
  Monat, darüber wird angerechnet (§ 155 SGB III). Ab 15 Wochenstunden ist man nicht mehr arbeitslos.
- Jobcenter: Erwerbseinkommen wird nach Abzug von Freibeträgen angerechnet (§ 11b SGB II).
- Immer VOR Beginn melden (Veränderungsmitteilung) und die Bescheinigung über Nebeneinkommen
  vom Arbeitgeber ausfüllen lassen.""",
    "eigenbemuehungen": """\
Eigenbemühungen / Bewerbungsnachweise
- Arbeitslose müssen alles tun, um ihre Beschäftigungslosigkeit zu beenden (§ 138 Abs. 4 SGB III).
  Art und Zahl der Bewerbungen stehen in der Eingliederungsvereinbarung bzw. im Kooperationsplan.
- Nachweise auf Verlangen vorlegen; ungenügende Eigenbemühungen -> 2 Wochen Sperrzeit
  (§ 159 Abs. 1 Nr. 3 SGB III) bzw. Leistungsminderung beim Jobcenter.
- Jede Bewerbung mit Datum, Arbeitgeber, Stelle, Weg und Ergebnis festhalten; Kopien/E-Mails aufheben.
- Bewerbungskosten und Fahrtkosten zu Vorstellungsgesprächen können vorher beantragt werden
  (Vermittlungsbudget, § 44 SGB III).
Tools: add_application, proof_of_applications""",
    "vermittlungsvorschlag": """\
Vermittlungsvorschläge
- Ein Vermittlungsvorschlag mit Rechtsfolgenbelehrung verpflichtet dazu, sich zeitnah (meist
  innerhalb weniger Tage - Frist im Schreiben beachten) zu bewerben und das Ergebnis zurückzumelden.
- Ablehnung oder Vereitelung (z. B. bewusst schlechte Bewerbung) ohne wichtigen Grund: Sperrzeit
  3 / 6 / 12 Wochen beim 1. / 2. / weiteren Mal (§ 159 Abs. 4 SGB III); beim Jobcenter
  Leistungsminderung (§ 31 SGB II).
- Bedenken gegen die Zumutbarkeit (§ 140 SGB III, § 10 SGB II) sofort schriftlich mitteilen und
  trotzdem bewerben, solange nicht geklärt.
Tools: add_application(source="vermittlungsvorschlag"), draft_letter(kind="rueckmeldung_vermittlungsvorschlag")""",
    "sperrzeit": """\
Sperrzeiten beim Arbeitslosengeld (§ 159 SGB III)
- Arbeitsaufgabe (Eigenkündigung, Aufhebungsvertrag, verhaltensbedingte Kündigung) ohne wichtigen
  Grund: 12 Wochen, Anspruchsdauer sinkt um mindestens ein Viertel (§ 148 SGB III). Vor Unterschrift
  eines Aufhebungsvertrags beraten lassen.
- Arbeitsablehnung / Ablehnung oder Abbruch einer Maßnahme: 3 / 6 / 12 Wochen.
- Unzureichende Eigenbemühungen: 2 Wochen. Meldeversäumnis: 1 Woche. Verspätete
  Arbeitsuchendmeldung: 1 Woche.
- Nach Sperrzeiten von insgesamt 21 Wochen erlischt der Anspruch (§ 161 SGB III).
- Vor einer Sperrzeit gibt es eine Anhörung: unbedingt fristgerecht antworten und den wichtigen
  Grund darlegen. Gegen den Sperrzeitbescheid ist Widerspruch möglich.""",
    "widerspruch": """\
Widerspruch und Überprüfung
- Frist: 1 Monat ab Bekanntgabe (§ 84 SGG). Ein Brief gilt seit 2025 am 4. Tag nach Aufgabe zur Post als
  bekanntgegeben (§ 37 Abs. 2 SGB X). Fehlt die Rechtsbehelfsbelehrung: 1 Jahr (§ 66 SGG).
- Schriftlich bei der Stelle, die den Bescheid erlassen hat, über die eServices oder zur Niederschrift;
  eine einfache E-Mail reicht nicht. Eine Begründung kann nachgereicht werden.
- Ein Widerspruch hat beim Arbeitslosengeld/Jobcenter oft keine aufschiebende Wirkung (§ 39 SGB II,
  § 86a SGG) - bei Eilbedarf Antrag beim Sozialgericht prüfen.
- Kostenlos; anwaltliche Hilfe über Beratungshilfeschein (Amtsgericht), Gewerkschaft oder Sozialverband.
- Nach Fristablauf: Überprüfungsantrag nach § 44 SGB X.
Tools: objection_deadline, draft_letter(kind="widerspruch"), log_correspondence""",
    "weiterbildung": """\
Weiterbildung
- Förderung per Bildungsgutschein (§ 81 SGB III, § 16 SGB II) für zugelassene (AZAV-zertifizierte)
  Kurse; vorher Beratung bei der Vermittlungsfachkraft, Förderung ist Ermessensleistung.
- Während einer geförderten Weiterbildung gibt es Arbeitslosengeld bei beruflicher Weiterbildung bzw.
  weiter Bürgergeld/Grundsicherung, ggf. Weiterbildungsgeld und Prämien für Abschlussprüfungen.
- Gute Argumente: Nachfrage am Arbeitsmarkt (Stellenanzeigen), fehlender Berufsabschluss, gesundheitliche
  Gründe, Bestätigung eines Arbeitgebers.
Tools: search_courses, get_course, draft_letter(kind="bildungsgutschein")""",
    "unterlagen": """\
Unterlagen für den Antrag auf Arbeitslosengeld
- Personalausweis/Pass, Steuer-ID, IBAN, Krankenkasse, Sozialversicherungsnummer
- Kündigung bzw. Aufhebungsvertrag, Arbeitsvertrag; die Arbeitsbescheinigung schickt der Arbeitgeber
  meist elektronisch (sonst Vordruck)
- Lebenslauf, Zeugnisse, Nachweise über Kinder (für den erhöhten Leistungssatz)
- Bei Nebenjob: Bescheinigung über Nebeneinkommen""",
    "kontakt": """\
Kontaktwege
- eServices / "Meine BA" (arbeitsagentur.de, Login mit BA-Konto oder BundID): Anträge, Postfach,
  Veränderungsmitteilungen, Bewerbungsnachweise hochladen. Das MCP hat keinen Zugriff darauf.
- Servicenummer für Arbeitnehmer: 0800 4 5555 00 (kostenfrei). Jobcenter haben eigene Nummern
  (find_offices).
- Alles Wichtige schriftlich und nachweisbar senden; Telefonate mit Datum, Uhrzeit, Name und Inhalt
  notieren (log_correspondence mit kind="telefonat").
- Akteneinsicht: § 25 SGB X; Auskunft über gespeicherte Daten: Art. 15 DSGVO.""",
    "kooperationsplan": """\
Eingliederungsvereinbarung / Kooperationsplan
- Arbeitsagentur (SGB III): Eingliederungsvereinbarung bzw. Potenzialanalyse und Plan (§ 37 SGB III).
  Jobcenter (SGB II): Kooperationsplan (§ 15 SGB II).
- Darin stehen Pflichten (z. B. Zahl der Bewerbungen pro Monat) und Leistungen der Behörde (z. B.
  Übernahme von Bewerbungskosten). Pflichten als Aufgaben erfassen (add_task) und die Mindestzahl
  Bewerbungen im Profil setzen (update_profile applications_per_month).
- Mit dem Inhalt nicht einverstanden? Nicht unterschreiben müssen; Änderungen vorschlagen. Beim
  Jobcenter gibt es ein Schlichtungsverfahren (§ 15a SGB II).""",
}


def topic_list() -> str:
    return ", ".join(TOPICS)
