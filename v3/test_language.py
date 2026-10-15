"""The frozen French WASH case must not receive an English response prompt."""

import unittest

from language import answer_language


class LanguageRegression(unittest.TestCase):
    def test_frozen_french_wash_question(self):
        question = "Les besoins en eau, hygiène et assainissement à Ségou sont-ils couverts par les projets FONGIM liés à l'EHA/WASH ?"
        self.assertEqual(answer_language(question), "French")

    def test_english_question_stays_english(self):
        self.assertEqual(answer_language("Are recorded projects evidence of coverage in Ségou?"), "English")

    def test_french_followup_retains_french(self):
        self.assertEqual(answer_language("Et à Bandiagara précisément : peut-on déduire les besoins du cercle à partir du total régional ?"), "French")
        self.assertEqual(answer_language("Mais comment vérifier ces besoins ?"), "French")
        self.assertEqual(answer_language("And what about Ségou?"), "English")


if __name__ == "__main__":
    unittest.main()


class SynthesisLanguageRegression(unittest.TestCase):
    def test_clear_german_research_and_followup_requests(self):
        from language import synthesis_language
        for question in ['Welche Rolle kann die DTM spielen?', 'Wie unterscheiden sich Bedarf und Reichweite?', 'Und was bedeutet das für Gao?', 'Was lässt sich daraus ableiten?', 'Bitte kürzer erklären.']:
            with self.subTest(question=question):self.assertEqual(synthesis_language(question), 'German')

    def test_existing_english_and_french_and_ambiguous_short_text(self):
        from language import synthesis_language
        for question, expected in [('What does the 3W establish?', 'English'), ('Was this project active?', 'English'), ('And in Gao?', 'English'), ('Et à Gao ?', 'French'), ('Quels besoins sont documentés ?', 'French'), ('DTM', 'English')]:
            with self.subTest(question=question):self.assertEqual(synthesis_language(question), expected)

    def test_deterministic_language_contract_is_preserved(self):
        self.assertEqual(answer_language('Welche Rolle kann die DTM spielen?'), 'English')
