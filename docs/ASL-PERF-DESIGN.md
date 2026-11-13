# ASL perfusion (BIDS perf/) in dcm2bids-session

Status: added in v2.19. User instructions: the README's "ASL perfusion" section.

## Requirement

ASL scans mapped in a BIDS map must be written as valid BIDS `perf/` data. Before
v2.19, `xnatbidsfns.getSubdir` knew no folder for `asl` or `m0scan`, so these scans were
logged as "does NOT map to a bids subdirectory" and skipped.

BIDS (1.5 onwards; checked against 1.11.2) requires, for each `*_asl` file:

- a `*_aslcontext.tsv` with one `volume_type` row per volume;
- sidecar fields ArterialSpinLabelingType, PostLabelingDelay, BackgroundSuppression,
  M0Type, TotalAcquiredPairs and RepetitionTimePreparation, plus LabelingDuration for
  CASL/PCASL;
- file names that use only sub, ses, acq, rec, dir, run, part and echo.

A `*_m0scan` file needs RepetitionTimePreparation and IntendedFor.

## How it works

`bids_asl.py` holds the logic, which is unit-tested on its own (`test_bids_asl.py`).
`dcm2bids_wholeSession.py` calls it at three points:

1. **Naming, when the map is loaded.** `normalize_perf_map_names` drops entities perf
   does not allow, corrects the suffix case and warns about each changed entry. It runs
   before run numbers are assigned. Normalizing per scan instead would let two entries
   that differ only by a dropped entity (`task-rest_asl`, `task-motor_asl`) both become
   `sub-X_asl`, and one scan would overwrite the other.
2. **Before conversion** (`m0scan_skip_reason`). A scan mapped to `*_m0scan` whose DICOM
   ImageType has no `ASL` is skipped, unless its map entry gives IntendedFor. This is
   the case that prompted the work: a site mapped a GE BRAVO localizer (`ASL_LOCALIZER`) to
   `m0scan`, but the real M0 is inside the PCASL series. Absence of `ASL` is not proof,
   since other vendors' separate M0 series need not carry it. IntendedFor is required
   for a standalone M0 anyway, and it is the user's statement that the series is one.
3. **After dcm2niix, before files are moved to the NIFTI resource.**
   `process_asl_outputs` (for `*_asl`) or `process_standalone_m0scan` (for `*_m0scan`)
   renames the outputs, writes `*_aslcontext.tsv` and completes the sidecars.
   `aslcontext.tsv` and the JSON sidecars stay in the BIDS resource; the NIfTIs move to
   the NIFTI resource, as for every other scan. A scan the step cannot handle is skipped
   before upload, with the reason logged.

### GE 3D PCASL

One GE series contains two volumes. One is the perfusion-weighted difference image
(ImageType `DERIVED\PRIMARY\ASL\PERFUSION`, i.e. deltaM). The other is a proton-density
reference (ImageType `ORIGINAL\PRIMARY\ASL`), which is the M0. dcm2niix (checked with
v1.0.20250506 and v1.0.20261029) writes them as `<name>` and `<name>a`, with the
suffix going to whichever it meets second.

Roles are therefore taken from each output's ImageType (`classify_asl_output`), never
from the file name. Renames go through temporary names, because the M0 may already
hold the name the ASL file needs. More than one perfusion image, more than one M0, or
any output that cannot be classified stops the scan rather than guessing. That
includes multi-echo ASL, which is not supported. A CBF tag wins over a PERFUSION tag.
GE's own CBF series (ImageType `DERIVED\SECONDARY\PROCESSED`) is a derivative and is not
mapped.

`*_aslcontext.tsv` drops `echo-` and `part-` from the ASL name. BIDS allows them on
`*_asl` but not on `*_aslcontext`.

### Derived sidecar values

Each derived value is logged. The map entry's `"sidecar"` overrides the `*_asl` values,
and `"m0scan_sidecar"` overrides the M0 values (the M0 has no map entry of its own):

| Field | Source | Why |
|---|---|---|
| M0Type | `Separate` when an M0 file is written | the M0 is its own file |
| RepetitionTimePreparation | RepetitionTime | for these sequences the readout TR is the preparation TR; dcm2niix does not write the field |
| TotalAcquiredPairs | GE NumberOfAverages (NEX), deltaM only | GE averages NEX label/control pairs into the one deltaM volume |
| IntendedFor (M0) | BIDS URI of the `*_asl` file | BIDS-recommended URI form, not a subject-relative path |
| ArterialSpinLabelingType (M0) | the ASL sidecar's value | dcm2niix labels GE's M0 volume `CASL` but the deltaM `PCASL`; both come from one acquisition |

BackgroundSuppression is never derived. The GE header does not record it reliably,
and a wrong value is worse than a missing one. Without a `"sidecar"` value, the log
warns that it is missing.

## Alternatives rejected

- **Splitting the GE volumes by hand.** dcm2niix already splits them correctly. The
  container only names them, so image data is exactly dcm2niix's.
- **Inferring label/control order for other vendors.** Siemens and Philips order
  varies by sequence and protocol, and dcm2niix does not always record it. The map
  entry's `"aslcontext"` states it instead; without it, the `*_aslcontext.tsv` is not
  written and the log says so.
- **Keeping `task-` in perf names.** The validator rejects it. The map is honoured as
  far as BIDS allows, and the warning tells the site what to change.

## Known limits

- The XNAT BIDS plugin's tree builders (`xnat_bids_plugin`) know `asl` → `perf` but
  not `m0scan` or `*_aslcontext.tsv`. Downloads that go through the plugin may not
  place those files until it is updated.
- GE deltaM and M0 scaling (the deltaM is a sum over NEX, the M0 is not) is left to
  the analysis tool, as BIDS stores the data unscaled.
- A standalone `*_m0scan` cannot name its ASL run. IntendedFor must come from the map.
- BIDSVersion is 1.11.2. bids-validator 3.0.2 bundles the 1.11.1 schema and warns
  UNKNOWN_BIDS_VERSION. Run with `--schema
  https://bids-specification.readthedocs.io/en/v1.11.2/schema.json` to validate against
  1.11.2 and clear the warning.

## Verification

- Unit tests: `python3 -m unittest test_bids_asl test_bids_naming test_regex_matching test_no_site_identifiers`.
  The last is a guard: no client site name, scanner protocol name, subject or session label,
  private address, home path or real accession number may be committed to this public
  repository, and the ASL timing fields in test data (RepetitionTime, RepetitionTimePreparation,
  InversionTime, PostLabelingDelay, LabelingDuration) must be invented round numbers, at most
  one decimal place in seconds, so a site's protocol cannot be copied in. It does not read
  prose, values in milliseconds, or common round values a site may also use.
- End to end (there is no web UI, so no Playwright tier): the image was run through
  XNAT Container Service on a de-identified GE session (3D PCASL,
  BRAVO ASL localizer, MPRAGE, FLAIR) with three BIDS maps:
  - The site's original map (`task-rest_run-01_asl`, localizer mapped to `m0scan`).
    `task-` was removed with warnings and the localizer was skipped. The validator
    reported one error, the missing BackgroundSuppression.
  - The corrected map (`run-01_asl` with `"sidecar": {"BackgroundSuppression": true}`,
    no localizer entry). The validator reported 0 errors.
  - The corrected map with overwrite off. scans.tsv was identical to the converting run.

## scans.tsv (fixed alongside)

Location: `sub-<s>/ses-<l>/sub-<s>_ses-<l>_scans.tsv` inside the session's `BIDS` resource
(`scans_tsv_resource_path`), its place in a BIDS dataset. Before v2.19 it sat at the resource
root. When bids-materialize copies the assembled tree into that resource, a root-level
scans.tsv fails the validator (INVALID_LOCATION). xnat2bids-setup 2.2 reads it from either
place and writes it into the session directory of its tree, keeping only rows whose image the
tree holds.

Before v2.19, `scans.tsv` named single-image scans without their extension, and listed
every file, JSON sidecars included, for multi-echo and fieldmap scans. The validator
rejects both (SCANS_FILENAME_NOT_MATCH_DATASET). From v2.19, `scans_tsv_rows` writes one
row per NIfTI image, with its extension, from the files actually written. For a scan
kept because it already has a NIFTI resource (overwrite off), the rows come from the files in that
resource whose names start with the session's BIDS base (`sub-X_ses-Y_`); files another
tool wrote there are not part of the dataset. If that listing fails, the scan is left out
of scans.tsv with a warning rather than ending the run. Nothing in the XNAT BIDS plugins
reads these rows.

The rows are also the session-wide collision check (`scans_tsv_clashes`). A scan whose
image name an earlier scan already wrote is skipped before upload. Run numbering only
sees map names, so it cannot catch a name the container generates, such as the
`*_m0scan` from a GE PCASL series meeting a separately mapped `*_m0scan`. With overwrite
off, the BIDS-named images of every scan that keeps its NIFTI resource are listed before
the loop. A scan converted earlier in the loop therefore cannot take a name that a later,
retained scan holds.
