"""Resolve only count/place ellipses. Thread context never supplies facts."""
import re
from geographic_model import geographic_model, simple_geography_question
from query_router import classify
from source_wave import _fold
from followup_context import previous_question


def resolve_hierarchy_followup(question, messages):
    followup = re.fullmatch(r'(?:and(?: in)?|what about|same for|et(?: a|dans|en)?) (.+)',
                            _fold(question))
    if not followup:
        return None
    previous = previous_question(messages)
    if not previous or not simple_geography_question(previous):
        return None
    base = re.fullmatch(
        r'(?:what is the (?:parent hierarchy|full administrative path|administrative path|hierarchy) of|'
        r'quelle est la hierarchie administrative de) (.+) '
        r'(region|cercle|commune|locality|arrondissement)', _fold(previous))
    if not base:
        return None
    old_place, level = base.groups()
    model = geographic_model()
    if len(model.lookup(old_place, level, model.preferred)) != 1:
        return None
    new_place = followup[1]
    explicit = re.fullmatch(r'(.+) (region|cercle|commune|locality|arrondissement)', new_place)
    if explicit:
        new_place, level = explicit.groups()
    if len(model.lookup(new_place, level, model.preferred)) != 1:
        return None
    return f'What is the parent hierarchy of {new_place} {level}?'


def resolve_count_followup(question, messages):
    followup = re.fullmatch(r'(?:and in|what about|et a|et dans|et en) (.+)', _fold(question))
    if not followup:
        return None
    previous = None
    for message in messages[-10:]:
        text = message.get('standalone_question') or (
            message.get('content') if message.get('role') == 'user' else None)
        if not isinstance(text, str) or not text.strip():
            continue
        if classify(text)['path'] == 'conversational':
            continue
        # A new substantive topic invalidates the preceding count context.
        previous = text
    if not previous or not simple_geography_question(previous):
        return None
    base = _fold(previous)
    count = re.fullmatch(
        r'(?:how many|combien de) (communes|municipalities|cercles|localities|localites) '
        r'(?:are in|are there in|belong to|compte le|dans|en|a|au) (.+)', base)
    if not count:
        return None
    metric, scope = count.groups()
    metric = {'municipalities': 'communes', 'localites': 'localities'}.get(metric, metric)
    level_match = re.fullmatch(r'(.+) (region|cercle|commune)', scope)
    parent_level = level_match[2] if level_match else 'region'
    old_place = level_match[1] if level_match else scope
    model = geographic_model()
    if old_place != 'mali' and len(model.lookup(old_place, parent_level, model.preferred)) != 1:
        return None
    new_scope = followup[1]
    explicit = re.fullmatch(r'(.+) (region|cercle|commune)', new_scope)
    if explicit:
        new_place, parent_level = explicit.groups()
    else:
        new_place = new_scope
    # Unknown/ambiguous names retain the existing semantic/clarification route.
    if len(model.lookup(new_place, parent_level, model.preferred)) != 1:
        return None
    if (metric, parent_level) not in {
        ('communes', 'region'), ('communes', 'cercle'),
        ('cercles', 'region'), ('localities', 'commune')
    }:
        return None
    return f'How many {metric} are in {new_place} {parent_level}?'
