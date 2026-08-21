from __future__ import annotations

import uuid

CONTRACT_DRIVE_ID = "1MZvw0Hn4FBciejld4pm0vHGzJo-9WYWN"
CONTRACT_SHA256 = "0569c29f3c30981dc0965715f740d204e6e129bb89dbb61fb1891fe764b889de"
NAMESPACE = uuid.UUID("c90ec333-f945-46dd-b22f-5128ce38e1bf")

# code|lang|target|same-language query|cross-language query|distractor 1|distractor 2|distractor 3|distractor 4
# D1/D2 are deliberately hard distractors; D4 is in the opposite language.
RAW = r'''G01|de|Für das Gästezimmer im Haus Elbe beträgt die monatliche Warmmiete 490 Euro; Internet ist darin enthalten.|Was zahlt man im Haus Elbe monatlich komplett für das Gästezimmer, und ist Internet schon dabei?|What is the all-in monthly rent for the guest room in House Elbe, and does that already include internet?|Die Kaution für das Gästezimmer im Haus Elbe beträgt 490 Euro und wird vor dem Einzug fällig.|Für das Gästezimmer im Haus Elbe beträgt die monatliche Warmmiete 590 Euro; Internet wird separat berechnet.|Für das Gästezimmer im Haus Weser beträgt die monatliche Warmmiete 490 Euro inklusive Internet.|The guest room in House Elbe costs 490 euros before utilities, and internet is billed separately.
G02|de|Die letzte Besichtigungsrunde für Standort Nord ist am Donnerstag von 14 bis 17 Uhr.|Wann ist am Standort Nord die allerletzte Besichtigungsmöglichkeit?|When is the final viewing window for the northern site?|Die letzte Besichtigungsrunde für Standort Nord ist am Freitag von 14 bis 17 Uhr.|Am Donnerstag findet am Standort Nord eine Schlüsselübergabe von 14 bis 17 Uhr statt.|Die letzte Besichtigungsrunde für Standort Süd ist am Donnerstag von 14 bis 17 Uhr.|The final viewing session for the northern site is on Thursday from 17:00 to 20:00.
G03|de|Die Kaution für Vertrag Orion wird in zwei gleich hohen Raten gezahlt.|Wie ist die Kautionszahlung beim Vertrag Orion aufgeteilt?|How is the security deposit for the Orion contract split up?|Die Kaution für Vertrag Orion wird in drei gleich hohen Raten gezahlt.|Die Monatsmiete für Vertrag Orion wird in zwei Teilzahlungen gezahlt.|Die Kaution für Vertrag Vega wird in zwei gleich hohen Raten gezahlt.|Contract Orion requires the full deposit to be paid before the keys are handed over.
G04|de|Beim Sonntagscheck der Ferienwohnung Küste müssen Toilettenpapier und Duschgel kontrolliert und bei Bedarf aufgefüllt werden.|Welche Verbrauchssachen müssen sonntags in der Ferienwohnung Küste geprüft und nachgefüllt werden?|Which consumable supplies have to be checked and refilled on Sundays in the Coast holiday apartment?|Beim Sonntagscheck der Ferienwohnung Küste müssen Küchenpapier und Spülmittel kontrolliert werden.|Bei der Ferienwohnung Küste werden Toilettenpapier und Duschgel nur mittwochs geprüft.|Beim Sonntagscheck der Ferienwohnung Berg müssen Toilettenpapier und Duschgel kontrolliert werden.|The Sunday inspection of the Coast apartment focuses only on windows and floor damage.
G05|de|Projekt Atlas verwendet PostgreSQL als kanonische Datenbank; der Suchindex ist nur abgeleitet.|Wo liegt im Projekt Atlas die maßgebliche Wahrheit und welche Rolle hat der Suchindex?|In Project Atlas, which system is authoritative and what role does the search index have?|Projekt Atlas verwendet MySQL als kanonische Datenbank und PostgreSQL nur für Berichte.|Projekt Atlas verwendet PostgreSQL ausschließlich als Suchindex; die kanonische Wahrheit liegt in Dateien.|Projekt Boreas verwendet PostgreSQL als kanonische Datenbank; sein Suchindex ist abgeleitet.|Project Atlas stores canonical truth in the search index and rebuilds PostgreSQL from it.
G06|de|Das Sicherungssystem Delta erstellt täglich um 02:00 Uhr ein Backup und bewahrt es 30 Tage auf.|Zu welcher Uhrzeit läuft das tägliche Delta-Backup und wie lange bleibt es erhalten?|At what time is Delta backed up each day, and how long are those backups retained?|Das Sicherungssystem Delta erstellt täglich um 03:00 Uhr ein Backup und bewahrt es 30 Tage auf.|Das Sicherungssystem Delta erstellt jeden Sonntag um 02:00 Uhr ein Backup und bewahrt es 30 Tage auf.|Das Sicherungssystem Delta erstellt täglich um 02:00 Uhr ein Backup und bewahrt es 90 Tage auf.|The Delta system verifies backups every day at 02:00 but creates them only once a week.
G07|de|Der Mietvertrag Lindenhof erlaubt eine Sonderkündigung jeweils zum 31. August.|Zu welchem Datum kann man den Vertrag Lindenhof außerordentlich beenden?|On what date does the Lindenhof lease allow the special termination option?|Der Mietvertrag Lindenhof erlaubt eine Sonderkündigung jeweils zum 31. Juli.|Der Mietvertrag Lindenhof erlaubt nur die reguläre Kündigung zum Jahresende.|Der Mietvertrag Parkhof erlaubt eine Sonderkündigung jeweils zum 31. August.|The Lindenhof lease can be terminated exceptionally on 30 September each year.
G08|de|Die Möbellieferung für Wohnung Hafen ist für den 15. September geplant.|Wann sollen die Möbel für die Wohnung Hafen geliefert werden?|When is the furniture delivery scheduled for the Harbour apartment?|Die Möbellieferung für Wohnung Hafen ist für den 15. Oktober geplant.|Die Fliesenlieferung für Wohnung Hafen ist für den 15. September geplant.|Die Möbellieferung für Wohnung See ist für den 15. September geplant.|Furniture for the Harbour apartment is expected on 5 September.
G09|de|Das Teammeeting des Projekts Kompass findet dienstags um 09:30 Uhr im Raum Elbe statt.|An welchem Wochentag, zu welcher Uhrzeit und in welchem Raum trifft sich das Team von Kompass?|What day, time, and room are used for the regular Compass project team meeting?|Das Teammeeting des Projekts Kompass findet donnerstags um 09:30 Uhr im Raum Elbe statt.|Das Teammeeting des Projekts Kompass findet dienstags um 09:30 Uhr im Raum Weser statt.|Die Schulung des Projekts Kompass findet dienstags um 09:30 Uhr im Raum Elbe statt.|Project Compass meets every Tuesday at 10:30 in room Elbe.
G10|de|Der Versicherungsbeitrag für Police Merkur wird vierteljährlich per Lastschrift eingezogen.|Wie oft und auf welchem Zahlungsweg wird die Police Merkur abgerechnet?|How frequently is the Mercury insurance premium collected, and by what payment method?|Der Versicherungsbeitrag für Police Merkur wird monatlich per Lastschrift eingezogen.|Der Versicherungsbeitrag für Police Merkur wird vierteljährlich per Rechnung bezahlt.|Der Versicherungsbeitrag für Police Venus wird vierteljährlich per Lastschrift eingezogen.|Policy Mercury is charged once per year by direct debit.
G11|de|Der API-Zugriff für Dienst Vega ist ausschließlich für das Projekt Nord freigeschaltet.|Welches Projekt darf die API des Dienstes Vega verwenden?|Which project is allowed to use the Vega service API?|Der API-Zugriff für Dienst Vega ist ausschließlich für das Projekt Süd freigeschaltet.|Der Webzugriff für Dienst Vega ist ausschließlich für das Projekt Nord freigeschaltet.|Der API-Zugriff für Dienst Vega ist für die Projekte Nord und Süd freigeschaltet.|Service Vega permits API calls from every internal project except North.
G12|de|Rechnung 2047 für den Lieferanten Stein wurde am 5. August vollständig bezahlt.|Wann wurde die Rechnung 2047 von Stein komplett beglichen?|When was supplier Stein invoice 2047 paid in full?|Rechnung 2047 für den Lieferanten Stein wurde am 5. August erstellt, aber noch nicht bezahlt.|Rechnung 2047 für den Lieferanten Stein wurde am 5. August nur teilweise bezahlt.|Rechnung 2048 für den Lieferanten Stein wurde am 5. August vollständig bezahlt.|Invoice 2047 from supplier Stein was fully paid on 15 August.
E01|en|The prototype uses a 13-week cash-flow forecast that is refreshed every Monday.|How long is the prototype cash-flow horizon, and when is the forecast updated?|Wie weit reicht die Liquiditätsvorschau des Prototyps und an welchem Tag wird sie aktualisiert?|The prototype uses a 13-month cash-flow forecast that is refreshed every Monday.|The prototype uses a 13-week cash-flow forecast that is refreshed every Friday.|The production system uses a 13-week cash-flow forecast that is refreshed every Monday.|Der Prototyp aktualisiert montags nur einen 13-Tage-Liquiditätsbericht.
E02|en|The mobile status channel sends only critical alerts after 8 p.m.|What kind of notifications may the mobile status channel send after 8 p.m.?|Welche Meldungen darf der mobile Statuskanal nach 20 Uhr noch verschicken?|The mobile status channel sends all alerts after 8 p.m.|The mobile status channel sends only critical alerts after 6 p.m.|The desktop status channel sends only critical alerts after 8 p.m.|Nach 20 Uhr wird der mobile Statuskanal vollständig stummgeschaltet.
E03|en|The data retention policy deletes raw audio after 14 days.|How long does the retention policy keep raw audio?|Nach welcher Zeit werden rohe Audiodateien laut Aufbewahrungsregel gelöscht?|The data retention policy deletes raw audio after 30 days.|The data retention policy deletes transcripts after 14 days but keeps raw audio.|The analytics retention policy deletes raw video after 14 days.|Rohes Audio wird nach vierzehn Monaten archiviert, nicht gelöscht.
E04|en|The backup restore test requires a clean machine with no shared credentials.|What environment is required for the backup restore test?|Welche Umgebung ist für den Wiederherstellungstest vorgeschrieben?|The backup restore test may run on the source machine as long as credentials are shared.|The backup restore test requires a clean machine but allows shared administrator credentials.|The performance test requires a clean machine with no shared credentials.|Der Restore-Test nutzt dieselbe Maschine, aber ein frisches Benutzerprofil.
E05|en|The supplier ships replacement tiles in boxes of twelve.|How many replacement tiles are packed in each supplier box?|Wie viele Ersatzfliesen enthält ein Karton des Lieferanten?|The supplier ships replacement tiles in boxes of ten.|The supplier ships replacement panels in boxes of twelve.|The warehouse stores replacement tiles in boxes of twelve, but the supplier ships them loose.|Der Lieferant verpackt zwölf Ersatzfliesen auf einer Palette, nicht in einem Karton.
E06|en|The tenant handover checklist includes meter readings and key counts.|Which two items must be documented on the tenant handover checklist?|Welche zwei Angaben müssen bei der Mieterübergabe laut Checkliste dokumentiert werden?|The tenant handover checklist includes meter readings but not key counts.|The tenant handover checklist includes key counts and furniture photos but no meter readings.|The cleaning checklist includes meter readings and key counts.|Bei der Wohnungsübergabe werden nur Zählerstände, aber keine Schlüsselanzahlen dokumentiert.
E07|en|The search index is rebuildable and never the canonical source of truth.|What is the authority status of the search index, and can it be rebuilt?|Welche Wahrheitsrolle hat der Suchindex und ist er rekonstruierbar?|The search index is the canonical source of truth and the database is rebuildable from it.|The search index is rebuildable but becomes authoritative when the database is unavailable.|The reporting cache is rebuildable and never the canonical source of truth.|Der Suchindex darf im Notfall vorübergehend als kanonische Wahrheit gelten.
E08|en|The quarterly review compares actual spending with the approved budget.|What does the quarterly review compare?|Welche beiden Größen werden in der Quartalsprüfung miteinander verglichen?|The quarterly review compares forecast revenue with the approved budget.|The monthly review compares actual spending with the approved budget.|The quarterly tax review compares actual tax payments with prior-year estimates.|Die Quartalsprüfung vergleicht nur geplante Ausgaben mit dem beantragten Budget.
E09|en|The service desk escalates unresolved incidents after four business hours.|When does the service desk escalate an incident that is still unresolved?|Nach welcher Frist eskaliert der Service Desk einen noch ungelösten Vorfall?|The service desk escalates unresolved incidents after four calendar hours.|The service desk escalates unresolved incidents after eight business hours.|The security desk escalates unresolved incidents after four business hours.|Nicht gelöste Vorfälle werden erst am nächsten Arbeitstag eskaliert.
E10|en|The invoice workflow needs manager approval above 2,500 euros.|At what amount does the invoice workflow require manager approval?|Ab welchem Betrag braucht der Rechnungsprozess eine Freigabe durch die Führungskraft?|The invoice workflow needs manager approval above 1,500 euros.|The purchase-order workflow needs manager approval above 2,500 euros.|The invoice workflow needs finance approval at exactly 2,500 euros but no manager approval above it.|Rechnungen über 2.500 Euro werden automatisch ohne Freigabe gebucht.
E11|en|The training dataset contains only synthetic customer profiles.|What kind of customer data is allowed in the training dataset?|Welche Art von Kundendaten darf im Trainingsdatensatz enthalten sein?|The training dataset contains anonymized real customer profiles.|The evaluation dataset contains only synthetic customer profiles.|The training dataset contains synthetic supplier profiles and real customer profiles.|Der Trainingsdatensatz enthält pseudonymisierte echte Kundendaten.
E12|en|The warehouse accepts deliveries Monday through Friday from 7 a.m. to 3 p.m.|On which days and during what hours does the warehouse accept deliveries?|An welchen Tagen und zu welchen Uhrzeiten nimmt das Lager Lieferungen an?|The warehouse accepts deliveries Monday through Friday from 9 a.m. to 5 p.m.|The warehouse accepts deliveries Monday through Saturday from 7 a.m. to 3 p.m.|The office accepts visitors Monday through Friday from 7 a.m. to 3 p.m.|Das Lager nimmt werktags nur zwischen 15 und 19 Uhr Lieferungen an.'''


def _id(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def build_benchmark() -> dict:
    records: list[dict] = []
    queries: list[dict] = []
    for line in RAW.splitlines():
        code, lang, target, q_same, q_cross, d1, d2, d3, d4 = line.split("|")
        target_id = _id(code + "-T")
        records.append({
            "record_key": code + "-T", "record_id": target_id, "group": code,
            "language": lang, "role": "target", "hard_distractor": False, "text": target,
        })
        other = "en" if lang == "de" else "de"
        for idx, text in enumerate((d1, d2, d3, d4), start=1):
            records.append({
                "record_key": f"{code}-D{idx}", "record_id": _id(f"{code}-D{idx}"),
                "group": code, "language": other if idx == 4 else lang,
                "role": "distractor", "hard_distractor": idx in (1, 2), "text": text,
            })
        if lang == "de":
            queries.extend([
                {"query_id": code + "-DE", "direction": "de_to_de", "query": q_same, "relevant_record_ids": [target_id]},
                {"query_id": code + "-EN", "direction": "en_to_de", "query": q_cross, "relevant_record_ids": [target_id]},
            ])
        else:
            queries.extend([
                {"query_id": code + "-EN", "direction": "en_to_en", "query": q_same, "relevant_record_ids": [target_id]},
                {"query_id": code + "-DE", "direction": "de_to_en", "query": q_cross, "relevant_record_ids": [target_id]},
            ])
    policy_controls = [
        {
            "control_id": "P01-project-deny",
            "record": {"record_id": _id("P01"), "text": "The confidential Aurora recovery phrase is SILVER HARBOR.", "target_domain": "SecretBench", "purpose": "cross_project_memory", "sensitivity": "CONFIDENTIAL"},
            "unauthorized_authority": {"projects": ["Bench"], "purposes": ["cross_project_memory"], "clearance": "CONFIDENTIAL"},
            "query": "Which recovery phrase belongs to Aurora?", "expected": "BLOCKED_BEFORE_INDEX_QUERY",
        },
        {
            "control_id": "P02-clearance-deny",
            "record": {"record_id": _id("P02"), "text": "The confidential Bench escalation code is ORANGE LANTERN.", "target_domain": "Bench", "purpose": "cross_project_memory", "sensitivity": "CONFIDENTIAL"},
            "unauthorized_authority": {"projects": ["Bench"], "purposes": ["cross_project_memory"], "clearance": "INTERNAL"},
            "query": "What is the confidential escalation code for Bench?", "expected": "NO_CONFIDENTIAL_PARTITION_QUERY",
        },
    ]
    result = {
        "schema": "externes-gehirn.derived-retrieval-phase-b-benchmark",
        "version": "0.1.0",
        "status": "FROZEN_BEFORE_CANDIDATE_RUNTIME",
        "contract_drive_id": CONTRACT_DRIVE_ID,
        "contract_sha256": CONTRACT_SHA256,
        "corpus_count": len(records),
        "query_count": len(queries),
        "hard_distractor_count": sum(1 for record in records if record["hard_distractor"]),
        "records": records,
        "queries": queries,
        "policy_controls": policy_controls,
    }
    assert result["corpus_count"] == 120
    assert result["query_count"] == 48
    assert result["hard_distractor_count"] == 48
    assert {direction: sum(1 for q in queries if q["direction"] == direction) for direction in {q["direction"] for q in queries}} == {
        "de_to_de": 12, "en_to_en": 12, "de_to_en": 12, "en_to_de": 12,
    }
    return result


BENCHMARK = build_benchmark()
