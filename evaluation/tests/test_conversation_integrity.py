import unittest
from evaluation.conversation_integrity import validate_context


class ContextIntegrityTests(unittest.TestCase):
    def test_retrieval_of_unrelated_projects_cannot_pass_subset(self):
        sequence = {'turns': ['Which projects?', 'Which of those are still active?']}
        result = validate_context(sequence, 1, 'AGRO (ID 715), KELEN (ID 461)',
                                  'SARES, project ID 664; HIV, ID 434')
        self.assertEqual(result[0]['status'], 'fail')
        self.assertEqual(result[0]['unexpected_ids'], ['434', '664'])

    def test_subset_identity_is_context_and_fresh_status_is_required_elsewhere(self):
        sequence = {'turns': ['Which projects?', 'Which of those are still active?']}
        self.assertEqual(validate_context(sequence, 1, 'ID 715 and ID 461',
                                          'ID 715 remains recorded as En cours [E01]')[0]['status'], 'pass')

    def test_missing_lookup_identity_stays_unknown(self):
        sequence = {'turns': ['Which projects?', 'Which of those are still active?']}
        self.assertEqual(validate_context(sequence, 1, 'AGRO Ecologie', 'ID 715')[0]['status'], 'unknown')

    def test_false_numeric_premise_must_not_change_administrative_entity(self):
        sequence = {'turns': ['How many cercles are in Mali?', 'Are all 999 of them EU funded?']}
        self.assertEqual(validate_context(sequence, 1, '159 cercles [E01]',
                                          'Not all 999 projects are EU funded [E02]')[0]['status'], 'fail')
        self.assertEqual(validate_context(sequence, 1, '159 cercles [E01]',
                                          'Mali has 159 cercles; funding for all of them is not established [E01]')[0]['status'], 'pass')
