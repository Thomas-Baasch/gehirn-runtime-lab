# Gehirn Runtime Lab

Isolierter öffentlicher Testbereich für das Projekt „Externes Gehirn“.

Zweck: reproduzierbare Runtime-Evidenz für den Cross-Project-Knowledge-Routing-Hard-Gate.

Regeln:
- ausschließlich synthetische Testdaten
- keine personenbezogenen oder produktiven Daten
- keine Secrets im Repository
- exakte Kandidaten-Pins
- PASS/FAIL/BLOCKED nur aus tatsächlich ausgeführten Tests
- keine automatische Stackentscheidung

Aktuelle Runtime-Pins:
- SuperLocalMemory 4.0.8
- MemTensor/MemOS v2.0.30 / Python distribution MemoryOS 2.0.30
- EverMind-AI/EverOS v1.2.3

Kritische Golden Tests nach erfolgreichem Bootstrap: GT-04, GT-05, GT-06, GT-08, GT-09, GT-12.

## Gezielte Härtung aus der Codeinventur vom 12.11.2026

Die synthetische Fortsetzungslogik bindet Freigaben jetzt an die vollständigen
geprüften Intent-, Grant- und Preflight-Felder. `AuthorityDecision` enthält den
Evidenzhash, den geprüften Preflight und die Prüfzeit. Der dauerhafte Claim prüft
dieselben Quellen erneut mit seiner aktuellen `as_of`-Zeit. Eine alte positive
Entscheidung kann weder ein geändertes Ziel noch abgelaufene Quellenfrische
überdecken. Der aufrufende Adapter bleibt für echte Quellenherkunft und seine
aktuelle vertrauenswürdige Uhr verantwortlich; diese Bibliothek stellt keine
neue Befugnis aus.

`DurableContinuationLedger.claim()` liefert nun `ClaimResult(status,
claim_token)`. Nur ein neuer oder wiederholbarer eigener Claim erhält ein Token.
`mark_success`, `mark_failure` und `mark_reconcile_required` verlangen dieses
Token als Schlüsselargument. Work, Home, Aktion und Berechtigungsumfang müssen
zum gespeicherten Scope passen. Nach einem erlaubten Retry gilt ein neues Token;
das alte kann den neuen Versuch nicht abschließen. Ein bestätigter Erfolg bleibt
bei einem späten unbelegten Reconcile-Aufruf erhalten. Der getrennte
`DownstreamReconciler` darf weiterhin anhand seiner verifizierten Belege
auflösen. Dafür bindet der Besitzer zunächst die authentifizierte
Dispatch-Quittung mit `bind_downstream_receipt(..., claim_token=..., target=...,
downstream_id=..., receipt_source_ref=...)` an genau seinen Versuch. Ein bereits
gebundener Lauf darf keinem anderen Versuch zugeordnet werden. Die
Reconciliation prüft Work-/Home-/Aktionsscope, konkrete Ziel-/Laufbindung und
Versuchsnummer vor der Auswertung und erneut atomar beim Zustandswechsel.
Belege eines früheren Versuchs können einen laufenden neueren Claim weder
abschließen noch wiederholbar machen. Auch direkt konstruierte
`DownstreamEvidence`-Werte benötigen echte boolesche Wirkungsflags.

Der vorhandene synthetische `dispatch_callback(item)` des
`DurableSafeContinuationExecutor` bleibt eine boolesche Testoberfläche; er erhält
kein Claim-Token und bindet keine echte Dispatch-Quittung. Ein späterer realer
Adapter muss den eigenen Claim- und Quittungsablauf ausdrücklich integrieren
und separat prüfen. Die reine Komponentenprüfung ist deshalb kein Nachweis
einer bereits laufenden automatischen Recovery im Home-System.

Ein Callback bestätigt Erfolg ausschließlich mit `True`. Ein Timeout, eine
unbekannte Ausnahme oder ein anderer Rückgabewert führt zu
`RECONCILE_REQUIRED`. Wiederholbar ist ausschließlich ein
`NoEffectDispatchError`: Der Adapter muss dafür nachweisen, dass keine Aktion
angenommen oder ausgeführt wurde. Das Ersetzen jedes allgemeinen Fehlers durch
diesen Ausnahmetyp wäre eine Vertragsverletzung. `UncertainDispatchOutcome`
bleibt als bestehender Import aus dem dauerhaften Ledger verfügbar.

SQLite erhält additiv Claim-, Scope- und Quittungsfelder sowie eine eindeutige
Historie der an Versuche gebundenen Lauf-IDs; vorhandene Zeilen werden erhalten.
Alte Zeilen ohne diese Bindung werden nicht automatisch
wiederholt oder als aktueller Claim abgeschlossen. Ihre Zuordnung muss vor
einem späteren realen Einsatz separat und anhand von Belegen geklärt werden.
Dies ist kein produktiver Migrations- oder Aktivierungslauf.

Sicherheitsflags müssen echte boolesche Werte, Retryzähler nichtnegative ganze
Zahlen und Berechtigungen eingefrorene Mengen von Textwerten sein. Der
Kontinuitätsprüfer behandelt passende Fortschrittscommits oder eingefrorene
Verträge mehr als 30 Sekunden in der Zukunft als `UNKNOWN`. Fehlerhafte
GitHub-Runlisten liefern einen typisierten Quellfehler; eine beschädigte Zeile
wird nicht weggelassen, um einen scheinbar eindeutigen Lauf zu erzeugen.

Die 100.000 Zufallsfälle enthalten nun gezielt gültige Fortsetzungs- und
Recoveryfälle sowie jeweils einzeln verletzte Gates. Der Test verlangt sowohl
ausgeübte erlaubte Pfade als auch null verbotene und null fälschlich blockierte
erlaubte Dispatches. Die Zahl der Fälle und die bestehenden Schutzgates bleiben
erhalten.

Zusätzliche Gegenfälle lokal ausführen:

```sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_audit_hardening.py' -v
```

Die acht bisherigen ausgewählten Prüfprogramme sowie die betroffenen
Downstream-Reconciliation- und Outcome-Gates müssen weiter bestehen. Alle
Callbacks und Daten bleiben synthetisch. Bestehende Vertrags-IDs und externe
Freigaberegeln werden durch diese Codeänderung nicht geändert; eine spätere
Einbindung benötigt ihre konkrete Verbraucher- und Versionsprüfung.
