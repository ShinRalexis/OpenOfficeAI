# -*- coding: utf-8 -*-
# The seven actions and the instruction each one sends to the model.
# Instructions are written in English (every model, small local ones included,
# follows English instructions best) and ask for the answer in the language of
# the selected text, so the tools work in any language. The general system
# prompt from the settings is sent separately as the "system" message.
from __future__ import unicode_literals

# Absolute imports on purpose: inside the office, uno's import hook hides the
# real cause of a failed "from ... import" behind a "type ... is unknown" error.
import openofficeai.i18n as i18n

SAME_LANGUAGE = "Write the result in the same language as the TEXT."
SAME_PARAGRAPHS = "Keep the paragraph breaks of the TEXT: one output paragraph for each input paragraph."
PLAIN_TEXT = ("The result goes straight into a word processor: write plain text, "
              "no Markdown (no asterisks, hash signs or code blocks), no preamble, "
              "no comments, no quotes around the result.")


class Action(object):
    def __init__(self, key, task, output="replace", keep_language=True, keep_paragraphs=False,
                 needs="msg.select_text"):
        self.key = key
        self.task = task
        # "replace": writes into the document; "synonyms": shows a chooser.
        self.output = output
        self.keep_language = keep_language
        self.keep_paragraphs = keep_paragraphs
        self.needs = needs

    @property
    def label(self):
        return i18n.tr("act." + self.key)

    def build(self, text, s):
        target = (s.get("translate_to") or "").strip() or i18n.LANGUAGE_NAMES[i18n.language()]
        lines = [self.task.format(target=target)]
        if self.keep_language:
            lines.append(SAME_LANGUAGE)
        if self.keep_paragraphs and "\n" in text.strip():
            lines.append(SAME_PARAGRAPHS)
        lines.append(PLAIN_TEXT)
        return "{0}\n\nTEXT:\n\"\"\"\n{1}\n\"\"\"".format(" ".join(lines), text)


ACTIONS = [
    Action(
        "migliora",
        "Improve the form, flow and cohesion of the TEXT without changing its meaning. "
        "Keep tone, register and information. Make implicit context explicit only where "
        "it helps. Avoid embellishments.",
        keep_paragraphs=True,
    ),
    Action(
        "editing",
        "Do a MINIMAL professional copy edit of the TEXT. Fix only clear errors "
        "(spelling, punctuation, agreement, syntax). Do not change the style or the "
        "author's voice. Remove only obvious redundancy, no broad rewrites. Keep a "
        "similar length.",
        keep_paragraphs=True,
    ),
    Action(
        "riassunto",
        "Summarize the TEXT keeping the key information. Clear and compact style "
        "(3 to 5 sentences if possible). No title.",
    ),
    Action(
        "traduci",
        "Translate the TEXT into {target}, keeping meaning, tone and nuances. "
        "Return only the translation, without notes or explanations.",
        keep_language=False,
        keep_paragraphs=True,
    ),
    Action(
        "elenco",
        "Turn the TEXT into a bulleted list with clear, concise points (at most one "
        "line each). Start every point with the character • followed by a space.",
    ),
    Action(
        "spiega",
        "Explain the TEXT to a non-expert reader. Use simple examples, concrete "
        "analogies and short sentences. Avoid jargon and define any technical term "
        "that appears. Return only the explanation.",
    ),
    Action(
        "sinonimi",
        "Give synonyms and expressive alternatives for the word or phrase in the TEXT, "
        "keeping the same register (formal or informal). If it is an idiom, give "
        "equivalent paraphrases. Return a single line with 6 to 12 proposals separated "
        "by commas, without numbers, dashes or explanations.",
        output="synonyms",
        needs="msg.select_word",
    ),
]

BY_KEY = dict((a.key, a) for a in ACTIONS)
