"""Extract the previous answer's main point and limitations without research."""
import re


def restate(question, prior, language):
    previous = next((m['content'] for m in reversed(prior) if m.get('role') == 'assistant'), None)
    if not previous:
        return {"answer": "Quelle réponse souhaitez-vous simplifier ?" if language == 'French' else "Which answer would you like me to simplify?", "evidence": []}
    text = re.sub(r"\[E\d+(?:\s*,\s*E\d+)*\]", "", previous)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    prose = [b for b in blocks if not re.fullmatch(r"(?:#{1,6}\s+[^\n]+|\*\*[^\n]+\*\*:?)", b)
             and not b.startswith(('Restatement of', 'Short version of', 'Reformulation de', 'Version courte de'))]
    if not prose:
        return {"answer": "Quelle partie souhaitez-vous clarifier ?" if language == 'French' else "Which part would you like clarified?", "evidence": []}
    # Quote complete sentences, so extracted qualifications are not paraphrased.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ])", prose[0])
    main = ' '.join(sentences[:2]) if len(sentences) > 2 else prose[0]
    caveats = []
    for i, block in enumerate(blocks):
        if re.search(r"^(?:#{1,6}\s*|\*\*)?(?:Important limitations|Limitations|Limites importantes|Limites|Incertitudes)(?:\*\*)?:?$", block, re.I):
            for following in blocks[i + 1:]:
                if re.match(r"^(?:#{1,6}\s+|\*\*[^\n]+\*\*:?$)", following):
                    break
                caveats.append(following)
    if not caveats:
        for block in reversed(prose[1:]):
            if re.search(r"\b(?:cannot|not|unknown|unverified|uncertain|missing|limitations?|ne|pas|incertain|limites?|manqu\w*)\b", block, re.I):
                caveats.append(block)
                break
    selected = [main] + [b for b in caveats if b != main]
    label = ("Version courte de la réponse précédente, sans nouvelle recherche. Les sources restent dans la réponse originale." if language == 'French' else
             "Short version of the previous answer, without new research. Sources remain with the original answer.")
    quoted = '\n\n'.join('\n'.join('> ' + line for line in b.splitlines()) for b in selected)
    return {"answer": label + "\n\n" + quoted, "evidence": []}
