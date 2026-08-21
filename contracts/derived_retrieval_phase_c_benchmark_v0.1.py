from __future__ import annotations

CONTRACT_DRIVE_ID = "1sF5t2XKJJywjuaRMfaUKodUR_OAwGuZfybstXeqitM8"
CONTRACT_FILE_SHA256 = "1e1e56ff6fc52484af8e198c36e32554642dab21b0e777bb33f7ba6dea9b6768"
PURPOSE = "cross_project_memory"
PROJECT = "Bench"

GROUPS = [
    {"id":"C01","kind":"conflict","subject":"Haus Elbe / House Elbe Warmmiete rent","records":["Für das Gästezimmer im Haus Elbe beträgt die Warmmiete 490 Euro inklusive Internet.","Für das Gästezimmer im Haus Elbe beträgt die Warmmiete 590 Euro und Internet wird separat berechnet."],"queries":["Wie hoch ist die Warmmiete im Haus Elbe und ist Internet enthalten?","What is the all-in rent for the guest room in House Elbe, and is internet included?"]},
    {"id":"C02","kind":"conflict","subject":"Standort Nord / North site Besichtigung viewing","records":["Die letzte Besichtigungsrunde am Standort Nord ist Donnerstag von 14 bis 17 Uhr.","Die letzte Besichtigungsrunde am Standort Nord ist Freitag von 14 bis 17 Uhr."],"queries":["Wann ist die letzte Besichtigungsrunde am Standort Nord?","When is the final viewing session at the North site?"]},
    {"id":"C03","kind":"conflict","subject":"Projekt Atlas / Project Atlas kanonische canonical Datenbank database","records":["Projekt Atlas verwendet PostgreSQL als kanonische Datenbank; der Suchindex ist nur abgeleitet.","Projekt Atlas verwendet MySQL als kanonische Datenbank; PostgreSQL ist nur für Berichte."],"queries":["Welche Datenbank ist im Projekt Atlas kanonisch?","Which database is canonical for Project Atlas?"]},
    {"id":"C04","kind":"conflict","subject":"Delta Backup Sicherung Uhrzeit time","records":["Das Sicherungssystem Delta erstellt täglich um 02:00 Uhr ein Backup.","Das Sicherungssystem Delta erstellt täglich um 03:00 Uhr ein Backup."],"queries":["Um wie viel Uhr läuft das tägliche Delta-Backup?","At what time does the daily Delta backup run?"]},
    {"id":"C05","kind":"conflict","subject":"Lindenhof Sonderkündigung special termination","records":["The Lindenhof lease allows special termination on 31 August each year.","The Lindenhof lease allows special termination on 31 July each year."],"queries":["Zu welchem Datum erlaubt Lindenhof die Sonderkündigung?","On what date does Lindenhof allow special termination?"]},
    {"id":"C06","kind":"conflict","subject":"Kompass Compass Teammeeting Raum room","records":["The Compass project team meets every Tuesday at 09:30 in room Elbe.","The Compass project team meets every Tuesday at 09:30 in room Weser."],"queries":["In welchem Raum trifft sich das Kompass-Team dienstags um 09:30?","Which room is used for the Compass team meeting on Tuesdays at 09:30?"]},
    {"id":"C07","kind":"conflict","subject":"Merkur Mercury Versicherung insurance cadence","records":["Policy Mercury is collected quarterly by direct debit.","Policy Mercury is collected monthly by direct debit."],"queries":["Wie oft wird die Police Merkur per Lastschrift eingezogen?","How often is Policy Mercury collected by direct debit?"]},
    {"id":"C08","kind":"conflict","subject":"Vega API Projekt project scope","records":["The Vega service API is enabled only for Project North.","The Vega service API is enabled only for Project South."],"queries":["Welches Projekt darf die Vega-API verwenden?","Which project is allowed to use the Vega service API?"]},
    {"id":"R01","kind":"correction","subject":"Rechnung Invoice 2047 Zahlungsdatum payment date","records":["Rechnung 2047 wurde am 5. August vollständig bezahlt.","Korrektur: Rechnung 2047 wurde tatsächlich am 6. August vollständig bezahlt."],"queries":["Wann wurde Rechnung 2047 vollständig bezahlt?","When was invoice 2047 paid in full?"]},
    {"id":"R02","kind":"correction","subject":"Vertrag Contract Orion Kaution deposit Raten installments","records":["Die Kaution für Vertrag Orion wird in drei gleich hohen Raten gezahlt.","Korrektur: Die Kaution für Vertrag Orion wird in zwei gleich hohen Raten gezahlt."],"queries":["In wie vielen Raten wird die Kaution bei Vertrag Orion gezahlt?","How many installments are used for the Orion deposit?"]},
    {"id":"R03","kind":"correction","subject":"Ferienwohnung Coast Küste Sonntag Sunday Verbrauchssachen consumables","records":["Sonntags werden in der Ferienwohnung Küste Toilettenpapier und Duschgel geprüft.","Korrektur: Sonntags werden in der Ferienwohnung Küste Küchenpapier und Spülmittel geprüft."],"queries":["Welche Verbrauchssachen werden sonntags in der Ferienwohnung Küste geprüft?","Which consumables are checked on Sundays in the Coast apartment?"]},
    {"id":"R04","kind":"correction","subject":"Prototype Prototyp 13-week 13-Wochen cash-flow Liquiditätsvorschau refresh Aktualisierung","records":["The 13-week prototype cash-flow forecast is refreshed every Friday.","Correction: the 13-week prototype cash-flow forecast is refreshed every Monday."],"queries":["An welchem Tag wird die 13-Wochen-Liquiditätsvorschau aktualisiert?","On which day is the 13-week cash-flow forecast refreshed?"]},
    {"id":"R05","kind":"correction","subject":"Raw Roh audio retention Aufbewahrung","records":["Raw audio is retained for 30 days.","Correction: raw audio is retained for 14 days."],"queries":["Wie lange wird Roh-Audio aufbewahrt?","How long is raw audio retained?"]},
    {"id":"R06","kind":"correction","subject":"Tenant Mieter handover Übergabe checklist Checkliste","records":["The tenant handover checklist records meter readings only.","Correction: the tenant handover checklist records meter readings and key counts."],"queries":["Was muss bei der Mieterübergabe dokumentiert werden?","What must be documented on the tenant handover checklist?"]},
    {"id":"R07","kind":"correction","subject":"Invoice Rechnung manager approval Freigabe threshold Betrag","records":["Manager approval is required for invoices above 1,500 euros.","Correction: manager approval is required for invoices above 2,500 euros."],"queries":["Ab welchem Rechnungsbetrag ist Managerfreigabe nötig?","Above what invoice amount is manager approval required?"]},
    {"id":"R08","kind":"correction","subject":"Warehouse Lager delivery Lieferungen days Wochentage","records":["The warehouse accepts deliveries Monday through Saturday.","Correction: the warehouse accepts deliveries Monday through Friday."],"queries":["An welchen Wochentagen nimmt das Lager Lieferungen an?","On which days does the warehouse accept deliveries?"]},
    {"id":"S01","kind":"current","subject":"Mobile status Statuskanal critical kritisch alerts Meldungen","records":["The mobile status channel sends only critical alerts after 8 p.m."],"queries":["Welche Meldungen sendet der mobile Statuskanal nach 20 Uhr?","What notifications does the mobile status channel send after 8 p.m.?"]},
    {"id":"S02","kind":"current","subject":"Backup restore Wiederherstellung test environment Umgebung","records":["The backup restore test requires a clean machine with no shared credentials."],"queries":["Welche Umgebung braucht der Restore-Test?","What environment is required for the backup restore test?"]},
    {"id":"S03","kind":"current","subject":"Search Suchindex index authority Wahrheit rebuild neu aufgebaut","records":["The search index is rebuildable and is never the canonical source of truth."],"queries":["Ist der Suchindex kanonische Wahrheit und kann er neu aufgebaut werden?","Is the search index canonical truth, and can it be rebuilt?"]},
    {"id":"S04","kind":"current","subject":"Training Trainingsdatensatz dataset customer Kunden profiles Profile","records":["The training dataset contains only synthetic customer profiles."],"queries":["Welche Kundendaten enthält der Trainingsdatensatz?","What customer data does the training dataset contain?"]},
    {"id":"E01","kind":"empty","subject":"Project Aurora emergency color","records":[],"queries":["Welche Notfallfarbe gilt im Projekt Aurora?","What emergency color is defined for Project Aurora?"]},
    {"id":"E02","kind":"empty","subject":"Contract Nova notice date","records":[],"queries":["Zu welchem Datum kann Vertrag Nova gekündigt werden?","On what date can Contract Nova be terminated?"]},
    {"id":"E03","kind":"empty","subject":"Service Zephyr network port","records":[],"queries":["Welchen Netzwerkport verwendet der Dienst Zephyr?","Which network port does the Zephyr service use?"]},
    {"id":"E04","kind":"empty","subject":"Warehouse Pine weekend hours","records":[],"queries":["Welche Wochenendöffnungszeiten hat Lager Pine?","What are the weekend opening hours of Warehouse Pine?"]},
]

BACKGROUND = [
    {"subject": f"Background subject {i:02d}", "text": (f"Hintergrundnotiz {i:02d}: Die Testanlage enthält eine unabhängige Referenz über Thema Nummer {i}." if i % 2 else f"Background note {i:02d}: the evaluation corpus contains an unrelated reference about topic number {i}.")}
    for i in range(1, 49)
]

BENCHMARK = {
    "contract_drive_id": CONTRACT_DRIVE_ID,
    "contract_file_sha256": CONTRACT_FILE_SHA256,
    "project": PROJECT,
    "purpose": PURPOSE,
    "groups": GROUPS,
    "background": BACKGROUND,
    "group_counts": {
        "conflict": sum(g["kind"] == "conflict" for g in GROUPS),
        "correction": sum(g["kind"] == "correction" for g in GROUPS),
        "current": sum(g["kind"] == "current" for g in GROUPS),
        "empty": sum(g["kind"] == "empty" for g in GROUPS),
    },
    "query_count": sum(len(g["queries"]) for g in GROUPS),
    "background_count": len(BACKGROUND),
}
