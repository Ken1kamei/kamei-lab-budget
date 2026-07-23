# Knowledge Console Verification - 2026-07-23

## Scope

- Restore legacy Notebooks and Protocols to the Web app.
- Group only checksum-confirmed duplicate records.
- Add a shared Notebook/Protocol viewer and private-file access.
- Replace the registry-first screen with a compact, search-first console.

## Source and Restoration Evidence

- Seed source: `gs://kamei-lab-knowledge-678641983168/knowledge-seed/records.json`
- Original seed generation: `1784725624542924`
- Backup:
  `gs://kamei-lab-knowledge-678641983168/knowledge-seed/backups/records-20260723T1156Z-generation-1784725624542924.json`
- Updated seed generation: `1784808002159546`
- Updated seed SHA-256:
  `a4010af5d10455832d8da3bbf95ebf0ae51da506eb8bd4fc9d1283442a7fea62`
- No source records were deleted. SHA-256 metadata was added only to six
  records forming three byte-identical duplicate pairs.

## Automated Verification

- Django test suite: `131 passed`
- `manage.py check`: no issues
- `makemigrations --check --dry-run`: no changes
- Production-mode `collectstatic`: app CSS and favicon present in the manifest
- `git diff --check`: passed

## Candidate Verification

- Initial candidate `00040-puz` returned HTTP 500 because the production static
  manifest could not resolve the favicon. Traffic was not switched.
- The favicon was made independent of the static manifest and the full local
  verification suite was rerun.
- Passing candidate: `kamei-lab-budget-web-staging-00041-jes`
- Candidate image:
  `sha256:0103e582e1027c194f99967888b96aac973adf30dce9b9f0a12155c69580a478`
- Browser checks:
  - 15 Protocols, 52 canonical Notebooks, and 3 grouped duplicates
  - MEF protocol structured content and original-file download visible
  - legacy Notebook metadata visible
  - checksum-confirmed duplicate search returns one canonical result
  - Notebook is the default upload type
  - no horizontal overflow at 1440 px
  - browser console errors and warnings: 0
- Candidate Cloud Run errors after the fix: 0

## Data Verification

- Release execution: `kamei-lab-apps-release-95jct`
  - no migrations left to apply
- Sync execution: `kamei-lab-apps-sync-45hp7`
  - seed records: 69
  - database records: 70
  - canonical records: 67
  - duplicate aliases: 3
- Candidate parity execution: `kamei-lab-apps-verify-sdxd9`
- Production parity execution: `kamei-lab-apps-verify-4978j`
  - Knowledge: seed 69, web-added 1, mirror 70, canonical 67, aliases 3
  - Google Sheets mirror counts matched for Apps, App_Roles, Audit_Log,
    Experiments, Member_Teams, Members, Milestones, Projects, Teams, and
    Updates_Reviews.

## Production

- Production revision: `kamei-lab-budget-web-staging-00041-jes`
- Traffic: 100%
- URL:
  `https://kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app/knowledge/`
- Production browser checks repeated for the MEF Protocol, legacy Notebook,
  counts, layout, and console.
- Production Cloud Run errors after cutover: 0
- No dummy production record was created, so no dummy restoration was needed.

## Remaining Data Caveat

The 69 imported legacy records are searchable and show their source metadata,
but their original Dropbox files have not yet been copied to private Cloud
Storage. Web-uploaded records include private original-file access.
