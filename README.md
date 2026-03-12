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

## Changes in v2.14

- Upgrade dcm2niix from v1.0.20241211 to v1.0.20250506
- Add regex pattern matching support for BIDS map entries
- Add fallback to project resource (`BIDS_bidsmap/bidsmap.json`) when project config service BIDS map is not available
- Support `{"mappings": [...]}` wrapped format in project resource BIDS maps
- Regex entries can specify `modality` to directly set the BIDS output subdirectory
- Regex entries without `suffix` are treated as exclusion patterns (matched scans are skipped)
