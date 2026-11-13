"""BIDS arterial spin labelling (perf/) support for dcm2niix output.

A scan mapped to an ``asl`` BIDS name is converted by dcm2niix as usual, then
``process_asl_outputs`` turns what dcm2niix wrote into valid BIDS perf files:

* GE 3D PCASL series hold two volumes: the perfusion-weighted image (deltaM, ImageType
  ``DERIVED\\PRIMARY\\ASL\\PERFUSION``) and the proton-density reference (ImageType
  ``ORIGINAL\\PRIMARY\\ASL``). dcm2niix writes them as two files, the second with an
  ``a`` appended. They become ``*_asl`` (deltaM) and ``*_m0scan`` (M0).
* ``*_aslcontext.tsv`` is written for the ``*_asl`` file.
* Sidecar fields BIDS requires are filled where the DICOM supports them, and the BIDS
  map entry's ``sidecar`` object can add or override any field.

BIDS perf file names only allow the sub, ses, acq, rec, dir, run, part and echo
entities; ``normalize_perf_bidsname`` drops any other (for example ``task-``).
"""

import gzip
import json
import os
import struct
import zlib

PERF_SUFFIXES = ("asl", "m0scan")
PERF_ALLOWED_ENTITIES = ("sub", "ses", "acq", "rec", "dir", "run", "part", "echo")
ASL_REQUIRED_FIELDS = (
    "ArterialSpinLabelingType",
    "PostLabelingDelay",
    "BackgroundSuppression",
    "M0Type",
    "TotalAcquiredPairs",
    "RepetitionTimePreparation",
)
CASL_REQUIRED_FIELDS = ("LabelingDuration",)
M0SCAN_REQUIRED_FIELDS = ("RepetitionTimePreparation", "IntendedFor")
ASLCONTEXT_VOLUME_TYPES = ("control", "label", "m0scan", "deltam", "cbf", "noRF")
NIFTI_EXTENSIONS = (".nii.gz", ".nii")


def perf_suffix(bidsname):
    """The BIDS perf suffix of a name ("asl" or "m0scan", whatever its case in the name), else None."""
    suffix = bidsname.rsplit("_", 1)[-1].lower()
    return suffix if suffix in PERF_SUFFIXES else None


def normalize_perf_bidsname(bidsname):
    """Make a perf name valid: drop entities BIDS does not allow and spell the suffix as BIDS does.

    Returns (new_name, changes), where changes describes each change for a log message. Names
    that are not perf names come back unchanged.
    """
    suffix = perf_suffix(bidsname)
    if not suffix:
        return bidsname, []
    parts = bidsname.split("_")
    kept, changes = [], []
    for part in parts[:-1]:
        key = part.split("-", 1)[0]
        if "-" in part and key not in PERF_ALLOWED_ENTITIES:
            changes.append(f"removed {part}, which BIDS does not allow in perf names")
        else:
            kept.append(part)
    if parts[-1] != suffix:
        changes.append(f"suffix {parts[-1]} written as {suffix}")
    return "_".join(kept + [suffix]), changes


def normalize_perf_map_names(bidsnamemap, regex_patterns, log=print):
    """Normalize the perf names in a BIDS map before run numbers are assigned.

    Doing it here, not per scan, means two entries that become the same name (for example
    task-rest_asl and task-motor_asl) are numbered as runs instead of overwriting each other.
    Returns (bidsnamemap, regex_patterns) as new objects; the inputs are not changed.
    """
    new_namemap = {}
    for field_value, bidsname in bidsnamemap.items():
        new_name, changes = normalize_perf_bidsname(bidsname)
        if changes:
            log(f"WARNING: BIDS map entry {field_value} -> {bidsname} is used as {new_name}: {'; '.join(changes)}.")
        new_namemap[field_value] = new_name
    new_patterns = []
    for entry in regex_patterns:
        if entry.get("suffix"):
            new_name, changes = normalize_perf_bidsname(entry["suffix"])
            if changes:
                log(f"WARNING: BIDS map pattern {entry['pattern']} -> {entry['suffix']} is used as {new_name}: {'; '.join(changes)}.")
                entry = dict(entry, suffix=new_name)
        new_patterns.append(entry)
    return new_namemap, new_patterns


def replace_suffix(bidsname, new_suffix):
    """The name with its last _-separated part (the BIDS suffix) replaced."""
    stem, _, _ = bidsname.rpartition("_")
    return f"{stem}_{new_suffix}" if stem else new_suffix


def aslcontext_name(asl_name):
    """The *_aslcontext.tsv name for an *_asl name. BIDS does not allow echo- or part- on it."""
    parts = asl_name.split("_")[:-1]
    kept = [part for part in parts if part.split("-", 1)[0] not in ("echo", "part")]
    return "_".join(kept + ["aslcontext"]) + ".tsv"


def nifti_extension(file_name):
    return ".nii.gz" if file_name.endswith(".nii.gz") else ".nii"


def is_asl_dicom(image_type):
    """True when a DICOM ImageType says the series is an ASL acquisition."""
    return any(str(value).strip().upper() == "ASL" for value in (image_type or []))


def classify_asl_output(sidecar):
    """Name the volume type of one dcm2niix ASL output from its sidecar.

    Returns "deltam", "cbf", "m0scan" or None when the output cannot be identified.
    """
    image_type = [str(value).strip().upper() for value in sidecar.get("ImageType", [])]
    if "CBF" in image_type:
        return "cbf"
    if "PERFUSION" in image_type:
        return "deltam"
    manufacturer = str(sidecar.get("Manufacturer", "")).upper()
    if manufacturer.startswith("GE") and image_type[:1] == ["ORIGINAL"] and "ASL" in image_type:
        return "m0scan"
    return None


def nifti_volume_count(path):
    """Number of volumes in a NIfTI-1 file (.nii or .nii.gz), read from its header."""
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rb") as handle:
            header = handle.read(348)
    except (EOFError, zlib.error, gzip.BadGzipFile) as error:
        raise ValueError(f"cannot read the NIfTI header of {path}: {error}") from error
    if len(header) < 348:
        raise ValueError(f"{path} is too short to be a NIfTI-1 file")
    for endian in ("<", ">"):
        if struct.unpack(endian + "i", header[:4])[0] == 348:
            dims = struct.unpack(endian + "8h", header[40:56])
            return dims[4] if dims[0] >= 4 and dims[4] > 0 else 1
    raise ValueError(f"{path} does not have a NIfTI-1 header")


def aslcontext_rows(volume_count, pattern):
    """Expand a volume-type pattern to one row per volume.

    A pattern as long as the file is used as is; a shorter one must divide the volume count
    and is repeated (for example ["control", "label"] for a label/control time series).
    """
    if not isinstance(pattern, (list, tuple)) or not all(isinstance(value, str) for value in pattern):
        raise ValueError(f"an aslcontext pattern must be a list of volume types, not {pattern!r}")
    pattern = list(pattern)
    if not pattern:
        raise ValueError("an aslcontext pattern needs at least one volume type")
    unknown = [value for value in pattern if value not in ASLCONTEXT_VOLUME_TYPES]
    if unknown:
        raise ValueError(
            "aslcontext volume types %s are not BIDS volume types %s" % (unknown, list(ASLCONTEXT_VOLUME_TYPES))
        )
    if volume_count % len(pattern) != 0:
        raise ValueError(
            "the aslcontext pattern has %d entries, which does not divide the %d volumes"
            % (len(pattern), volume_count)
        )
    return pattern * (volume_count // len(pattern))


def bids_uri(bidsname_with_extension, datatype):
    """BIDS URI of a file in this dataset, e.g. bids::sub-01/ses-01/perf/sub-01_ses-01_asl.nii.gz."""
    entities = dict(
        part.split("-", 1) for part in bidsname_with_extension.split("_")[:-1] if "-" in part
    )
    if "sub" not in entities:
        raise ValueError(f"{bidsname_with_extension} has no sub- entity, so it has no BIDS URI")
    path = [f"sub-{entities['sub']}"]
    if "ses" in entities:
        path.append(f"ses-{entities['ses']}")
    path += [datatype, bidsname_with_extension]
    return "bids::" + "/".join(path)


def m0scan_skip_reason(image_type, map_entry):
    """Why a series mapped to *_m0scan should not be converted, or None to convert it.

    A series whose DICOM ImageType says ASL is taken as an M0. Other vendors' separate M0
    series may not say so, so one without ASL is converted only when its BIDS map entry gives
    the IntendedFor that BIDS requires anyway; that is what tells a real M0 from, for example,
    a localizer mapped to m0scan by mistake.
    """
    if is_asl_dicom(image_type):
        return None
    sidecar = (map_entry or {}).get("sidecar")
    if isinstance(sidecar, dict) and sidecar.get("IntendedFor"):
        return None
    return (
        "its DICOM ImageType (%s) does not say ASL, and its BIDS map entry gives no \"sidecar\": {\"IntendedFor\": [...]}. "
        "If it is an M0 scan, add IntendedFor naming the ASL file it belongs to; a GE 3D PCASL series contains its own "
        "M0 volume, so map only the ASL series." % "\\".join(str(value) for value in (image_type or []))
    )


def missing_required_fields(sidecar, suffix):
    """The BIDS-required sidecar fields for an *_asl or *_m0scan file that the sidecar lacks."""
    if suffix == "asl":
        required = list(ASL_REQUIRED_FIELDS)
        if sidecar.get("ArterialSpinLabelingType") in ("CASL", "PCASL"):
            required += list(CASL_REQUIRED_FIELDS)
    else:
        required = list(M0SCAN_REQUIRED_FIELDS)
    return [field for field in required if field not in sidecar]


def _nifti_for(directory, stem):
    for extension in NIFTI_EXTENSIONS:
        if os.path.exists(os.path.join(directory, stem + extension)):
            return stem + extension
    return None


def _read_json(path):
    with open(path) as handle:
        return json.load(handle)


def _write_json(path, sidecar):
    with open(path, "w") as handle:
        json.dump(sidecar, handle, indent=4)
        handle.write("\n")


def _rename(directory, source, target):
    if source == target:
        return
    target_path = os.path.join(directory, target)
    if os.path.exists(target_path):
        raise FileExistsError(f"refusing to overwrite {target_path} while renaming {source}")
    os.rename(os.path.join(directory, source), target_path)


def _derive_repetition_time_preparation(sidecar, name, log):
    if "RepetitionTimePreparation" not in sidecar and "RepetitionTime" in sidecar:
        sidecar["RepetitionTimePreparation"] = sidecar["RepetitionTime"]
        log(f"{name}: RepetitionTimePreparation set from RepetitionTime ({sidecar['RepetitionTime']})")


def apply_sidecar_overrides(sidecar, overrides, name, log):
    """Set the fields of a BIDS map entry's sidecar object on a sidecar; they win over derived values."""
    if not overrides:
        return
    if not isinstance(overrides, dict):
        raise ValueError(f"the BIDS map entry's \"sidecar\" must be a JSON object, not {type(overrides).__name__}")
    for key, value in overrides.items():
        sidecar[key] = value
    log(f"{name}: applied BIDS map sidecar fields {sorted(overrides)}")


def process_asl_outputs(directory, bidsname, map_entry=None, log=print):
    """Rename and complete dcm2niix's output for a scan mapped to ``*_asl``.

    ``directory`` holds dcm2niix's .json and .nii.gz files for the scan; ``bidsname`` is the
    BIDS name it was given (``-f``), ending in ``_asl``. Returns the final file names, or None
    when the outputs cannot be identified (the caller then skips the scan); every reason is
    logged.
    """
    map_entry = map_entry or {}
    stems = sorted(name[: -len(".json")] for name in os.listdir(directory) if name.endswith(".json"))
    outputs = []
    for stem in stems:
        nifti = _nifti_for(directory, stem)
        if nifti is None:
            log(f"WARNING: {stem}.json has no NIfTI file next to it; ignoring it.")
            continue
        sidecar = _read_json(os.path.join(directory, stem + ".json"))
        outputs.append({"stem": stem, "nifti": nifti, "sidecar": sidecar, "role": classify_asl_output(sidecar)})

    if not outputs:
        log(f"No dcm2niix output found for {bidsname}.")
        return None

    if len(outputs) == 1:
        asl, m0 = outputs[0], None
        if asl["role"] == "m0scan" and not map_entry.get("aslcontext"):
            # A lone GE ORIGINAL ASL image is normally an M0; an "aslcontext" in the map says it is
            # a label/control series instead
            log(
                f"The only dcm2niix output for {bidsname} looks like an M0 image (ImageType {asl['sidecar'].get('ImageType')}). "
                "Map this series to an m0scan BIDS name, or give its volume types in an \"aslcontext\" list if it is a "
                "label/control series. Skipping."
            )
            return None
    else:
        by_role = {}
        for output in outputs:
            by_role.setdefault(output["role"], []).append(output)
        asl_candidates = by_role.get("deltam", []) + by_role.get("cbf", [])
        m0_candidates = by_role.get("m0scan", [])
        unidentified = by_role.get(None, [])
        if len(asl_candidates) != 1 or len(m0_candidates) > 1 or unidentified:
            log(
                f"Could not tell the {len(outputs)} dcm2niix outputs for {bidsname} apart "
                f"(ImageType {[o['sidecar'].get('ImageType') for o in outputs]}). Only a GE-style pair of one "
                "perfusion (deltaM or CBF) image and one M0 image is recognised. Skipping this scan."
            )
            return None
        asl, m0 = asl_candidates[0], (m0_candidates[0] if m0_candidates else None)

    extension = nifti_extension(asl["nifti"])
    asl_name = bidsname
    m0_name = replace_suffix(bidsname, "m0scan") if m0 else None
    asl_volumes = nifti_volume_count(os.path.join(directory, asl["nifti"]))

    # aslcontext: from the BIDS map when given, otherwise from what the image is
    if map_entry.get("aslcontext"):
        rows = aslcontext_rows(asl_volumes, map_entry["aslcontext"])
        log(f"{asl_name}: aslcontext from the BIDS map entry: {rows}")
    elif asl["role"] in ("deltam", "cbf"):
        rows = [asl["role"]] * asl_volumes
        log(f"{asl_name}: aslcontext from ImageType: {rows}")
    else:
        rows = None
        log(
            f"WARNING: {asl_name}: cannot tell which volumes are control, label or M0 ({asl_volumes} volumes, "
            f"ImageType {asl['sidecar'].get('ImageType')}). BIDS requires *_aslcontext.tsv; add an \"aslcontext\" "
            "list to this BIDS map entry, e.g. [\"control\", \"label\"]."
        )

    renames = [(asl["stem"] + ".json", asl_name + ".json"), (asl["nifti"], asl_name + extension)]
    if m0:
        m0_extension = nifti_extension(m0["nifti"])
        renames += [(m0["stem"] + ".json", m0_name + ".json"), (m0["nifti"], m0_name + m0_extension)]
    # through temporary names, because dcm2niix may have given the M0 the name the ASL file gets
    for source, target in renames:
        _rename(directory, source, target + ".renaming")
    for source, target in renames:
        _rename(directory, target + ".renaming", target)
        if source != target:
            log(f"rename {source} -> {target}")

    produced = [asl_name + ".json", asl_name + extension]
    if rows is not None:
        context_name = aslcontext_name(asl_name)
        with open(os.path.join(directory, context_name), "w") as handle:
            handle.write("volume_type\n" + "".join(row + "\n" for row in rows))
        produced.append(context_name)

    # ASL sidecar
    asl_sidecar = asl["sidecar"]
    if m0 and "M0Type" not in asl_sidecar:
        asl_sidecar["M0Type"] = "Separate"
        log(f"{asl_name}: M0Type Separate (M0 written to {m0_name})")
    _derive_repetition_time_preparation(asl_sidecar, asl_name, log)
    manufacturer = str(asl_sidecar.get("Manufacturer", "")).upper()
    if (
        "TotalAcquiredPairs" not in asl_sidecar
        and manufacturer.startswith("GE")
        and asl["role"] == "deltam"
        and asl_sidecar.get("NumberOfAverages")
    ):
        asl_sidecar["TotalAcquiredPairs"] = int(asl_sidecar["NumberOfAverages"])
        log(f"{asl_name}: TotalAcquiredPairs set from GE NumberOfAverages (NEX {asl_sidecar['NumberOfAverages']})")
    apply_sidecar_overrides(asl_sidecar, map_entry.get("sidecar"), asl_name, log)
    _write_json(os.path.join(directory, asl_name + ".json"), asl_sidecar)
    missing = missing_required_fields(asl_sidecar, "asl")
    if missing:
        log(
            f"WARNING: {asl_name}.json lacks BIDS-required ASL fields {missing}. The DICOM does not record them; "
            "add them to this BIDS map entry's \"sidecar\" object, e.g. \"sidecar\": {\"BackgroundSuppression\": true}."
        )

    # M0 sidecar
    if m0:
        m0_sidecar = m0["sidecar"]
        m0_sidecar["IntendedFor"] = [bids_uri(asl_name + extension, "perf")]
        log(f"{m0_name}: IntendedFor {m0_sidecar['IntendedFor']}")
        _derive_repetition_time_preparation(m0_sidecar, m0_name, log)
        asl_type = asl_sidecar.get("ArterialSpinLabelingType")
        if asl_type and m0_sidecar.get("ArterialSpinLabelingType") not in (None, asl_type):
            log(
                f"{m0_name}: ArterialSpinLabelingType {m0_sidecar['ArterialSpinLabelingType']} -> {asl_type}, "
                "to match the ASL image from the same acquisition"
            )
            m0_sidecar["ArterialSpinLabelingType"] = asl_type
        apply_sidecar_overrides(m0_sidecar, map_entry.get("m0scan_sidecar"), m0_name, log)
        _write_json(os.path.join(directory, m0_name + ".json"), m0_sidecar)
        produced += [m0_name + ".json", m0_name + m0_extension]
        missing = missing_required_fields(m0_sidecar, "m0scan")
        if missing:
            log(
                f"WARNING: {m0_name}.json lacks BIDS-required m0scan fields {missing}; add them to this BIDS map "
                "entry's \"m0scan_sidecar\" object."
            )

    return produced


def process_standalone_m0scan(directory, bidsname, map_entry=None, log=print):
    """Complete the sidecar of a separate M0 series mapped to ``*_m0scan``.

    BIDS requires IntendedFor on an m0scan; this series alone cannot say which ASL run it
    belongs to, so it comes from the BIDS map entry's ``sidecar`` (warned about when missing).
    Returns the file names, or None when dcm2niix wrote more than one image (the caller then
    skips the scan): a GE 3D PCASL series mapped to m0scan, for example, holds a deltaM too.
    """
    map_entry = map_entry or {}
    names = sorted(name for name in os.listdir(directory) if name.endswith(".json"))
    if len(names) != 1:
        log(
            f"dcm2niix wrote {len(names)} images for {bidsname} ({names}); an m0scan is one image. "
            "If this is a GE 3D PCASL series, map it to an asl BIDS name; its M0 is written as *_m0scan. Skipping."
        )
        return None
    name = names[0]
    stem = name[: -len(".json")]
    if stem != bidsname:
        # dcm2niix adds a postfix to some single images (for example _e2 when EchoNumbers is 2);
        # the one image of an m0scan series takes the BIDS name itself
        nifti = _nifti_for(directory, stem)
        _rename(directory, name, bidsname + ".json")
        if nifti:
            _rename(directory, nifti, bidsname + nifti[len(stem):])
        log(f"Renamed dcm2niix output {stem} to {bidsname}: an m0scan series is one image under its BIDS name.")
        name = bidsname + ".json"
    path = os.path.join(directory, name)
    sidecar = _read_json(path)
    _derive_repetition_time_preparation(sidecar, name, log)
    apply_sidecar_overrides(sidecar, map_entry.get("sidecar"), name, log)
    _write_json(path, sidecar)
    missing = missing_required_fields(sidecar, "m0scan")
    if missing:
        log(
            f"WARNING: {name} lacks BIDS-required m0scan fields {missing}. Set them in this BIDS map entry's "
            "\"sidecar\" object, e.g. \"sidecar\": {\"IntendedFor\": [\"bids::sub-01/ses-01/perf/sub-01_ses-01_asl.nii.gz\"]}."
        )
    nifti = _nifti_for(directory, name[: -len(".json")])
    return [name] + ([nifti] if nifti else [])
