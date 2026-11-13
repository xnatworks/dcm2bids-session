# dcm2bids-session

XNAT container service image that runs dcm2niix on an imaging session's scans, converts DICOM files to NIFTI format, and organises the output according to the Brain Imaging Data Structure (BIDS) specification. The converted NIFTI and BIDS sidecar JSON files are uploaded back to XNAT as scan-level resources, along with session-level BIDS metadata (dataset_description.json, CHANGES, scans.tsv).

## Features

- Converts DICOM (and IMA) files to NIFTI using dcm2niix
- Applies BIDS naming based on a configurable BIDS map (site-wide, project-level via config service, or project resource)
- Supports regex pattern matching in BIDS maps for flexible series description mapping
- Regex entries can specify a `modality` to override the default BIDS subdirectory
- Regex entries without a `suffix` act as exclusion patterns
- Handles multi-echo acquisitions with automatic echo/part-phase labelling
- Generates session-level BIDS metadata (dataset_description.json, CHANGES, scans.tsv)
- Supports overwrite and skip-unusable options
- Configurable scan field for mapping (series_description, type, or series_class)
- Writes arterial spin labelling (ASL) scans to BIDS `perf/`, with `*_aslcontext.tsv`, an `*_m0scan` for GE 3D PCASL's built-in M0, and the sidecar fields BIDS requires (see [ASL perfusion](#asl-perfusion-perf))

## ASL perfusion (perf/)

Map an ASL series to a name ending in `_asl`. A separately acquired M0 series can be mapped to a name ending in `_m0scan`. Both are written to `perf/`.

Example project BIDS map for a GE 3D PCASL session:

```json
[
    {"series_description": "T1_MPRAGE", "bidsname": "T1w"},
    {"series_description": "ASL_3D_PCASL", "bidsname": "run-01_asl",
     "sidecar": {"BackgroundSuppression": true}}
]
```

For session `ses-01` of subject `sub-01`, that produces:

```
sub-01/ses-01/perf/sub-01_ses-01_run-01_asl.nii.gz
sub-01/ses-01/perf/sub-01_ses-01_run-01_asl.json         (BIDS resource)
sub-01/ses-01/perf/sub-01_ses-01_run-01_aslcontext.tsv   (BIDS resource; one row: deltam)
sub-01/ses-01/perf/sub-01_ses-01_run-01_m0scan.nii.gz
sub-01/ses-01/perf/sub-01_ses-01_run-01_m0scan.json      (BIDS resource; IntendedFor the asl file)
```

What the container does for a scan mapped to `*_asl`:

- **GE 3D PCASL.** The series holds a perfusion-weighted (deltaM) volume and a proton-density M0 volume, which dcm2niix writes as two files. The deltaM becomes `*_asl` and the M0 becomes `*_m0scan`. Roles come from each volume's DICOM ImageType, not from file order.
- **`*_aslcontext.tsv`** is written from the image type: `deltam` for a GE perfusion image, `cbf` for a CBF map. For anything else (for example a label/control time series), give the pattern in the map entry, e.g. `"aslcontext": ["control", "label"]`. It is repeated to the number of volumes and must divide it evenly. A pattern in the map also tells the container that a single GE image which would otherwise look like an M0 is a label/control series.
- **Sidecar fields.** dcm2niix fills ArterialSpinLabelingType, PostLabelingDelay and LabelingDuration from the GE header. The container adds M0Type `Separate` when it writes an M0, RepetitionTimePreparation (from RepetitionTime), TotalAcquiredPairs (GE only, from NumberOfAverages), and, on the M0, IntendedFor and the ASL image's ArterialSpinLabelingType. Every derived value is logged.
- **`"sidecar"`** in the map entry sets or overrides any field of the scan's own sidecar (`*_asl`, or `*_m0scan` for a separate M0 series). Use it for the fields the DICOM does not record, above all BackgroundSuppression. Without it, the log warns which required fields are missing.
- **`"m0scan_sidecar"`** does the same for the `*_m0scan` written from a GE 3D PCASL series, which has no map entry of its own.
- **Names.** BIDS does not allow `task-` (or any entity other than sub, ses, acq, rec, dir, run, part and echo) in perf names, and spells the suffixes `asl` and `m0scan`. A map entry such as `task-rest_run-01_ASL` is used as `run-01_asl`, with a warning. This happens before run numbers are assigned, so two entries that become the same name (`task-rest_asl`, `task-motor_asl`) get `run-01` and `run-02` instead of overwriting each other.
- **A separate M0 series** mapped to `*_m0scan` gets RepetitionTimePreparation. BIDS also requires IntendedFor, which the series cannot tell; set it in the entry's `"sidecar"`, e.g. `"sidecar": {"IntendedFor": ["bids::sub-01/ses-01/perf/sub-01_ses-01_run-01_asl.nii.gz"]}`. A series whose DICOM ImageType does not say `ASL` is converted only when its entry gives IntendedFor; otherwise (for example a localizer mapped to `m0scan`) it is skipped with a message.

What it will not do:

- Guess BackgroundSuppression, or any field the DICOM does not record.
- Split label/control volumes from other vendors by itself. Without an `"aslcontext"` pattern, `*_aslcontext.tsv` is not written, and the log says so.
- Convert a scan whose dcm2niix outputs it cannot tell apart, other than one perfusion image plus at most one M0. That scan is skipped with a message. This includes multi-echo ASL.
- Convert a series mapped to `*_m0scan` that dcm2niix writes as more than one image (for example a GE 3D PCASL series; map it to `*_asl` instead).
- Upload two scans under one BIDS file name. If a scan would write a name an earlier scan of the session already has (for example a GE 3D PCASL's `run-01_m0scan` and a separate series mapped to `run-01_m0scan`), that scan is skipped with an error; give one of them a different `acq-` or `run-` in the map.
- Change NIfTI data. Images are exactly what dcm2niix writes.

Design notes: [docs/ASL-PERF-DESIGN.md](docs/ASL-PERF-DESIGN.md).

## Changes in v2.19

- BIDS perf/ASL support: `asl` and `m0scan` go to `perf/`, GE 3D PCASL is split into `*_asl` and `*_m0scan`, `*_aslcontext.tsv` is written, required ASL sidecar fields are completed, and the map entry's `"sidecar"`, `"m0scan_sidecar"` and `"aslcontext"` options are added
- Remove entities BIDS does not allow in perf names (e.g. `task-`) and correct the suffix case, with a warning, before run numbering
- Skip a scan mapped to `*_m0scan` when its DICOM is not an ASL image and its map entry gives no IntendedFor
- scans.tsv lists each NIfTI image with its extension, and no sidecars, as BIDS requires (it failed the BIDS validator before), and is stored at `sub-<s>/ses-<l>/` in the session's BIDS resource, its place in a BIDS dataset (it was at the resource root). xnat2bids-setup 2.2 carries it into the BIDS tree it assembles, so a materialized session resource validates.
- Upgrade dcm2niix from v1.0.20250506 to v1.0.20261029
- dataset_description.json BIDSVersion 1.11.2 (was 1.0.1)

## Changes in v2.18

- Renew the XNAT session when it expires during long-running conversions (e.g. very large series), and retry a request once with a fresh session if XNAT rejects it with a 401
- Route all XNAT uploads and deletes through the session-renewing helpers instead of the raw HTTP session

## Changes in v2.14

- Upgrade dcm2niix from v1.0.20241211 to v1.0.20250506
- Add regex pattern matching support for BIDS map entries
- Add fallback to project resource (`BIDS_bidsmap/bidsmap.json`) when project config service BIDS map is not available
- Support `{"mappings": [...]}` wrapped format in project resource BIDS maps
- Regex entries can specify `modality` to directly set the BIDS output subdirectory
- Regex entries without `suffix` are treated as exclusion patterns (matched scans are skipped)
