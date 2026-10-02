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
