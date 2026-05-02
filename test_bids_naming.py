import unittest

from bids_naming import (
    add_or_replace_run_entity,
    build_bids_base,
    build_naming_collision_message,
    collapse_paired_fieldmap_run,
    detect_gre_fieldmap_component,
    duplicate_bids_suffix_counts,
    prepare_gre_fieldmap_bidsname,
    rename_echo_file,
    rename_gre_fieldmap_file,
    resolve_scan_match,
)


class TestRenameEchoFile(unittest.TestCase):
    def test_echo_without_run_goes_before_bold_suffix(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_task-rest_bold_e1.nii.gz"
            ),
            "sub-01_ses-01_task-rest_echo-1_bold.nii.gz",
        )

    def test_echo_without_run_json_goes_before_bold_suffix(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_task-rest_bold_e2.json"
            ),
            "sub-01_ses-01_task-rest_echo-2_bold.json",
        )

    def test_echo_with_run_stays_after_run_entity(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_task-rest_run-03_bold_e2.nii.gz"
            ),
            "sub-01_ses-01_task-rest_run-03_echo-2_bold.nii.gz",
        )

    def test_echo_without_run_goes_before_sbref_suffix(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_task-rest_sbref_e3.nii.gz"
            ),
            "sub-01_ses-01_task-rest_echo-3_sbref.nii.gz",
        )

    def test_echo_phase_without_run_keeps_bids_entity_order(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_task-rest_bold_e1_ph.nii.gz"
            ),
            "sub-01_ses-01_task-rest_echo-1_part-phase_bold.nii.gz",
        )

    def test_echo_phase_with_run_keeps_bids_entity_order(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_task-rest_run-01_bold_e1_ph.nii.gz"
            ),
            "sub-01_ses-01_task-rest_run-01_echo-1_part-phase_bold.nii.gz",
        )

    def test_phase_without_echo_is_labeled_part_phase(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_task-rest_bold_ph.nii.gz"
            ),
            "sub-01_ses-01_task-rest_part-phase_bold.nii.gz",
        )

    def test_echo_phase_fieldmap_keeps_entities_before_suffix(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_run-01_fieldmap_e1_ph.nii.gz"
            ),
            "sub-01_ses-01_run-01_echo-1_part-phase_fieldmap.nii.gz",
        )

    def test_non_echo_name_is_unchanged(self):
        self.assertEqual(
            rename_echo_file(
                "sub-01_ses-01_task-rest_bold.nii.gz"
            ),
            "sub-01_ses-01_task-rest_bold.nii.gz",
        )


class TestGreFieldmapNaming(unittest.TestCase):
    def test_detects_magnitude_component_from_siemens_fieldmap(self):
        self.assertEqual(
            detect_gre_fieldmap_component(
                ["ORIGINAL", "PRIMARY", "M", "ND"],
                sequence_name="*fm2d2",
                series_description="field_map_2p4iso",
                bidsname="sub-01_ses-01_run-01_fieldmap",
            ),
            "magnitude",
        )

    def test_detects_phasediff_component_from_siemens_fieldmap(self):
        self.assertEqual(
            detect_gre_fieldmap_component(
                ["ORIGINAL", "PRIMARY", "P", "ND"],
                sequence_name="*fm2d2",
                series_description="field_map_2p4iso",
                bidsname="sub-01_ses-01_run-02_fieldmap",
            ),
            "phasediff",
        )

    def test_does_not_reclassify_non_fieldmap_suffix(self):
        self.assertIsNone(
            detect_gre_fieldmap_component(
                ["ORIGINAL", "PRIMARY", "M", "ND"],
                sequence_name="*fm2d2",
                series_description="field_map_2p4iso",
                bidsname="sub-01_ses-01_T1w",
            )
        )

    def test_collapses_scan_runs_to_fieldmap_pair_runs(self):
        self.assertEqual(
            collapse_paired_fieldmap_run("sub-01_ses-01_run-01_fieldmap"),
            "sub-01_ses-01_run-01_fieldmap",
        )
        self.assertEqual(
            collapse_paired_fieldmap_run("sub-01_ses-01_run-02_fieldmap"),
            "sub-01_ses-01_run-01_fieldmap",
        )
        self.assertEqual(
            collapse_paired_fieldmap_run("sub-01_ses-01_run-03_fieldmap"),
            "sub-01_ses-01_run-02_fieldmap",
        )
        self.assertEqual(
            collapse_paired_fieldmap_run("sub-01_ses-01_run-04_fieldmap"),
            "sub-01_ses-01_run-02_fieldmap",
        )

    def test_prepares_magnitude_and_phasediff_bidsnames(self):
        self.assertEqual(
            prepare_gre_fieldmap_bidsname(
                "sub-01_ses-01_run-03_fieldmap",
                "magnitude",
            ),
            "sub-01_ses-01_run-02_magnitude",
        )
        self.assertEqual(
            prepare_gre_fieldmap_bidsname(
                "sub-01_ses-01_run-04_fieldmap",
                "phasediff",
            ),
            "sub-01_ses-01_run-02_phasediff",
        )

    def test_renames_magnitude_echo_outputs_to_bids_suffixes(self):
        self.assertEqual(
            rename_gre_fieldmap_file(
                "sub-01_ses-01_run-01_magnitude_e1.nii.gz",
                "magnitude",
            ),
            "sub-01_ses-01_run-01_magnitude1.nii.gz",
        )
        self.assertEqual(
            rename_gre_fieldmap_file(
                "sub-01_ses-01_run-01_magnitude_e2.json",
                "magnitude",
            ),
            "sub-01_ses-01_run-01_magnitude2.json",
        )

    def test_renames_phase_output_to_phasediff(self):
        self.assertEqual(
            rename_gre_fieldmap_file(
                "sub-01_ses-01_run-01_phasediff_e2_ph.nii.gz",
                "phasediff",
            ),
            "sub-01_ses-01_run-01_phasediff.nii.gz",
        )


class TestNamingCollisionMessage(unittest.TestCase):
    def test_collision_message_explains_failure_and_bidsmap_fix(self):
        message = build_naming_collision_message(
            scan_id="60",
            field_name="series_description",
            field_value="cmrr_2p5iso_mb3me3_TR1500",
            bidsname="sub-01_ses-01_task-rest_bold",
            source_name="sub-01_ses-01_task-rest_bold_e2.nii.gz",
            target_name="sub-01_ses-01_task-rest_echo-2_bold.nii.gz",
            target_path="/nifti/IMG/60/sub-01_ses-01_task-rest_echo-2_bold.nii.gz",
        )

        self.assertIn("BIDS naming collision detected", message)
        self.assertIn("Scan ID: 60", message)
        self.assertIn("Mapping field: series_description", message)
        self.assertIn("cmrr_2p5iso_mb3me3_TR1500", message)
        self.assertIn("dcm2niix output file", message)
        self.assertIn("Attempted renamed file", message)
        self.assertIn("project BIDS map", message)
        self.assertIn("run-01 and run-02", message)
        self.assertIn('"xnat_field": "cmrr_2p5iso_mb3me3_TR1500"', message)


DEMO02_BIDS_BASE = (
    "sub-paugaa20200428DCCN_"
    "ses-200428084433DST131221107524366068_"
)


DEMO02_REPROIN_SCANS = [
    ("1", "anat-scout_ND"),
    ("2", "anat-scout"),
    ("3", "anat-scout_MPR_sag"),
    ("4", "anat-scout_MPR_cor"),
    ("5", "anat-scout_MPR_tra"),
    ("6", "anat-T1w_acq-MPRAGE"),
    ("7", "fmap_acq-4mm"),
    ("8", "fmap_acq-4mm"),
    ("9", "dwi_dir-AP"),
    ("15", "fmap_dir-PA"),
    ("16", "func_task-rest"),
]

DEMO02_REPROIN_BIDSMAP = [
    {"xnat_field": "anat-T1w_acq-MPRAGE", "bidsname": "acq-MPRAGE_T1w"},
    {"xnat_field": "fmap_acq-4mm", "bidsname": "acq-4mm_epi"},
    {"xnat_field": "dwi_dir-AP", "bidsname": "dir-AP_dwi"},
    {"xnat_field": "fmap_dir-PA", "bidsname": "dir-PA_epi"},
    {"xnat_field": "func_task-rest", "bidsname": "task-rest_bold"},
    {"pattern": "(?i).*localizer.*", "suffix": None},
    {"pattern": "(?i).*scout.*", "suffix": None},
]

DEMO02_BIDS_SMOKE_SCANS = [
    ("1", "localizer_32ch-head"),
    ("2", "AAHead_Scout_32ch-head"),
    ("7", "t1_mprage_sag_ipat2_1p0iso"),
    ("47", "cmrr_2p4iso_mb8_TR0700_SBRef"),
    ("48", "cmrr_2p4iso_mb8_TR0700"),
    ("49", "field_map_2p4iso"),
    ("50", "field_map_2p4iso"),
    ("59", "cmrr_2p5iso_mb3me3_TR1500_SBRef"),
    ("60", "cmrr_2p5iso_mb3me3_TR1500"),
    ("61", "field_map_2p5iso"),
    ("62", "field_map_2p5iso"),
]

DEMO02_BIDS_SMOKE_BIDSMAP = [
    {"xnat_field": "t1_mprage_sag_ipat2_1p0iso", "bidsname": "T1w"},
    {"xnat_field": "cmrr_2p4iso_mb8_TR0700_SBRef", "bidsname": "task-rest_sbref"},
    {"xnat_field": "field_map_2p4iso", "bidsname": "run-01_fieldmap"},
    {"xnat_field": "cmrr_2p5iso_mb3me3_TR1500_SBRef", "bidsname": "task-rest_sbref"},
    {"xnat_field": "field_map_2p5iso", "bidsname": "run-01_fieldmap"},
    {"xnat_field": "cmrr_2p4iso_mb8_TR0700", "bidsname": "task-cmrr2p4isomb8TR0700_bold"},
    {"xnat_field": "cmrr_2p5iso_mb3me3_TR1500", "bidsname": "task-cmrr2p5isomb3me3TR1500_bold"},
    {"pattern": "(?i).*localizer.*", "suffix": None},
    {"pattern": "(?i).*scout.*", "suffix": None},
    {"pattern": "(?i).*AAHead_Scout.*", "suffix": None},
]

DEMO02_BIDS_TEST_SCANS = [
    ("1", "T1w"),
    ("2", "task-flanker_run-1_bold"),
    ("3", "task-flanker_run-2_bold"),
]

DEMO02_BIDS_TEST_BIDSMAP = [
    {"xnat_field": "T1w", "bidsname": "T1w"},
    {"xnat_field": "task-flanker_run-1_bold", "bidsname": "task-flanker_run-01_bold"},
    {"xnat_field": "task-flanker_run-2_bold", "bidsname": "task-flanker_run-02_bold"},
]

DEMO02_BIDS_GEN_E2E_SCANS = [
    ("6", "anat-T1w_desc-mpragep2iso"),
    ("7", "dwi_acq-DKI64dir_dir-AP"),
    ("8", "dwi_acq-DKI64dir_dir-PA"),
]

DEMO02_BIDSMAP_BUGFIX_SCANS = [
    ("1", "3 Plane Localizer"),
    ("2", "anat-T1w"),
    ("3", "fmap-epi_dir-AP"),
    ("4", "fmap-epi_dir-PA"),
    ("5", "func_acq-mb4_desc-CMRR_bold_SBRef"),
    ("6", "func_acq-mb4_desc-CMRR_bold"),
    ("7", "func_acq-mb6_desc-CMRR_bold_SBRef"),
    ("8", "func_acq-mb6_desc-CMRR_bold"),
    ("9", "func_acq-mb8_desc-CMRR_bold_SBRef"),
    ("10", "func_acq-mb8_desc-CMRR_bold"),
    ("11", "func_acq-mb4_desc-siemens_bold"),
    ("12", "func_acq-mb6_desc-siemens_bold"),
    ("13", "func_acq-mb8_desc-siemens_bold"),
    ("99", "PhoenixZIPReport"),
]

DEMO02_BIDSMAP_BUGFIX_BIDSMAP = [
    {"xnat_field": "anat-T1w", "bidsname": "T1w"},
    {"xnat_field": "fmap-epi_dir-AP", "bidsname": "dir-AP_epi"},
    {"xnat_field": "fmap-epi_dir-PA", "bidsname": "dir-PA_epi"},
    {"xnat_field": "func_acq-mb4_desc-CMRR_bold_SBRef", "bidsname": "task-rest_acq-mb4CMRR_sbref"},
    {"xnat_field": "func_acq-mb4_desc-CMRR_bold", "bidsname": "task-rest_acq-mb4CMRR_bold"},
    {"xnat_field": "func_acq-mb6_desc-CMRR_bold_SBRef", "bidsname": "task-rest_acq-mb6CMRR_sbref"},
    {"xnat_field": "func_acq-mb6_desc-CMRR_bold", "bidsname": "task-rest_acq-mb6CMRR_bold"},
    {"xnat_field": "func_acq-mb8_desc-CMRR_bold_SBRef", "bidsname": "task-rest_acq-mb8CMRR_sbref"},
    {"xnat_field": "func_acq-mb8_desc-CMRR_bold", "bidsname": "task-rest_acq-mb8CMRR_bold"},
    {"xnat_field": "func_acq-mb4_desc-siemens_bold", "bidsname": "task-rest_acq-mb4siemens_bold"},
    {"xnat_field": "func_acq-mb6_desc-siemens_bold", "bidsname": "task-rest_acq-mb6siemens_bold"},
    {"xnat_field": "func_acq-mb8_desc-siemens_bold", "bidsname": "task-rest_acq-mb8siemens_bold"},
    {"pattern": "(?i).*localizer.*", "suffix": None},
    {"pattern": "(?i).*PhoenixZIPReport.*", "suffix": None},
]


def _bids_maps(bidsmap):
    exact = {
        entry["xnat_field"].lower(): entry["bidsname"]
        for entry in bidsmap
        if "xnat_field" in entry and "bidsname" in entry
    }
    regex_patterns = [entry for entry in bidsmap if "pattern" in entry]
    return exact, regex_patterns


def _planned_suffixes(scans, bidsmap):
    exact, regex_patterns = _bids_maps(bidsmap)
    fields = [series for _, series in scans]
    multiples = duplicate_bids_suffix_counts(fields, exact, regex_patterns)
    planned = {}

    for scan_id, series in reversed(scans):
        scan_match = resolve_scan_match(series, exact, regex_patterns)
        if not scan_match:
            planned[scan_id] = None
            continue

        suffix = scan_match[0]
        if suffix in multiples:
            suffix = add_or_replace_run_entity(suffix, multiples[suffix])
            multiples[scan_match[0]] -= 1

        planned[scan_id] = suffix

    return planned


class TestDemo02ScanNaming(unittest.TestCase):
    def test_demo02_bids_base_matches_existing_outputs(self):
        self.assertEqual(
            build_bids_base(
                "paugaa_20200428_DCCN",
                "20_04_28-08_44_33-DST-1_3_12_2_1107_5_2_43_66068",
            ),
            DEMO02_BIDS_BASE,
        )

    def test_demo02_reproin_scan_suffixes(self):
        self.assertEqual(
            _planned_suffixes(DEMO02_REPROIN_SCANS, DEMO02_REPROIN_BIDSMAP),
            {
                "1": None,
                "2": None,
                "3": None,
                "4": None,
                "5": None,
                "6": "acq-MPRAGE_T1w",
                "7": "acq-4mm_run-01_epi",
                "8": "acq-4mm_run-02_epi",
                "9": "dir-AP_dwi",
                "15": "dir-PA_epi",
                "16": "task-rest_bold",
            },
        )

    def test_demo02_bids_smoke_scan_suffixes(self):
        self.assertEqual(
            _planned_suffixes(DEMO02_BIDS_SMOKE_SCANS, DEMO02_BIDS_SMOKE_BIDSMAP),
            {
                "1": None,
                "2": None,
                "7": "T1w",
                "47": "task-rest_run-01_sbref",
                "48": "task-cmrr2p4isomb8TR0700_bold",
                "49": "run-01_fieldmap",
                "50": "run-02_fieldmap",
                "59": "task-rest_run-02_sbref",
                "60": "task-cmrr2p5isomb3me3TR1500_bold",
                "61": "run-03_fieldmap",
                "62": "run-04_fieldmap",
            },
        )

    def test_demo02_bids_test_scan_suffixes(self):
        self.assertEqual(
            _planned_suffixes(DEMO02_BIDS_TEST_SCANS, DEMO02_BIDS_TEST_BIDSMAP),
            {
                "1": "T1w",
                "2": "task-flanker_run-01_bold",
                "3": "task-flanker_run-02_bold",
            },
        )

    def test_demo02_bids_gen_e2e_empty_map_does_not_resolve_scans(self):
        self.assertEqual(
            _planned_suffixes(DEMO02_BIDS_GEN_E2E_SCANS, []),
            {
                "6": None,
                "7": None,
                "8": None,
            },
        )

    def test_demo02_bidsmap_bugfix_scan_suffixes(self):
        self.assertEqual(
            _planned_suffixes(
                DEMO02_BIDSMAP_BUGFIX_SCANS,
                DEMO02_BIDSMAP_BUGFIX_BIDSMAP,
            ),
            {
                "1": None,
                "2": "T1w",
                "3": "dir-AP_epi",
                "4": "dir-PA_epi",
                "5": "task-rest_acq-mb4CMRR_sbref",
                "6": "task-rest_acq-mb4CMRR_bold",
                "7": "task-rest_acq-mb6CMRR_sbref",
                "8": "task-rest_acq-mb6CMRR_bold",
                "9": "task-rest_acq-mb8CMRR_sbref",
                "10": "task-rest_acq-mb8CMRR_bold",
                "11": "task-rest_acq-mb4siemens_bold",
                "12": "task-rest_acq-mb6siemens_bold",
                "13": "task-rest_acq-mb8siemens_bold",
                "99": None,
            },
        )

    def test_demo02_multi_echo_bold_without_run_does_not_collide(self):
        source_files = [
            f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_bold_e1.nii.gz",
            f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_bold_e2.nii.gz",
            f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_bold_e3.nii.gz",
            f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_bold_e1.json",
            f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_bold_e2.json",
            f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_bold_e3.json",
        ]
        renamed = [rename_echo_file(name) for name in source_files]

        self.assertEqual(len(renamed), len(set(renamed)))
        self.assertEqual(
            renamed,
            [
                f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_echo-1_bold.nii.gz",
                f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_echo-2_bold.nii.gz",
                f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_echo-3_bold.nii.gz",
                f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_echo-1_bold.json",
                f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_echo-2_bold.json",
                f"{DEMO02_BIDS_BASE}task-cmrr2p5isomb3me3TR1500_echo-3_bold.json",
            ],
        )

    def test_demo02_multi_echo_sbref_with_run_keeps_run_before_echo(self):
        self.assertEqual(
            rename_echo_file(
                f"{DEMO02_BIDS_BASE}task-rest_run-02_sbref_e3.nii.gz"
            ),
            f"{DEMO02_BIDS_BASE}task-rest_run-02_echo-3_sbref.nii.gz",
        )


if __name__ == "__main__":
    unittest.main()
