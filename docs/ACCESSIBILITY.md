# Accessibility validation status

The interface uses native file pickers and selects, labelled controls, visible
keyboard focus, native MathML, a structural ARIA tree and polite status messages.
The user's screen reader supplies speech. The app does not set NVDA voices, rates,
modifier keys or profiles, and does not bundle NVDA or another speech model.

**User-confirmed: voice clarity and comfort.** General positive feedback was also
received during guided image/explorer and PDF-opening checks. Exact spoken words,
focus outcomes and all task steps were not consistently recorded. Equation-reading
validation is not marked complete from that feedback. Independent blind-user task
success has not been established; no participant identity or experience is inferred.

Automated browser/API checks, audible screen-reader testing and blind-user testing
are separate evidence categories. DOM text and live-region assertions do not prove
what a screen reader actually speaks. No JAWS/VoiceOver compatibility claim is made.

## Keyboard use

1. Tab to Choose an image or Choose a PDF; Enter opens the native file picker.
2. Activate Read equation or Read selected candidate. Loading focuses Cancel
   recognition. A result normally focuses Read & explore if focus stayed in the
   reading controls. Errors receive focus and offer a return-to-input/navigation
   button. Changing inputs invalidates pending results.
3. Tab to Explore the equation. Up/Down visit visible parts; Right expands or enters;
   Left collapses or returns to the parent. Home/End visit first/last visible parts.
   Enter repeats the current part. Tab leaves the tree. Native MathML is a separate
   reading/navigation path supplied by the screen reader's math support.
4. PDF page controls retain every page. Candidate controls follow heuristic reading
   order and may skip pages without candidates. Multi-line regions are listed with
   recognition not attempted. Context is surrounding text that may contain errors.

If NVDA consumes arrow keys in browse mode, NVDA+Space switches browse/focus mode.
The NVDA modifier is the user's configured Insert/Caps Lock key. Control stops
current speech. NVDA+Control+V opens Speech settings; Tab/arrows adjust voice/rate,
OK/Enter applies, and Escape cancels. NVDA+Control+S selects a synthesizer. These
are optional user choices, not requirements or settings enforced by this app.

## Remaining manual checks

The release follow-up uses short, one-at-a-time listening checkpoints. Before
marking a checkpoint complete, record what the listener actually heard, including
silence, clipping, duplication or interruption. Speech Viewer and browser output
are diagnostic evidence only. General positive feedback does not confirm every
equation word, warning or focus target. Preserve existing speech preferences.

The listener ended the current NVDA session before the warning checkpoint.
Remaining audible checks below are pending, not failed or passed. NVDA was left
closed and its existing preferences were not reset for publication.

| Audible release checkpoint | Evidence status |
| --- | --- |
| General voice clarity and comfort | Previously user-confirmed; no voice/rate override |
| Reach Choose an image by keyboard | Listener reported hearing the written label clearly; exact utterance not transcribed |
| Load fraction and report the focused control | Listener reported successful loading; exact focus announcement remains unconfirmed |
| Hear equation words | Listener reported listening carefully and that the reading worked well; exact equation words remain unrecorded |
| Hear uncertainty and fallibility warning | New release session pending |
| Numerator navigation and repeat | New release session pending |
| Denominator navigation and repeat | New release session pending |
| Leave explorer and recover input/error focus | New release session pending |
| Hear PDF completeness separately from transcription confidence | New release session pending |
| Independent blind-user task completion | Pending; not inferred from guided testing |

- Record actual equation, confidence and structural-role utterances for a fraction,
  exponent/root and integral; listen for repetition, omission and interruption.
- Check file-picker cancellation, result/error focus, parent/child/leaf navigation,
  Enter repeat, Tab exit/re-entry, alternatives and keyboard-only error recovery.
- In real PDFs, separately hear region completeness unknown before transcription
  confidence, the context-extraction warning, multi-line non-attempt and every page
  state. Never interpret no candidates as no equations.
- Cancel decoding/discovery, replace input and confirm no stale result or late
  announcement returns. Test timeout recovery, including initial-loading limits.
- Test concrete independent reading/recovery tasks with blind users. Missed/clipped
  PDF regions currently have no dependable nonvisual correction workflow.
- Repeat on other screen readers, browsers and operating systems. The executed
  browser/runtime checks were Windows/Chromium; macOS/Linux launchers are unvalidated.
