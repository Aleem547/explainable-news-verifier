"""Provenance and boundary tests; no network, database or model required."""

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import unittest

from ml.ingestion.passages import (
    PassageSpan, extract_paragraph_contexts, split_passages,
)


def span(text, *, start=0, ordinal=0):
    return PassageSpan(ordinal, start, start+len(text), text, sha256(text.encode()).hexdigest())


class ContextWindowTests(unittest.TestCase):
    def test_retains_complete_paragraph_and_all_qualifications(self):
        text = "The Orion council approved the plan, but only for a temporary trial. It may still be withdrawn.\nNext."
        report = extract_paragraph_contexts(span(text), document_length=len(text))
        self.assertEqual(report.contexts[0].text, text.split("\n")[0])

    def test_keeps_negation_and_numbers_exactly(self):
        text = "The Orion council did not approve 16 proposals, including proposal 4."
        result = extract_paragraph_contexts(span(text), document_length=len(text)).contexts[0]
        self.assertEqual(result.text, text)
        self.assertEqual(result.sha256, sha256(text.encode()).hexdigest())

    def test_excludes_unknown_first_and_last_fragments(self):
        text = "fragment from a previous paragraph.\nA complete paragraph is here.\nA trailing fragment"
        result = extract_paragraph_contexts(span(text, start=20, ordinal=4), document_length=2000)
        self.assertEqual([c.text for c in result.contexts], ["A complete paragraph is here."])
        reasons = {code for item in result.excluded for code in item.reasons}
        self.assertIn("UNPROVEN_LEFT_PARAGRAPH_BOUNDARY", reasons)
        self.assertIn("UNPROVEN_RIGHT_PARAGRAPH_BOUNDARY", reasons)

    def test_a_final_full_stop_does_not_prove_parent_boundary(self):
        text = "A sentence may be followed by another sentence in the same paragraph."
        result = extract_paragraph_contexts(span(text), document_length=len(text)+100)
        self.assertEqual(result.contexts, ())
        self.assertIn("UNPROVEN_RIGHT_PARAGRAPH_BOUNDARY", result.excluded[0].reasons)

    def test_newline_proves_right_boundary_within_truncated_parent(self):
        text = "A complete initial paragraph.\nA trailing cut"
        result = extract_paragraph_contexts(span(text), document_length=1000)
        self.assertEqual([c.text for c in result.contexts], ["A complete initial paragraph."])

    def test_newline_proves_left_boundary_after_unknown_first_fragment(self):
        text = "\nA complete paragraph.\n"
        result = extract_paragraph_contexts(span(text, start=40), document_length=2000)
        self.assertEqual([c.text for c in result.contexts], ["A complete paragraph."])

    def test_metadata_without_sentence_terminator_is_reported(self):
        text = "Updated October 28, 2026 at 2:03 PM\nThe Orion council approved the plan.\n"
        result = extract_paragraph_contexts(span(text), document_length=1000)
        self.assertEqual([c.text for c in result.contexts], ["The Orion council approved the plan."])
        self.assertEqual(result.excluded[0].reasons, ("NO_TERMINAL_SENTENCE_PUNCTUATION",))

    def test_long_paragraph_is_excluded_instead_of_cut(self):
        text = "A long paragraph " + "word " * 40 + "."
        result = extract_paragraph_contexts(span(text), document_length=len(text), max_chars=100)
        self.assertEqual(result.contexts, ())
        self.assertIn("PARAGRAPH_EXCEEDS_CONTEXT_LIMIT", result.excluded[0].reasons)

    def test_unicode_crlf_and_outer_whitespace_preserve_document_offsets(self):
        text = '  Café — “A quoted statement.”  \r\n\r\nAnother sentence!\r\n'
        parent = span(text)
        report = extract_paragraph_contexts(parent, document_length=len(text))
        self.assertEqual(len(report.contexts), 2)
        for context in report.contexts:
            self.assertEqual(text[context.start_offset:context.end_offset], context.text)
            self.assertEqual(context.sha256, sha256(context.text.encode()).hexdigest())
        self.assertEqual(report.contexts[0].text, 'Café — “A quoted statement.”')

    def test_blank_lines_do_not_produce_empty_inputs(self):
        text = " \n\n\t\r\nA full paragraph.\n\n"
        result = extract_paragraph_contexts(span(text), document_length=len(text))
        self.assertEqual(len(result.contexts), 1)

    def test_whitespace_only_parent_has_no_contexts(self):
        text = " \n\t "
        result = extract_paragraph_contexts(span(text), document_length=len(text))
        self.assertEqual(result.contexts, ())

    def test_heading_is_not_promoted_into_a_sentence(self):
        text = "An Orion Council Meeting\nAn actual sentence follows."
        result = extract_paragraph_contexts(span(text), document_length=len(text))
        self.assertEqual([c.text for c in result.contexts], ["An actual sentence follows."])

    def test_closing_quotation_or_bracket_after_punctuation_is_supported(self):
        for text in ('He said, "This is temporary."', "A statement (with context.)", "A statement [with context.]"):
            with self.subTest(text=text):
                result = extract_paragraph_contexts(span(text), document_length=len(text))
                self.assertEqual(result.contexts[0].text, text)

    def test_hash_tampering_is_refused(self):
        parent = replace(span("A full sentence."), sha256="0"*64)
        with self.assertRaisesRegex(ValueError, "parent_passage_provenance"):
            extract_paragraph_contexts(parent, document_length=100)

    def test_inconsistent_offsets_are_refused(self):
        parent = replace(span("A full sentence."), end_offset=999)
        with self.assertRaisesRegex(ValueError, "parent_passage_provenance"):
            extract_paragraph_contexts(parent, document_length=1000)

    def test_invalid_types_and_bools_are_not_lengths(self):
        parent = span("A full sentence.")
        for kwargs in ({"document_length": True}, {"document_length": 100, "max_chars": False},
                       {"document_length": 100, "max_contexts": True}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "context_limits"):
                extract_paragraph_contexts(parent, **kwargs)
        with self.assertRaisesRegex(ValueError, "parent_passage_type"):
            extract_paragraph_contexts(object(), document_length=100)

    def test_parent_bounds_cannot_leave_document(self):
        parent = span("A full sentence.", start=90)
        with self.assertRaisesRegex(ValueError, "parent_passage_provenance"):
            extract_paragraph_contexts(parent, document_length=100)

    def test_context_limit_fails_instead_of_silently_omitting_rows(self):
        text = "First complete paragraph.\nSecond complete paragraph."
        with self.assertRaisesRegex(ValueError, "context_count_exceeds_limit"):
            extract_paragraph_contexts(span(text), document_length=len(text), max_contexts=1)

    def test_duplicate_text_keeps_distinct_offsets_and_parent_identity(self):
        text = "Repeated paragraph.\nRepeated paragraph."
        parent = span(text)
        contexts = extract_paragraph_contexts(parent, document_length=len(text)).contexts
        self.assertEqual(contexts[0].sha256, contexts[1].sha256)
        self.assertNotEqual(contexts[0].start_offset, contexts[1].start_offset)
        self.assertTrue(all(c.parent_passage_sha256 == parent.sha256 for c in contexts))

    def test_background_quotes_are_not_removed_based_on_claim_alignment(self):
        text = '“I have known Orion Council members for years,” the witness said.\n'
        # The helper knows no claim, stance or model score.
        contexts = extract_paragraph_contexts(span(text), document_length=len(text)).contexts
        self.assertEqual(contexts[0].text, text.rstrip())

    def test_records_are_immutable_and_do_not_mutate_parent(self):
        parent = span("A full sentence.")
        old = repr(parent)
        item = extract_paragraph_contexts(parent, document_length=len(parent.text)).contexts[0]
        with self.assertRaises(FrozenInstanceError):
            item.text = "Rewritten."
        self.assertEqual(repr(parent), old)

    def test_existing_lossless_splitter_still_preserves_every_character(self):
        for text in ("Word " * 500, "é中🙂\r\n" * 100, "x" * 501, " \nA paragraph.\t " * 60):
            with self.subTest(sample=text[:20]):
                pieces = split_passages(text, max_chars=100)
                self.assertEqual("".join(p.text for p in pieces), text)
                self.assertEqual([p.ordinal for p in pieces], list(range(len(pieces))))
                cursor = 0
                for item in pieces:
                    self.assertEqual(item.start_offset, cursor)
                    self.assertEqual(text[item.start_offset:item.end_offset], item.text)
                    self.assertEqual(item.sha256, sha256(item.text.encode()).hexdigest())
                    self.assertLessEqual(len(item.text), 100)
                    cursor = item.end_offset
                self.assertEqual(cursor, len(text))

    def test_legacy_validation_is_preserved(self):
        for text, size in (("", 800), (" \n", 800), ("text", 99), ("text", 4001)):
            with self.subTest(text=text, size=size), self.assertRaises(ValueError):
                split_passages(text, max_chars=size)

    def test_order_is_deterministic_and_original_paragraphs_are_not_joined(self):
        text = "First paragraph.\nSecond paragraph.\nThird paragraph."
        one = extract_paragraph_contexts(span(text), document_length=len(text))
        two = extract_paragraph_contexts(span(text), document_length=len(text))
        self.assertEqual(one, two)
        self.assertEqual([c.text for c in one.contexts], text.split("\n"))


if __name__ == "__main__":
    unittest.main()
