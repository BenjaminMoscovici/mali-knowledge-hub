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

    def test_rewrite_input_excludes_a_superseded_topic(self):
        messages = [
            {"role": "user", "content": "What are the humanitarian needs in Mopti?"},
            {"role": "assistant", "content": "Old Mopti gap [E01]."},
            {"role": "user", "content": "Which organisations operate in Gao?"},
            {"role": "assistant", "content": "Current Gao roster [E02]."},
        ]
        for filename in ("app.py", "analysis_core.py"):
            with self.subTest(filename=filename):
                source = ast.parse((Path(__file__).parent / filename).read_text())
                function = next(node for node in source.body
                                if isinstance(node, ast.FunctionDef)
                                and node.name == "resolve_conversational_question")
                recorder = ResponseRecorder()
                namespace = {"openai_client": SimpleNamespace(responses=recorder)}
                exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
                namespace[function.name]("What about that result?", messages)
                self.assertIn("Current Gao roster", recorder.kwargs["input"])
                self.assertNotIn("Old Mopti gap", recorder.kwargs["input"])

    def test_rewrite_input_retains_late_ids_from_a_long_current_roster(self):
        messages = [
            {"role": "user", "content": "List the documented projects in Gao."},
            {"role": "assistant", "content": (
                "Current Gao roster begins. " + ("x" * 6800) +
                " Final entries: FONGIM Project ID 664; World Bank project P166811.")},
        ]
        for filename in ("app.py", "analysis_core.py"):
            with self.subTest(filename=filename):
                source = ast.parse((Path(__file__).parent / filename).read_text())
                function = next(node for node in source.body
                                if isinstance(node, ast.FunctionDef)
                                and node.name == "resolve_conversational_question")
                recorder = ResponseRecorder()
                namespace = {"openai_client": SimpleNamespace(responses=recorder)}
                exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
                namespace[function.name]("Which of those projects are active?", messages)
                self.assertIn("Current Gao roster begins", recorder.kwargs["input"])
                self.assertIn("FONGIM Project ID 664", recorder.kwargs["input"])
                self.assertIn("P166811", recorder.kwargs["input"])
                self.assertIn("middle omitted; context only", recorder.kwargs["input"])

    def test_rewrite_input_retains_only_qualified_middle_identifiers(self):
        messages = [
            {"role": "user", "content": "List the documented projects in Gao."},
            {"role": "assistant", "content": (
                "Current Gao roster begins. " + ("x" * 3300) +
                " Middle entries: FONGIM Project ID 664; World Bank project P166811; "
                "budget 999; year 2099. " + ("y" * 3300) + " Final context.")},
        ]
        for filename in ("app.py", "analysis_core.py"):
            with self.subTest(filename=filename):
                source = ast.parse((Path(__file__).parent / filename).read_text())
                function = next(node for node in source.body
                                if isinstance(node, ast.FunctionDef)
                                and node.name == "resolve_conversational_question")
                recorder = ResponseRecorder()
                namespace = {"openai_client": SimpleNamespace(responses=recorder)}
                exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
                namespace[function.name]("Which of those projects are active?", messages)
                self.assertIn("FONGIM project IDs 664", recorder.kwargs["input"])
                self.assertIn("World Bank project IDs P166811", recorder.kwargs["input"])
                self.assertNotIn("budget 999", recorder.kwargs["input"])
                self.assertNotIn("year 2099", recorder.kwargs["input"])
                self.assertIn("source-qualified identifiers retained", recorder.kwargs["input"])


if __name__ == "__main__":
    unittest.main()
