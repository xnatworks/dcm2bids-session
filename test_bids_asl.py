import gzip
import json
import os
import shutil
import struct
import tempfile
import unittest

import xnatbidsfns
from bids_asl import (
    aslcontext_name,
    aslcontext_rows,
    bids_uri,
    classify_asl_output,
    is_asl_dicom,
    m0scan_skip_reason,
    missing_required_fields,
    nifti_volume_count,
    normalize_perf_bidsname,
    normalize_perf_map_names,
    perf_suffix,
    process_asl_outputs,
    process_standalone_m0scan,
)
from bids_naming import add_or_replace_run_entity, duplicate_bids_suffix_counts

# The sidecar fields dcm2niix (v1.0.20250506 and v1.0.20261029) writes for a GE 3D PCASL series
# (ASL_3D_PCASL): one perfusion-weighted (deltaM) and one M0 output. The timing values and the
# number of averages are invented round numbers, not any site's protocol.
GE_DELTAM = {
    "Manufacturer": "GE",
    "ImageType": ["DERIVED", "PRIMARY", "ASL", "PERFUSION", "ASL", "MAGNITUDE"],
    "NumberOfAverages": 2,
    "RepetitionTime": 5.0,
    "InversionTime": 2.0,
    "ArterialSpinLabelingType": "PCASL",
    "LabelingDuration": 1.5,
    "PostLabelingDelay": 2.0,
}
GE_M0 = {
    "Manufacturer": "GE",
    "ImageType": ["ORIGINAL", "PRIMARY", "ASL", "MAGNITUDE"],
    "RepetitionTime": 5.0,
    "ArterialSpinLabelingType": "CASL",
    "LabelingDuration": 1.5,
}
NAME = "sub-01_ses-01_run-01_asl"


def write_nifti(path, dims, big_endian=False):
    """A minimal NIfTI-1 file: a valid header and a few bytes of data."""
    endian = ">" if big_endian else "<"
    header = bytearray(352)
    struct.pack_into(endian + "i", header, 0, 348)
    struct.pack_into(endian + "8h", header, 40, *(list(dims) + [1] * (8 - len(dims))))
    header[344:348] = b"n+1\x00"
    data = bytes(header) + b"\x00" * 16
    if path.endswith(".gz"):
        with gzip.open(path, "wb") as handle:
            handle.write(data)
    else:
        with open(path, "wb") as handle:
            handle.write(data)


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.messages = []

    def tearDown(self):
        shutil.rmtree(self.dir)

    def log(self, message):
        self.messages.append(message)

    def output(self, stem, sidecar, dims=(3, 128, 128, 36)):
        with open(os.path.join(self.dir, stem + ".json"), "w") as handle:
            json.dump(sidecar, handle)
        write_nifti(os.path.join(self.dir, stem + ".nii.gz"), dims)

    def read(self, name):
        with open(os.path.join(self.dir, name)) as handle:
            return json.load(handle) if name.endswith(".json") else handle.read()

    def warnings(self):
        return [m for m in self.messages if m.startswith("WARNING")]


class TestPerfFolder(unittest.TestCase):
    def test_asl_and_m0scan_go_to_perf(self):
        self.assertEqual(xnatbidsfns.getSubdir("asl"), "perf")
        self.assertEqual(xnatbidsfns.getSubdir("m0scan"), "perf")

    def test_other_folders_unchanged(self):
        self.assertEqual(xnatbidsfns.getSubdir("T1w"), "anat")
        self.assertEqual(xnatbidsfns.getSubdir("bold"), "func")
        self.assertIsNone(xnatbidsfns.getSubdir("aslcontext"))

    def test_perf_suffix(self):
        self.assertEqual(perf_suffix(NAME), "asl")
        self.assertEqual(perf_suffix("sub-01_m0scan"), "m0scan")
        self.assertEqual(perf_suffix("sub-01_M0Scan"), "m0scan")
        self.assertIsNone(perf_suffix("sub-01_task-rest_bold"))


class TestPerfNames(unittest.TestCase):
    def test_task_is_removed_from_asl(self):
        name, changes = normalize_perf_bidsname("sub-01_ses-01_task-rest_run-01_asl")
        self.assertEqual(name, "sub-01_ses-01_run-01_asl")
        self.assertEqual(len(changes), 1)
        self.assertIn("task-rest", changes[0])

    def test_task_is_removed_from_m0scan(self):
        self.assertEqual(normalize_perf_bidsname("sub-01_task-rest_run-01_m0scan")[0], "sub-01_run-01_m0scan")

    def test_suffix_case_is_corrected(self):
        name, changes = normalize_perf_bidsname("run-01_ASL")
        self.assertEqual(name, "run-01_asl")
        self.assertIn("ASL", changes[0])
        self.assertEqual(normalize_perf_bidsname("M0Scan")[0], "m0scan")

    def test_allowed_entities_are_kept(self):
        name = "sub-01_ses-02_acq-pcasl_rec-x_dir-AP_run-01_part-mag_echo-1_asl"
        self.assertEqual(normalize_perf_bidsname(name), (name, []))

    def test_non_perf_names_are_untouched(self):
        name = "sub-01_task-rest_run-01_bold"
        self.assertEqual(normalize_perf_bidsname(name), (name, []))

    def test_aslcontext_name_drops_echo_and_part(self):
        self.assertEqual(aslcontext_name("sub-01_acq-x_run-01_part-mag_echo-1_asl"), "sub-01_acq-x_run-01_aslcontext.tsv")
        self.assertEqual(aslcontext_name(NAME), "sub-01_ses-01_run-01_aslcontext.tsv")


class TestPerfMapNames(unittest.TestCase):
    def setUp(self):
        self.messages = []

    def test_entries_that_become_equal_are_numbered_as_runs(self):
        # Two series whose names differ only by task-: without normalizing first, both scans
        # would be written as sub-01_asl and one would overwrite the other.
        field_values = ["ASL_rest", "ASL_motor"]
        namemap = {"asl_rest": "task-rest_asl", "asl_motor": "task-motor_asl"}
        namemap, patterns = normalize_perf_map_names(namemap, [], self.messages.append)
        self.assertEqual(namemap, {"asl_rest": "asl", "asl_motor": "asl"})
        multiples = duplicate_bids_suffix_counts(field_values, namemap, patterns)
        names = []
        for value in field_values:
            match = namemap[value.lower()]
            names.append(add_or_replace_run_entity(match, multiples[match]))
            multiples[match] -= 1
        self.assertEqual(sorted(names), ["run-01_asl", "run-02_asl"])
        self.assertEqual(len(self.messages), 2)

    def test_regex_suffixes_are_normalized_without_changing_the_input(self):
        patterns = [{"pattern": "ASL_.*", "suffix": "task-rest_asl", "sidecar": {"BackgroundSuppression": True}},
                    {"pattern": "LOC.*"}]
        _, new_patterns = normalize_perf_map_names({}, patterns, self.messages.append)
        self.assertEqual(new_patterns[0]["suffix"], "asl")
        self.assertEqual(new_patterns[0]["sidecar"], {"BackgroundSuppression": True})
        self.assertEqual(new_patterns[1], {"pattern": "LOC.*"})
        self.assertEqual(patterns[0]["suffix"], "task-rest_asl")

    def test_other_entries_are_unchanged_and_not_logged(self):
        namemap = {"t1": "T1w", "rest": "task-rest_bold"}
        self.assertEqual(normalize_perf_map_names(namemap, [], self.messages.append)[0], namemap)
        self.assertEqual(self.messages, [])


class TestClassify(unittest.TestCase):
    def test_ge_perfusion_is_deltam(self):
        self.assertEqual(classify_asl_output(GE_DELTAM), "deltam")

    def test_ge_original_asl_is_m0(self):
        self.assertEqual(classify_asl_output(GE_M0), "m0scan")

    def test_cbf(self):
        self.assertEqual(classify_asl_output({"ImageType": ["DERIVED", "SECONDARY", "CBF"]}), "cbf")

    def test_cbf_wins_over_perfusion(self):
        self.assertEqual(classify_asl_output({"ImageType": ["DERIVED", "PRIMARY", "PERFUSION", "CBF"]}), "cbf")

    def test_original_asl_from_another_vendor_is_not_assumed_m0(self):
        self.assertIsNone(classify_asl_output(dict(GE_M0, Manufacturer="Siemens")))

    def test_m0scan_skip_reason(self):
        self.assertIsNone(m0scan_skip_reason(["ORIGINAL", "PRIMARY", "ASL"], {}))
        # an ASL_LOCALIZER series: a GE BRAVO T1 localizer mapped to m0scan
        reason = m0scan_skip_reason(["ORIGINAL", "PRIMARY", "OTHER"], {"bidsname": "m0scan"})
        self.assertIn("IntendedFor", reason)
        self.assertIn("ORIGINAL\\PRIMARY\\OTHER", reason)
        # another vendor's M0 without ASL in ImageType, which the map vouches for
        intended = {"sidecar": {"IntendedFor": ["bids::sub-01/perf/sub-01_asl.nii.gz"]}}
        self.assertIsNone(m0scan_skip_reason(["ORIGINAL", "PRIMARY", "M_FFE", "M", "FFE"], intended))
        self.assertIsNotNone(m0scan_skip_reason(["ORIGINAL", "PRIMARY", "M"], {"sidecar": {"IntendedFor": []}}))
        self.assertIsNotNone(m0scan_skip_reason([], {"sidecar": "IntendedFor"}))

    def test_is_asl_dicom(self):
        self.assertTrue(is_asl_dicom(["ORIGINAL", "PRIMARY", "ASL"]))
        # an ASL_LOCALIZER series: a GE BRAVO T1 localizer, not an M0
        self.assertFalse(is_asl_dicom(["ORIGINAL", "PRIMARY", "OTHER"]))
        self.assertFalse(is_asl_dicom([]))


class TestNiftiVolumes(TempDirTest):
    def test_3d_is_one_volume(self):
        path = os.path.join(self.dir, "a.nii.gz")
        write_nifti(path, (3, 128, 128, 36))
        self.assertEqual(nifti_volume_count(path), 1)

    def test_4d_gz(self):
        path = os.path.join(self.dir, "a.nii.gz")
        write_nifti(path, (4, 64, 64, 20, 80))
        self.assertEqual(nifti_volume_count(path), 80)

    def test_4d_uncompressed_big_endian(self):
        path = os.path.join(self.dir, "a.nii")
        write_nifti(path, (4, 64, 64, 20, 7), big_endian=True)
        self.assertEqual(nifti_volume_count(path), 7)

    def test_truncated_gz(self):
        path = os.path.join(self.dir, "a.nii.gz")
        write_nifti(path, (4, 64, 64, 20, 80))
        with open(path, "rb") as handle:
            data = handle.read()
        with open(path, "wb") as handle:
            handle.write(data[:20])
        with self.assertRaises(ValueError):
            nifti_volume_count(path)

    def test_not_nifti(self):
        path = os.path.join(self.dir, "a.nii")
        with open(path, "wb") as handle:
            handle.write(b"x" * 400)
        with self.assertRaises(ValueError):
            nifti_volume_count(path)


class TestAslContextRows(unittest.TestCase):
    def test_repeated_pattern(self):
        self.assertEqual(aslcontext_rows(4, ["control", "label"]), ["control", "label", "control", "label"])

    def test_full_length_pattern(self):
        self.assertEqual(aslcontext_rows(2, ["deltam", "m0scan"]), ["deltam", "m0scan"])

    def test_pattern_must_divide_volumes(self):
        with self.assertRaises(ValueError):
            aslcontext_rows(5, ["control", "label"])

    def test_unknown_volume_type(self):
        with self.assertRaises(ValueError):
            aslcontext_rows(2, ["ctrl", "label"])

    def test_empty_pattern(self):
        with self.assertRaises(ValueError):
            aslcontext_rows(2, [])

    def test_pattern_that_is_not_a_list(self):
        for pattern in (2, True, "control", {"control": 1}, [1, 2]):
            with self.assertRaises(ValueError):
                aslcontext_rows(2, pattern)


class TestBidsUri(unittest.TestCase):
    def test_with_session(self):
        self.assertEqual(
            bids_uri(NAME + ".nii.gz", "perf"),
            "bids::sub-01/ses-01/perf/sub-01_ses-01_run-01_asl.nii.gz",
        )

    def test_without_session(self):
        self.assertEqual(bids_uri("sub-01_asl.nii.gz", "perf"), "bids::sub-01/perf/sub-01_asl.nii.gz")

    def test_without_subject(self):
        with self.assertRaises(ValueError):
            bids_uri("run-01_asl.nii.gz", "perf")


class TestRequiredFields(unittest.TestCase):
    def test_pcasl_needs_labeling_duration(self):
        missing = missing_required_fields({"ArterialSpinLabelingType": "PCASL"}, "asl")
        self.assertIn("LabelingDuration", missing)
        self.assertIn("BackgroundSuppression", missing)

    def test_pasl_does_not_need_labeling_duration(self):
        self.assertNotIn("LabelingDuration", missing_required_fields({"ArterialSpinLabelingType": "PASL"}, "asl"))

    def test_m0scan(self):
        self.assertEqual(missing_required_fields({}, "m0scan"), ["RepetitionTimePreparation", "IntendedFor"])


class TestGePcaslPair(TempDirTest):
    """A GE 3D PCASL session: dcm2niix writes <name> (deltaM) and <name>a (M0) for one GE 3D PCASL series."""

    def setUp(self):
        super().setUp()
        self.output(NAME, GE_DELTAM)
        self.output(NAME + "a", GE_M0)

    def test_files_are_named_for_bids_perf(self):
        produced = process_asl_outputs(self.dir, NAME, {}, self.log)
        expected = [
            NAME + ".json",
            NAME + ".nii.gz",
            "sub-01_ses-01_run-01_aslcontext.tsv",
            "sub-01_ses-01_run-01_m0scan.json",
            "sub-01_ses-01_run-01_m0scan.nii.gz",
        ]
        self.assertEqual(produced, expected)
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(expected))

    def test_aslcontext_is_one_deltam_volume(self):
        process_asl_outputs(self.dir, NAME, {}, self.log)
        self.assertEqual(self.read("sub-01_ses-01_run-01_aslcontext.tsv"), "volume_type\ndeltam\n")

    def test_asl_sidecar_is_completed_from_the_dicom(self):
        process_asl_outputs(self.dir, NAME, {}, self.log)
        sidecar = self.read(NAME + ".json")
        self.assertEqual(sidecar["M0Type"], "Separate")
        self.assertEqual(sidecar["TotalAcquiredPairs"], 2)
        self.assertEqual(sidecar["RepetitionTimePreparation"], 5.0)
        # what dcm2niix wrote is kept
        self.assertEqual(sidecar["ArterialSpinLabelingType"], "PCASL")
        self.assertEqual(sidecar["PostLabelingDelay"], 2.0)

    def test_background_suppression_is_not_guessed(self):
        process_asl_outputs(self.dir, NAME, {}, self.log)
        self.assertNotIn("BackgroundSuppression", self.read(NAME + ".json"))
        self.assertTrue(any("BackgroundSuppression" in w for w in self.warnings()))

    def test_map_entry_sidecar_completes_and_overrides(self):
        process_asl_outputs(self.dir, NAME, {"sidecar": {"BackgroundSuppression": True, "TotalAcquiredPairs": 6}}, self.log)
        sidecar = self.read(NAME + ".json")
        self.assertIs(sidecar["BackgroundSuppression"], True)
        self.assertEqual(sidecar["TotalAcquiredPairs"], 6)
        self.assertEqual(self.warnings(), [])

    def test_m0_sidecar(self):
        process_asl_outputs(self.dir, NAME, {}, self.log)
        sidecar = self.read("sub-01_ses-01_run-01_m0scan.json")
        self.assertEqual(
            sidecar["IntendedFor"],
            ["bids::sub-01/ses-01/perf/sub-01_ses-01_run-01_asl.nii.gz"],
        )
        self.assertEqual(sidecar["RepetitionTimePreparation"], 5.0)
        self.assertEqual(sidecar["ArterialSpinLabelingType"], "PCASL")
        self.assertNotIn("M0Type", sidecar)

    def test_map_entry_m0scan_sidecar_overrides_the_m0(self):
        process_asl_outputs(self.dir, NAME, {"m0scan_sidecar": {"RepetitionTimePreparation": 2.0}}, self.log)
        self.assertEqual(self.read("sub-01_ses-01_run-01_m0scan.json")["RepetitionTimePreparation"], 2.0)
        self.assertEqual(self.read(NAME + ".json")["RepetitionTimePreparation"], 5.0)

    def test_asl_sidecar_does_not_reach_the_m0(self):
        process_asl_outputs(self.dir, NAME, {"sidecar": {"BackgroundSuppression": True}}, self.log)
        self.assertNotIn("BackgroundSuppression", self.read("sub-01_ses-01_run-01_m0scan.json"))

    def test_intended_for_is_logged(self):
        process_asl_outputs(self.dir, NAME, {}, self.log)
        self.assertTrue(any("IntendedFor" in m and "m0scan" in m for m in self.messages))

    def test_bad_aslcontext_entry_raises(self):
        with self.assertRaises(ValueError):
            process_asl_outputs(self.dir, NAME, {"aslcontext": 2}, self.log)

    def test_map_aslcontext_overrides_image_type(self):
        process_asl_outputs(self.dir, NAME, {"aslcontext": ["cbf"]}, self.log)
        self.assertEqual(self.read("sub-01_ses-01_run-01_aslcontext.tsv"), "volume_type\ncbf\n")

    def test_bad_sidecar_entry_raises(self):
        with self.assertRaises(ValueError):
            process_asl_outputs(self.dir, NAME, {"sidecar": ["BackgroundSuppression"]}, self.log)


class TestPartEntity(TempDirTest):
    def test_aslcontext_is_named_without_part(self):
        name = "sub-01_run-01_part-mag_asl"
        self.output(name, GE_DELTAM)
        self.output(name + "a", GE_M0)
        produced = process_asl_outputs(self.dir, name, {}, self.log)
        self.assertIn("sub-01_run-01_aslcontext.tsv", produced)
        self.assertIn("sub-01_run-01_part-mag_m0scan.nii.gz", produced)


class TestGePairInOtherOrder(TempDirTest):
    def test_roles_come_from_image_type_not_file_names(self):
        self.output(NAME, GE_M0)
        self.output(NAME + "a", GE_DELTAM)
        process_asl_outputs(self.dir, NAME, {}, self.log)
        self.assertEqual(self.read(NAME + ".json")["ImageType"], GE_DELTAM["ImageType"])
        self.assertEqual(self.read("sub-01_ses-01_run-01_m0scan.json")["ImageType"], GE_M0["ImageType"])


class TestSingleOutputs(TempDirTest):
    def test_label_control_series_uses_the_map_pattern(self):
        self.output(NAME, {"Manufacturer": "Siemens", "ImageType": ["ORIGINAL", "PRIMARY", "ASL"], "RepetitionTime": 4.0},
                    dims=(4, 64, 64, 20, 4))
        produced = process_asl_outputs(self.dir, NAME, {"aslcontext": ["control", "label"]}, self.log)
        self.assertIn("sub-01_ses-01_run-01_aslcontext.tsv", produced)
        self.assertEqual(
            self.read("sub-01_ses-01_run-01_aslcontext.tsv"), "volume_type\ncontrol\nlabel\ncontrol\nlabel\n"
        )
        self.assertNotIn("M0Type", self.read(NAME + ".json"))

    def test_unknown_series_without_pattern_warns_and_writes_no_aslcontext(self):
        self.output(NAME, {"Manufacturer": "Siemens", "ImageType": ["ORIGINAL", "PRIMARY", "ASL"]}, dims=(4, 64, 64, 20, 4))
        produced = process_asl_outputs(self.dir, NAME, {}, self.log)
        self.assertEqual(produced, [NAME + ".json", NAME + ".nii.gz"])
        self.assertTrue(any("aslcontext" in w for w in self.warnings()))

    def test_only_an_m0_output_is_refused(self):
        self.output(NAME, GE_M0)
        self.assertIsNone(process_asl_outputs(self.dir, NAME, {}, self.log))

    def test_ge_label_control_series_described_by_the_map_is_converted(self):
        self.output(NAME, GE_M0, dims=(4, 128, 128, 36, 8))
        produced = process_asl_outputs(self.dir, NAME, {"aslcontext": ["control", "label"]}, self.log)
        self.assertEqual(produced, [NAME + ".json", NAME + ".nii.gz", "sub-01_ses-01_run-01_aslcontext.tsv"])
        self.assertEqual(self.read("sub-01_ses-01_run-01_aslcontext.tsv").count("control"), 4)
        self.assertNotIn("M0Type", self.read(NAME + ".json"))

    def test_no_output(self):
        self.assertIsNone(process_asl_outputs(self.dir, NAME, {}, self.log))

    def test_sidecar_without_image_is_ignored(self):
        self.output(NAME, GE_DELTAM)
        with open(os.path.join(self.dir, "stray.json"), "w") as handle:
            json.dump({}, handle)
        produced = process_asl_outputs(self.dir, NAME, {}, self.log)
        self.assertIn(NAME + ".nii.gz", produced)
        self.assertTrue(any("stray.json" in w for w in self.warnings()))

    def test_two_unidentified_outputs_are_refused(self):
        unknown = {"Manufacturer": "Siemens", "ImageType": ["ORIGINAL", "PRIMARY", "M"]}
        self.output(NAME, unknown)
        self.output(NAME + "a", unknown)
        self.assertIsNone(process_asl_outputs(self.dir, NAME, {}, self.log))
        # nothing was renamed
        self.assertEqual(sorted(os.listdir(self.dir)), sorted([NAME + ".json", NAME + ".nii.gz", NAME + "a.json", NAME + "a.nii.gz"]))


class TestStandaloneM0(TempDirTest):
    def test_repetition_time_preparation_and_missing_intended_for(self):
        self.output("sub-01_m0scan", {"RepetitionTime": 5.0, "ImageType": ["ORIGINAL", "PRIMARY", "ASL"]})
        produced = process_standalone_m0scan(self.dir, "sub-01_m0scan", {}, self.log)
        self.assertEqual(produced, ["sub-01_m0scan.json", "sub-01_m0scan.nii.gz"])
        self.assertEqual(self.read("sub-01_m0scan.json")["RepetitionTimePreparation"], 5.0)
        self.assertTrue(any("IntendedFor" in w for w in self.warnings()))

    def test_intended_for_from_the_map(self):
        self.output("sub-01_m0scan", {"RepetitionTime": 5.0})
        intended = ["bids::sub-01/perf/sub-01_asl.nii.gz"]
        process_standalone_m0scan(self.dir, "sub-01_m0scan", {"sidecar": {"IntendedFor": intended}}, self.log)
        self.assertEqual(self.read("sub-01_m0scan.json")["IntendedFor"], intended)
        self.assertEqual(self.warnings(), [])

    def test_dcm2niix_postfix_on_the_one_image_is_replaced_by_the_bids_name(self):
        self.output("sub-01_m0scan_e2", {"RepetitionTime": 5.0, "EchoNumber": 2})
        produced = process_standalone_m0scan(self.dir, "sub-01_m0scan", {}, self.log)
        self.assertEqual(produced, ["sub-01_m0scan.json", "sub-01_m0scan.nii.gz"])
        self.assertEqual(sorted(os.listdir(self.dir)), ["sub-01_m0scan.json", "sub-01_m0scan.nii.gz"])
        self.assertEqual(self.read("sub-01_m0scan.json")["RepetitionTimePreparation"], 5.0)
        self.assertTrue(any("Renamed dcm2niix output sub-01_m0scan_e2" in m for m in self.messages))

    def test_ge_pcasl_series_mapped_to_m0scan_is_refused(self):
        self.output("sub-01_m0scan", GE_DELTAM)
        self.output("sub-01_m0scana", GE_M0)
        self.assertIsNone(process_standalone_m0scan(self.dir, "sub-01_m0scan", {}, self.log))
        self.assertEqual(self.read("sub-01_m0scan.json"), GE_DELTAM)


if __name__ == "__main__":
    unittest.main()
