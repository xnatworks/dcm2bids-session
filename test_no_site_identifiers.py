"""Guard: no site-specific identifier is committed to this public repository.

Scans every text file in the repository for private IPv4 addresses, home-directory paths,
private (tailnet) host names, real XNAT accession numbers, AI-authorship trailers, the names
and labels of client sites, their scanner protocols and their data, and acquisition timing
values that look copied from a scanner. Test data uses placeholders and invented round numbers
instead (sub-01, XNAT_E1, ASL_3D_PCASL, RepetitionTime 5.0).

The names and labels are held as sha256 digests of the lower-cased token, so this file does not
spell them out. Timing values are not held at all: a digest of a number is reversed by trying
every number, so the guard instead requires each timing field written with a number to carry at
most one decimal place (in seconds, as BIDS writes it). A site's protocol, such as a
RepetitionTime of a few seconds and some hundredths, fails that; 5.0 and 1.5 pass.
"""
import hashlib
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
TEXT_EXTENSIONS = (".py", ".md", ".json", ".sh", ".txt", ".tsv", ".yml", ".yaml", ".cfg", ".toml")
TEXT_FILE_NAMES = ("Dockerfile",)
SKIPPED_DIRECTORIES = {".git", "__pycache__", ".pytest_cache", "node_modules"}

PRIVATE_IPV4 = re.compile(
    r"(?<![\d.])(?:10|127|192\.168|172\.(?:1[6-9]|2\d|3[01])|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))"
    r"(?:\.\d{1,3}){1,3}(?![\d.])")
HOME_DIRECTORY_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")
TAILNET_HOST = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net\b")
REAL_ACCESSION = re.compile(r"\bXNAT\d*_[ESP]\d{4,}\b")
AI_AUTHORSHIP = re.compile(r"co-authored-by:\s*claude|generated with \[?claude", re.IGNORECASE)

SITE_TOKEN_DIGESTS = {
    # client site names
    "aed4be33e55b3d8495e62f3e906fd70f75ad998c498452b2dc6f48c214e5e557",
    "3a5b8990e60ffa74e15461d7547e0f62aa94d19de4e3de687bd31176f8b6d17b",
    "1e103fdeb16ccc3e413269a593820a1353c2f5ce1eae04284aafd0c133a932ef",
    # a client's scanner series descriptions
    "72026490b6b61e8848b80b74d91098da4e0db931b84429988ffa08c056f9d749",
    "ba060dba279dd00154e0da6c0b1c43d67293e536b475ca26ecb88e64456fba03",
    "b58003c51f8221d62bbc53016417565170889f07ee5596b3951cd2fb22f26488",
    # a private test XNAT's host name, and a real subject label and site once used as a fixture
    "eab5551936dd0ac75b9daf051d453f1af42a1c4dca04a7df2345708e3a70fbbb",
    "751ec202b93d5a272b084beccd03fce3447c1a0fe6182a2fc83fe521e7f19f57",
    "64f96c79534a8a05510d5b2242df6329faad963cc48502127907df85a38d6971",
    # test project names on a private XNAT
    "a93e8e3f8efa09f03c9a20dc3dce70d52f36a2c579d99350e446dbcf4859b645",
    "c8e620d1617e3d3c67475e9d5ade3bb711d0f6f19813fd87b68637566d2d3ede",
    # subject and session labels a client's sample was given on a private XNAT
    "b526a216476eb82c8ed14eed7d08d4861f94e50d3b9ec5133727d03a34bfa4d7",
    "55a89345c5108fb815b61b415bd0fbf8f7a3acc95cf118b119a609058e165050",
}

TIMING_FIELDS = ("RepetitionTime", "RepetitionTimePreparation", "InversionTime", "PostLabelingDelay",
                 "LabelingDuration")
NUMBER = r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
# A timing field followed by a number or a list of numbers, quoted or not: "Field": 1.5 in
# JSON, {'Field': 1.5} in Python, Field=1.5, sidecar["Field"], 1.5 in an assertion, and
# "Field": [1.5, 2.0] for multiple delays. Prose ("a Field of 1.5 s") is not matched.
TIMING_FIELD_VALUE = re.compile(
    r"\b(%s)[\"']?\]?\s*[:=,]\s*(\[[^\]]*\]|[\"']?%s[\"']?)" % ("|".join(TIMING_FIELDS), NUMBER))
MAX_TIMING_DECIMALS = 1


def word_tokens(text):
    """Lower-cased identifiers in the text, whole and split at underscores and camelCase humps."""
    tokens = set()
    for identifier in re.findall(r"[A-Za-z0-9_]+", text):
        tokens.add(identifier.lower())
        for piece in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", identifier):
            if piece:
                tokens.add(piece.lower())
    return tokens


def timing_field_values(text):
    """(field, value) for every timing field written with a number, one pair per list element."""
    pairs = []
    for match in TIMING_FIELD_VALUE.finditer(text):
        for number in re.findall(r"(?<![\w.])%s(?![\w.])" % NUMBER, match.group(2)):
            pairs.append((match.group(1), float(number)))
    return pairs


def is_round(value, decimals=MAX_TIMING_DECIMALS):
    """Whether the value has at most the given number of decimal places."""
    scaled = value * 10 ** decimals
    return abs(scaled - round(scaled)) < 1e-9


def site_identifier_findings(text, token_digests=SITE_TOKEN_DIGESTS):
    """What in the text identifies a site, its data or a private machine, one description per finding."""
    findings = []
    for label, pattern in (("private IPv4 address", PRIVATE_IPV4),
                           ("home-directory path", HOME_DIRECTORY_PATH),
                           ("tailnet host name", TAILNET_HOST),
                           ("real XNAT accession number", REAL_ACCESSION),
                           ("AI-authorship trailer", AI_AUTHORSHIP)):
        findings.extend("%s: %s" % (label, match.group(0)) for match in pattern.finditer(text))
    for token in sorted(word_tokens(text)):
        if hashlib.sha256(token.encode("utf-8")).hexdigest() in token_digests:
            findings.append("site name or protocol: %s" % token)
    for field, value in timing_field_values(text):
        if not is_round(value):
            findings.append("timing value with more than %d decimal place (use an invented round number): %s=%r"
                            % (MAX_TIMING_DECIMALS, field, value))
    return findings


def repository_text_files(root=REPO_ROOT):
    for directory, subdirectories, file_names in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRECTORIES]
        for file_name in file_names:
            if file_name.endswith(TEXT_EXTENSIONS) or file_name in TEXT_FILE_NAMES:
                yield os.path.join(directory, file_name)


class TestSiteIdentifierFindings(unittest.TestCase):
    """The checker itself, so the repository scan below cannot pass by finding nothing."""

    def test_private_ipv4_is_found_but_dicom_uids_and_versions_are_not(self):
        private_address = ".".join(["10", "1", "2", "3"])
        self.assertEqual(site_identifier_findings("host " + private_address),
                         ["private IPv4 address: " + private_address])
        self.assertEqual(site_identifier_findings("UID 1.2.840.113619.6.514 dcm2niix v1.0.20261029"), [])

    def test_home_path_and_tailnet_host_are_found(self):
        home_path = "/" + "Users" + "/someone/data"
        tailnet_host = "box." + "example.ts" + ".net"
        findings = site_identifier_findings("%s and %s" % (home_path, tailnet_host))
        self.assertIn("home-directory path: " + home_path[:-4], findings)
        self.assertIn("tailnet host name: " + tailnet_host, findings)

    def test_real_accession_is_found_but_placeholders_are_not(self):
        real_accession = "XNAT_" + "E28845"
        self.assertEqual(site_identifier_findings("session " + real_accession),
                         ["real XNAT accession number: " + real_accession])
        self.assertEqual(site_identifier_findings("XNAT_E1 XNAT_E02 XNAT_S01"), [])

    def test_ai_authorship_trailer_is_found(self):
        trailer = "Co-Authored-" + "By: Claude <noreply@example.com>"
        self.assertEqual(len(site_identifier_findings(trailer)), 1)

    def test_site_token_is_found_whole_in_snake_case_and_in_camel_case(self):
        digests = {hashlib.sha256(b"examplesite").hexdigest()}
        for text in ("ExampleSite", "examplesite_scan", "TestExamplesiteNaming", "examplesite"):
            self.assertEqual(site_identifier_findings(text, digests), ["site name or protocol: examplesite"],
                             text)
        self.assertEqual(site_identifier_findings("example site", digests), [])

    # The values are put together at run time, so the repository scan does not find them in this file.
    UNROUND = "2." + "25"

    def test_unround_timing_value_is_found_in_json_python_assertion_and_list_forms(self):
        for template in ('"PostLabelingDelay": {v},', "{{'PostLabelingDelay': {v}}}", "PostLabelingDelay={v}",
                         'sidecar["PostLabelingDelay"], {v})', "sidecar['PostLabelingDelay'], {v})",
                         '"PostLabelingDelay": [1.5, {v}]', '"PostLabelingDelay": "{v}"', '"PostLabelingDelay":\n    {v}',
                         '"PostLabelingDelay": {v}0', '"PostLabelingDelay": {exponent}'):
            text = template.format(v=self.UNROUND, exponent="225" + "e-2")
            findings = site_identifier_findings(text)
            self.assertEqual(len(findings), 1, text)
            self.assertIn("PostLabelingDelay=" + self.UNROUND, findings[0], text)

    def test_round_timing_values_and_other_fields_pass(self):
        for text in ('"PostLabelingDelay": 2.0', '"RepetitionTime": 5', "{'LabelingDuration': 1.5}",
                     '"PostLabelingDelay": [1.5, 2.0, 2.5]', '"RepetitionTime": 25e-1', '"InversionTime": 0.7',
                     '"EchoTime": 0.0123', '"SliceTiming": [0.125]', "a RepetitionTime of {} s".format(self.UNROUND),
                     '("RepetitionTimePreparation", "IntendedFor")', "dcm2niix v1.0.20261029"):
            self.assertEqual(site_identifier_findings(text), [], text)

    def test_every_list_element_is_checked(self):
        findings = site_identifier_findings('"PostLabelingDelay": [{}, 1.5, {}]'.format("1." + "25", "1." + "75"))
        self.assertEqual(len(findings), 2)


class TestRepositoryHasNoSiteIdentifiers(unittest.TestCase):

    def test_repository_files_hold_no_site_identifiers(self):
        scanned = 0
        problems = []
        for path in repository_text_files():
            with open(path, encoding="utf-8", errors="replace") as text_file:
                text = text_file.read()
            scanned += 1
            relative_path = os.path.relpath(path, REPO_ROOT)
            problems.extend("%s: %s" % (relative_path, finding) for finding in site_identifier_findings(text))
        self.assertGreater(scanned, 5, "the scan found almost no files; check REPO_ROOT")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
