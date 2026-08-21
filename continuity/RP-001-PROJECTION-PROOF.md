# RP-001 – External Brain Reader/Projection Proof

Status: CANDIDATE / NOT YET PASS UNTIL CI EVIDENCE

## Purpose

Prove that a second real home-system repository can independently read and project the frozen `rp-001.v1` continuity contract without importing PETER implementation code and without acquiring writer, dispatch, or Canon-promotion authority.

This is compatibility evidence only. It does not replace the existing External Brain continuity supervisor, the External Brain Canon, Phase-C project truth, or home-system writer authority.

## Frozen provenance

- source repository: `Thomas-Baasch/peter-system-code`
- source branch: `peter-003-import`
- source RP-001 validation commit: `c895f8745b3d7285da5eb7c1af896680903fd681`
- source schema path: `config/rp-001-continuity-contract.schema.v1.json`
- source schema Git blob SHA: `84f6ecdbd4e4b6c24025c4000bb1d6940cae11a3`
- source current-candidate run: `32517661529` / SUCCESS
- frozen fixture semantic SHA-256: `033a062899056145a6cd7d6e95cb389b24233dac2a04137eca10fc9b28ceb693`

The schema is mirrored here only so the independent reader proof is reproducible inside this repository. The PETER repository remains the source of the RP-001 contract definition for this proof.

## Hard boundaries

- `reader_writer_authority = false`
- `dispatch_allowed = false`
- `canon_promotion_allowed = false`
- no write to External Brain Canon
- no modification of `continuity/brain_continuity_supervisor.py`
- no replacement of `continuity/brain-continuity-contract.json`
- no workflow dispatch by the reader
- no merge, payment, delete, publish, production write, threshold change, or stack decision

## Acceptance candidate

The proof is acceptable only if the isolated CI job on Python 3.14.7:

1. validates the mirrored `rp-001.v1` shape;
2. reads the frozen PETER fixture independently;
3. preserves its semantic digest exactly;
4. accepts an `EXTERNAL_BRAIN` home-system identity through the same reader shape;
5. fails closed on unknown versions, missing/unknown fields, malformed timestamps, and malformed owner gates;
6. proves all writer/dispatch/promotion rights remain false;
7. leaves the existing External Brain supervisor and continuity contract in place.

A green result is a second-home-system Reader/Projection compatibility proof, not a production-autonomy or writer-authority proof.
