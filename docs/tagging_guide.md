# Tagging guide (Phase 6)

Tag with `tools/tagger.html`, in a browser window beside a legally licensed stream. Nothing is recorded from the video.
Fighter A is the red corner and B the blue corner of the bout ID (`bout_fighter.corner` in the database).

## Workflow
1. Enter the bout ID, tagger name and the two fighter names. Start the clock (Space) when the broadcast round clock starts;
   `[` and `]` nudge it by a second; `N` ends the round and resets to 0:00.
2. Press an event key, fill the form with Tab, Enter to save, Esc to cancel. The time stamped is when you pressed the key.
   `U` undoes the last event.
3. After each round press **Round-end summary** and compare takedowns with the broadcast stats.
4. Export JSON and CSV into `data/tags/`, then `python -m ufcmodel import-tags data/tags`. The import also lists any bout where
   tagged landed takedowns differ from UFCStats; fix those first.
5. Re-tag 10% of bouts at least two weeks later into a separate folder and load it with `--pass-no 2`. Fields with Cohen's
   kappa under 0.6 get a tighter definition or are dropped (`ufcmodel.tagging.import_tags.field_kappas`).

## Events (keys in brackets)
- **[P] Position change:** distance, clinch open, clinch on cage (who pins who), standing back control, or ground (guard, half
  guard, side control, mount, back, front headlock, turtle) and who is on top.
- **[T] Takedown attempt:** type, location (cage or open), setup in the 2 seconds before (none if nothing), result
  (landed, stuffed, landed but up within 10 s, landed but up within 30 s).
- **[G] Get-up:** seconds to stand and method.
- **[S] Submission attempt:** type and outcome.
- **[H] Hurt event:** rocked or knocked down, the strike, and the response.
- **[R] Pressure sequence:** who moves forward, the defender's exit, and whether it ends on the cage.
- **[K] Kick outcome:** checked, landed or caught, for the kicker.
- **[W] Stance switch:** the new stance.

## Edge cases
- **Clinch on the cage:** use it only when the pinned fighter's back or hip is against the fence and the hold lasts about 2 seconds
  or more. Brief touches along the fence stay "clinch open".
- **Takedown location:** "cage" if the fighter's back or side was on the fence when they went down or the shot started from a
  pin. A shot from open space that finishes at the fence is "open".
- **Landed vs stuffed:** a takedown counts as landed when the fighter ends on the mat with the opponent controlling position for
  about 2 seconds. Use the "up within 10 s / 30 s" results when the fighter is back on their feet that fast.
- **Setup:** only strikes or feints in the 2 seconds before the shot count. Anything earlier is "none".
- **Round-end:** an action that straddles the bell belongs to the round where it started.
- When unsure between two options, pick the more conservative one. If the same doubt keeps coming up, the definition needs
  tightening: say which case it is and it will be added here.

## First wave
The last three to five UFC bouts of every fighter on the next two cards, then the top 15 of two divisions: about 100 bouts at
roughly 20 to 30 minutes each. Track the actual time per bout; the tool does not do it for you.
