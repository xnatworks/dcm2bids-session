"""Tests for regex pattern matching in BIDS map resolution."""

import collections
import re
import unittest

import xnatbidsfns


# Import match_regex_pattern without importing the full dcm2bids_wholeSession module,
# which has heavy dependencies (nipype) and top-level argparse that runs at import time.
# We use the same implementation as in dcm2bids_wholeSession.py.
def match_regex_pattern(seriesdesc, regex_patterns):
    """Try regex patterns against a series description. Returns matched entry or None."""
    for entry in regex_patterns:
        if re.search(entry['pattern'], seriesdesc):
            return entry
    return None


class TestMatchRegexPattern(unittest.TestCase):
    """Tests for the match_regex_pattern helper function."""

    def test_basic_regex_match(self):
        patterns = [{"pattern": "(?i)^se_field_mapping", "suffix": "epi", "modality": "fmap"}]
        result = match_regex_pattern("SE_Field_Mapping_AP", patterns)
        self.assertEqual(result["suffix"], "epi")

    def test_no_match_returns_none(self):
        patterns = [{"pattern": "(?i)^se_field_mapping", "suffix": "epi", "modality": "fmap"}]
        result = match_regex_pattern("T1w_MPRAGE", patterns)
        self.assertIsNone(result)

    def test_empty_patterns_returns_none(self):
        result = match_regex_pattern("anything", [])
        self.assertIsNone(result)

    def test_first_match_wins(self):
        patterns = [
            {"pattern": "(?i)^bold", "suffix": "bold_first", "modality": "func"},
            {"pattern": "(?i)bold", "suffix": "bold_second", "modality": "func"},
        ]
        result = match_regex_pattern("BOLD_task_rest", patterns)
        self.assertEqual(result["suffix"], "bold_first")

    def test_second_pattern_matches_when_first_does_not(self):
        patterns = [
            {"pattern": "(?i)^rest_bold$", "suffix": "bold_exact", "modality": "func"},
            {"pattern": "(?i)bold", "suffix": "bold_contains", "modality": "func"},
        ]
        result = match_regex_pattern("task_BOLD_run1", patterns)
        self.assertEqual(result["suffix"], "bold_contains")

    def test_case_insensitive_flag_in_pattern(self):
        patterns = [{"pattern": "(?i)^t1w_mprage", "suffix": "T1w", "modality": "anat"}]
        result = match_regex_pattern("T1W_MPRAGE_SAG", patterns)
        self.assertEqual(result["suffix"], "T1w")

    def test_case_sensitive_pattern(self):
        patterns = [{"pattern": "^T1w_MPRAGE", "suffix": "T1w", "modality": "anat"}]
        # Lowercase should not match a case-sensitive pattern
        result = match_regex_pattern("t1w_mprage", patterns)
        self.assertIsNone(result)

    def test_null_suffix_returns_entry(self):
        """Null suffix entries should still be returned — caller decides to skip."""
        patterns = [{"pattern": "(?i)^localizer", "suffix": None, "modality": None}]
        result = match_regex_pattern("Localizer_Scout", patterns)
        self.assertIsNotNone(result)
        self.assertIsNone(result["suffix"])

    def test_missing_suffix_key_returns_entry(self):
        """Entry without 'suffix' key should still be returned."""
        patterns = [{"pattern": "(?i)^scout"}]
        result = match_regex_pattern("Scout_3plane", patterns)
        self.assertIsNotNone(result)
        self.assertIsNone(result.get("suffix"))


class TestExactMatchPriority(unittest.TestCase):
    """Test that exact matches take priority over regex patterns."""

    def _resolve(self, field_list, bidsnamemap, regex_patterns):
        """Replicate the resolution logic from dcm2bids_wholeSession."""
        resolved = []
        for x in field_list:
            if x.lower() in bidsnamemap:
                resolved.append(bidsnamemap[x.lower()])
            elif regex_patterns:
                regex_match = match_regex_pattern(x, regex_patterns)
                if regex_match and regex_match.get('suffix'):
                    resolved.append(regex_match['suffix'])
        return resolved

    def test_exact_match_takes_priority(self):
        bidsnamemap = {"bold_task_rest": "task-rest_bold"}
        regex_patterns = [{"pattern": "(?i)bold", "suffix": "task-generic_bold", "modality": "func"}]
        resolved = self._resolve(["BOLD_task_rest"], bidsnamemap, regex_patterns)
        self.assertEqual(resolved, ["task-rest_bold"])

    def test_regex_used_when_no_exact_match(self):
        bidsnamemap = {"t1w_mprage": "T1w"}
        regex_patterns = [{"pattern": "(?i)bold", "suffix": "task-rest_bold", "modality": "func"}]
        resolved = self._resolve(["BOLD_task_rest"], bidsnamemap, regex_patterns)
        self.assertEqual(resolved, ["task-rest_bold"])

    def test_no_patterns_no_match(self):
        bidsnamemap = {"t1w_mprage": "T1w"}
        resolved = self._resolve(["BOLD_task_rest"], bidsnamemap, [])
        self.assertEqual(resolved, [])


class TestScanMatchingLogic(unittest.TestCase):
    """Test the per-scan matching block logic."""

    def _match_scan(self, seriesdesc, bidsnamemap, regex_patterns):
        """Replicate the per-scan matching logic. Returns (match, regex_modality) or None to skip."""
        regex_modality = None
        if seriesdesc.lower() not in bidsnamemap:
            if regex_patterns:
                regex_match = match_regex_pattern(seriesdesc, regex_patterns)
                if regex_match:
                    if not regex_match.get('suffix'):
                        return None  # exclusion pattern
                    match = regex_match['suffix']
                    regex_modality = regex_match.get('modality')
                    return (match, regex_modality)
                else:
                    return None  # not found
            else:
                return None  # not found, no patterns
        else:
            match = bidsnamemap[seriesdesc.lower()]
            return (match, regex_modality)

    def test_exact_match_returns_match_no_regex_modality(self):
        bidsnamemap = {"bold_task_rest": "task-rest_bold"}
        result = self._match_scan("BOLD_task_rest", bidsnamemap, [])
        self.assertEqual(result, ("task-rest_bold", None))

    def test_regex_match_with_modality(self):
        bidsnamemap = {}
        patterns = [{"pattern": "(?i)^se_field", "suffix": "epi", "modality": "fmap"}]
        result = self._match_scan("SE_Field_Mapping", bidsnamemap, patterns)
        self.assertEqual(result, ("epi", "fmap"))

    def test_regex_match_without_modality(self):
        bidsnamemap = {}
        patterns = [{"pattern": "(?i)^bold", "suffix": "task-rest_bold"}]
        result = self._match_scan("BOLD_resting", bidsnamemap, patterns)
        self.assertEqual(result, ("task-rest_bold", None))

    def test_null_suffix_exclusion(self):
        bidsnamemap = {}
        patterns = [{"pattern": "(?i)^localizer", "suffix": None}]
        result = self._match_scan("Localizer", bidsnamemap, patterns)
        self.assertIsNone(result)

    def test_missing_suffix_key_exclusion(self):
        bidsnamemap = {}
        patterns = [{"pattern": "(?i)^scout"}]
        result = self._match_scan("Scout_3plane", bidsnamemap, patterns)
        self.assertIsNone(result)

    def test_no_match_anywhere(self):
        bidsnamemap = {"t1w": "T1w"}
        patterns = [{"pattern": "(?i)^bold", "suffix": "task-rest_bold"}]
        result = self._match_scan("DWI_b1000", bidsnamemap, patterns)
        self.assertIsNone(result)

    def test_exact_match_priority_over_regex(self):
        bidsnamemap = {"se_field_mapping_ap": "acq-AP_epi"}
        patterns = [{"pattern": "(?i)^se_field", "suffix": "epi", "modality": "fmap"}]
        result = self._match_scan("SE_Field_Mapping_AP", bidsnamemap, patterns)
        self.assertEqual(result, ("acq-AP_epi", None))

    def test_no_regex_patterns_existing_behavior(self):
        """With no regex patterns, behavior matches the original code exactly."""
        bidsnamemap = {"t1w_mprage": "T1w", "bold_rest": "task-rest_bold"}
        # Known series
        result = self._match_scan("T1w_MPRAGE", bidsnamemap, [])
        self.assertEqual(result, ("T1w", None))
        # Unknown series
        result = self._match_scan("Unknown_Series", bidsnamemap, [])
        self.assertIsNone(result)


class TestSubdirResolution(unittest.TestCase):
    """Test subdirectory resolution with regex_modality override."""

    def _get_subdir(self, bidsname, regex_modality):
        """Replicate the subdirectory resolution logic."""
        if regex_modality:
            return regex_modality
        else:
            return xnatbidsfns.getSubdir(xnatbidsfns.generateBidsNameMap(bidsname)['modality'])

    def test_regex_modality_overrides_derivation(self):
        # epi normally maps to fmap via getSubdir, but regex_modality could be anything
        bidssubdir = self._get_subdir("sub-01_ses-01_epi", "custom_dir")
        self.assertEqual(bidssubdir, "custom_dir")

    def test_null_regex_modality_uses_getsubdir(self):
        bidssubdir = self._get_subdir("sub-01_ses-01_T1w", None)
        self.assertEqual(bidssubdir, "anat")

    def test_func_modality_derivation(self):
        bidssubdir = self._get_subdir("sub-01_ses-01_task-rest_bold", None)
        self.assertEqual(bidssubdir, "func")

    def test_fmap_modality_derivation(self):
        bidssubdir = self._get_subdir("sub-01_ses-01_epi", None)
        self.assertEqual(bidssubdir, "fmap")

    def test_regex_modality_fmap(self):
        bidssubdir = self._get_subdir("sub-01_ses-01_epi", "fmap")
        self.assertEqual(bidssubdir, "fmap")


class TestRunNumberingWithRegex(unittest.TestCase):
    """Test that run numbering works correctly for regex-matched scans."""

    def _resolve_and_count(self, field_list, bidsnamemap, regex_patterns):
        """Replicate resolved list and multiples counting."""
        resolved = []
        for x in field_list:
            if x.lower() in bidsnamemap:
                resolved.append(bidsnamemap[x.lower()])
            elif regex_patterns:
                regex_match = match_regex_pattern(x, regex_patterns)
                if regex_match and regex_match.get('suffix'):
                    resolved.append(regex_match['suffix'])
        bidscount = collections.Counter(resolved)
        multiples = {desc: count for desc, count in bidscount.items() if count > 1}
        return resolved, multiples

    def test_regex_matches_counted_for_run_numbering(self):
        """Multiple scans matching the same regex pattern should get run numbers."""
        bidsnamemap = {}
        patterns = [{"pattern": "(?i)^bold", "suffix": "task-rest_bold", "modality": "func"}]
        field_list = ["BOLD_run1", "BOLD_run2", "T1w_MPRAGE"]
        resolved, multiples = self._resolve_and_count(field_list, bidsnamemap, patterns)
        self.assertEqual(resolved, ["task-rest_bold", "task-rest_bold"])
        self.assertIn("task-rest_bold", multiples)
        self.assertEqual(multiples["task-rest_bold"], 2)

    def test_mixed_exact_and_regex_run_numbering(self):
        """Exact and regex matches with same suffix should be counted together."""
        bidsnamemap = {"bold_task_rest": "task-rest_bold"}
        patterns = [{"pattern": "(?i)^bold_variant", "suffix": "task-rest_bold", "modality": "func"}]
        field_list = ["BOLD_task_rest", "BOLD_variant_rest"]
        resolved, multiples = self._resolve_and_count(field_list, bidsnamemap, patterns)
        self.assertEqual(resolved, ["task-rest_bold", "task-rest_bold"])
        self.assertIn("task-rest_bold", multiples)
        self.assertEqual(multiples["task-rest_bold"], 2)


class TestBidsmapResourceFallback(unittest.TestCase):
    """Test that bidsmap.json from project resource is parsed correctly."""

    def _parse_resource_response(self, response_data):
        """Replicate the resource fallback parsing logic."""
        bidsmaplist = []
        bidsmaptoadd = response_data
        if isinstance(bidsmaptoadd, dict) and "mappings" in bidsmaptoadd:
            bidsmaptoadd = bidsmaptoadd["mappings"]
        if isinstance(bidsmaptoadd, list):
            for mapentry in bidsmaptoadd:
                if mapentry not in bidsmaplist:
                    bidsmaplist.append(mapentry)
            return bidsmaplist
        return None

    def test_plain_list_format(self):
        """Resource file contains a plain list of entries."""
        data = [
            {"xnat_field": "T1w_MPRAGE", "bidsname": "T1w"},
            {"pattern": "(?i)^bold", "suffix": "bold", "modality": "func"},
        ]
        result = self._parse_resource_response(data)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["bidsname"], "T1w")

    def test_wrapped_mappings_format(self):
        """Resource file contains {"mappings": [...]} wrapper (tree-builder format)."""
        data = {
            "version": "1.0.0",
            "mappings": [
                {"pattern": "(?i)^T1w", "suffix": "T1w", "modality": "anat"},
                {"pattern": "(?i)^bold", "suffix": "bold", "modality": "func"},
            ]
        }
        result = self._parse_resource_response(data)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["suffix"], "T1w")

    def test_unexpected_format_returns_none(self):
        """Non-list, non-mappings dict returns None."""
        data = {"something": "else"}
        result = self._parse_resource_response(data)
        self.assertIsNone(result)

    def test_deduplication(self):
        """Duplicate entries are not added twice."""
        data = [
            {"pattern": "(?i)^bold", "suffix": "bold", "modality": "func"},
            {"pattern": "(?i)^bold", "suffix": "bold", "modality": "func"},
        ]
        result = self._parse_resource_response(data)
        self.assertEqual(len(result), 1)


if __name__ == '__main__':
    unittest.main()
