"""Conservative LaTeX normalization used only for voting between readings.

Same rules as the research comparator (ryze-eval math/evaluate_math.py, after fix D2): drop spacing,
style and delimiter-size commands, map dfrac/tfrac to frac and operatorname{X} to mathrm{X}, then
ignore whitespace. Signs, relations, roots, scripts and braces are never touched. The returned
reading is always the model's own string, never the normalized key.
"""
import re

SPACING = [r'\\,', r'\\;', r'\\:', r'\\!', r'\\qquad', r'\\quad', r'~', r'\\ ']
STYLE = [r'\\displaystyle', r'\\textstyle', r'\\scriptstyle', r'\\limits', r'\\nolimits']
SIZERS = [r'\\left', r'\\right', r'\\biggl', r'\\biggr', r'\\Biggl', r'\\Biggr', r'\\bigl', r'\\bigr',
          r'\\Bigl', r'\\Bigr', r'\\bigg', r'\\Bigg', r'\\big', r'\\Big']


def normalize(s: str) -> str:
    s = s.replace('\\nonumber', '')
    for p in SPACING + STYLE:
        tail = r'(?![A-Za-z])' if p[-1].isalpha() else ''  # lookahead only after alphabetic commands
        s = re.sub(p + tail, ' ', s)
    for p in SIZERS:
        s = re.sub(p + r'(?![A-Za-z])', ' ', s)
    s = re.sub(r'\\[dt]frac(?![A-Za-z])', r'\\frac', s)
    s = re.sub(r'\\operatorname\{([^}]*)\}', r'\\mathrm{\1}', s)
    return re.sub(r'\s+', ' ', s).strip()


TEXT_COMMANDS = re.compile(r'\\(text|textrm|textit|textbf|textsf|texttt|textnormal|mbox|hbox)\s*\{')
KEPT_SPACE = '\u2423'  # stands for a meaningful space inside text-mode arguments


def _protect_text_spaces(s: str) -> str:
    """Mark spaces inside \\text{...}-style arguments (brace-balanced) so voting keeps them."""
    out, i = [], 0
    for m in TEXT_COMMANDS.finditer(s):
        if m.start() < i:
            continue
        out.append(s[i:m.end()])
        depth, j = 1, m.end()
        while j < len(s) and depth:
            depth += {'{': 1, '}': -1}.get(s[j], 0) if s[j - 1] != '\\' else 0
            j += 1
        arg = s[m.end():j]
        out.append(re.sub(r'\s+', KEPT_SPACE, arg))  # LaTeX collapses runs; leading/trailing spaces still render
        i = j
    out.append(s[i:])
    return ''.join(out)


def vote_key(s: str) -> str:
    # Deviation from the research key (which dropped every space): spaces inside text-mode arguments
    # are meaningful ("a b" vs "ab") and are kept, as RESEARCH_NOTES.md requires.
    return _protect_text_spaces(normalize(s)).replace(' ', '')
