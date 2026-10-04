"""Conservative, deterministic routing before context rewriting or research."""
import re
from source_wave import _fold
from geographic_model import simple_geography_question

SIMPLIFY = {"can you explain that more simply", "explain that more simply", "explain it more simply",
    "simplify that", "simplify it", "summarize that", "summarise that", "summarize your answer",
    "make that shorter", "make it shorter", "shorter please", "can you make that shorter",
    "peux tu expliquer plus simplement", "pouvez vous expliquer plus simplement",
    "explique plus simplement", "explique cela plus simplement", "resume ta reponse", "resumez votre reponse"}


def classify(question, mode="balanced"):
    q = _fold(question)
    greeting = r"(?:(?:hi|hello|hey|bonjour|salut|bonsoir)(?: there)?(?: how are you| comment ca va)?|how are you(?: doing)?|comment ca va|ca va)"
    thanks = r"(?:thanks(?: a lot| so much)?|thank you(?: very much)?|merci(?: beaucoup)?|great thanks|ok thanks|okay thanks)"
    capabilities = {"what can you do", "how can you help", "what is this hub", "what is the mali knowledge hub",
        "que peux tu faire", "que pouvez vous faire", "comment peux tu m aider"}
    if re.fullmatch(greeting, q):
        fr = any(word in q for word in ("bonjour", "salut", "bonsoir", "ca va"))
        return {"path": "conversational", "reply": "Bonjour ! Je suis prêt à vous aider à explorer les besoins, priorités et interventions au Mali." if fr else
            "Hey! I’m ready to help you explore Mali’s needs, priorities and interventions. What would you like to look into?"}
    if re.fullmatch(thanks, q):
        return {"path": "conversational", "reply": "Avec plaisir !" if "merci" in q else "You’re welcome!"}
    if q in capabilities:
        fr = q.startswith(("que ", "comment "))
        return {"path": "conversational", "reply": "Je peux explorer les besoins, les plans, les acteurs, les projets et les financements au Mali, comparer les sources et expliquer leurs limites. Je peux aussi retrouver la hiérarchie administrative d’un lieu." if fr else
            "I can research Mali’s needs, plans, actors, projects and financing, compare sources and explain their limits. I can also look up administrative counts and a place’s parent hierarchy."}
    if q in SIMPLIFY:
        return {"path": "conversation_only"}
    if simple_geography_question(question):
        return {"path": "simple_geography"}
    return {"path": "deep_research" if mode == "deep" else "complex_research"}
