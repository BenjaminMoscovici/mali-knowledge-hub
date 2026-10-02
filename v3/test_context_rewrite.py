"""Check that follow-up resolution uses prior answers only as query context."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unicodedata
import unittest


class ResponseRecorder:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text="What evidence supports the reported gap in Mopti?")


class ContextRewriteTests(unittest.TestCase):
    def test_long_french_followup_uses_previous_turn(self):
        question = "Et à Bandiagara précisément : peut-on déduire les besoins du cercle à partir du total régional ?"
        for filename in ("app.py", "analysis_core.py"):
            with self.subTest(filename=filename):
                source = ast.parse((Path(__file__).parent / filename).read_text())
                function = next(node for node in source.body
                                if isinstance(node, ast.FunctionDef)
                                and node.name == "likely_context_dependent_followup")
                namespace = {"normalize_text": lambda value: "".join(
                    char for char in unicodedata.normalize("NFKD", value.lower())
                    if not unicodedata.combining(char))}
                exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
                detect = namespace[function.name]
                self.assertTrue(detect(question, [{"role": "user", "content": "Besoins à Mopti ?"}]))
                self.assertFalse(detect(question, []))
                self.assertFalse(detect("What are the humanitarian needs in Mopti?", [{"role": "user", "content": "Earlier topic"}]))

    def test_assistant_reference_is_context_not_evidence(self):
        source = ast.parse((Path(__file__).parent / "app.py").read_text())
        function = next(node for node in source.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "resolve_conversational_question")
        recorder = ResponseRecorder()
        namespace = {"openai_client": SimpleNamespace(responses=recorder)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
        answer = namespace[function.name]("What about that gap?", [
            {"role": "user", "content": "What are the needs in Mopti?"},
            {"role": "assistant", "content": "There may be a gap in Mopti [D1]."},
        ])
        self.assertIn("gap in Mopti", recorder.kwargs["input"])
        self.assertIn("never evidence", recorder.kwargs["instructions"])
        self.assertIn("fresh retrieval", recorder.kwargs["instructions"])
        self.assertEqual(answer, "What evidence supports the reported gap in Mopti?")


if __name__ == "__main__":
    unittest.main()
