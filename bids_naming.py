import collections
import os
import re


def _split_bids_extension(filename):
    for extension in (".nii.gz", ".json", ".bval", ".bvec", ".tsv", ".nii"):
        if filename.endswith(extension):
            return filename[:-len(extension)], extension
    return os.path.splitext(filename)


def _insert_entity_before_suffix(filename, entity):
    stem, extension = _split_bids_extension(filename)
    if f"_{entity}" in stem:
        return filename

    suffix_index = stem.rfind("_")
    if suffix_index == -1:
        return f"{stem}_{entity}{extension}"

    return f"{stem[:suffix_index]}_{entity}{stem[suffix_index:]}{extension}"


def build_bids_base(subject, session_label):
    subject_label = re.sub(r"[_-]", "", subject)
    session = re.sub(r"[_-]", "", session_label)
    return f"sub-{subject_label}_ses-{session}_"


def match_regex_pattern(seriesdesc, regex_patterns):
    """Try regex patterns against a series description. Returns matched entry or None."""
    for entry in regex_patterns:
        if re.search(entry["pattern"], seriesdesc):
            return entry
    return None


def resolve_scan_match(seriesdesc, bidsnamemap, regex_patterns):
    """Return (BIDS suffix, regex modality) for a scan, or None when excluded/unmatched."""
    exact_match = bidsnamemap.get(seriesdesc.lower())
    if exact_match:
        return exact_match, None

    regex_match = match_regex_pattern(seriesdesc, regex_patterns)
    if regex_match and regex_match.get("suffix"):
        return regex_match["suffix"], regex_match.get("modality")

    return None


def resolve_bids_suffixes(field_values, bidsnamemap, regex_patterns):
    resolved = []
    for field_value in field_values:
        scan_match = resolve_scan_match(field_value, bidsnamemap, regex_patterns)
        if scan_match:
            resolved.append(scan_match[0])
    return resolved


def duplicate_bids_suffix_counts(field_values, bidsnamemap, regex_patterns):
    counts = collections.Counter(
        resolve_bids_suffixes(field_values, bidsnamemap, regex_patterns)
    )
    return {suffix: count for suffix, count in counts.items() if count > 1}


def add_or_replace_run_entity(bids_suffix, run_index):
    run = f"run-{run_index:02d}"
    splitname = bids_suffix.split("_")

    for index, part in enumerate(splitname[:-1]):
        if re.fullmatch(r"run-\d+", part):
            splitname[index] = run
            return "_".join(splitname)

    splitname.insert(len(splitname) - 1, run)
    return "_".join(splitname)


def build_naming_collision_message(
    scan_id,
    field_name,
    field_value,
    bidsname,
    source_name,
    target_name,
    target_path,
):
    return "\n".join(
        [
            "BIDS naming collision detected while renaming dcm2niix outputs.",
            f"Scan ID: {scan_id}",
            f"Mapping field: {field_name}",
            f"Mapping value: {field_value}",
            f"Resolved BIDS name: {bidsname}",
            f"dcm2niix output file: {source_name}",
            f"Attempted renamed file: {target_name}",
            f"Existing target path: {target_path}",
            "",
            "The conversion is stopping to avoid overwriting data.",
            "Correct this by editing the project BIDS map so each converted output has a unique BIDS suffix.",
            "Common fixes:",
            "- If two XNAT scans map to the same BIDS suffix, give them explicit run labels such as run-01 and run-02.",
            "- If the DICOM series is multi-echo, make sure the BIDS name can accept echo labels such as echo-1, echo-2, echo-3.",
            "- If a phase image is present, make sure it can be represented with part-phase or map it to a separate suffix.",
            "",
            "Example BIDS map entry to review:",
            f'{{"xnat_field": "{field_value}", "bidsname": "{bidsname}"}}',
        ]
    )


def rename_echo_file(filename):
    echo_match = re.search(r"_e(\d+)(?=(_|\.|$))", filename)
    echo_entity = f"echo-{echo_match.group(1)}" if echo_match else None

    filename = re.sub(r"_e\d+(?=(_|\.|$))", "", filename)

    has_phase = re.search(r"_ph(?=(_|\.|$))", filename) is not None
    filename = re.sub(r"_ph(?=(_|\.|$))", "", filename)

    if echo_entity:
        run_matches = list(re.finditer(r"_run-\d+", filename))
        if f"_{echo_entity}" in _split_bids_extension(filename)[0]:
            pass
        elif run_matches:
            insert_pos = run_matches[-1].end()
            filename = f"{filename[:insert_pos]}_{echo_entity}{filename[insert_pos:]}"
        else:
            filename = _insert_entity_before_suffix(filename, echo_entity)

    if has_phase and "_part-phase" not in _split_bids_extension(filename)[0]:
        filename = _insert_entity_before_suffix(filename, "part-phase")

    return filename
