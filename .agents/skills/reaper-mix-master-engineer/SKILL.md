---
name: reaper-mix-master-engineer
description: >
  Run evidence-led vocal mixing and mastering workflows in REAPER through
  REAPER MCP. Use for session preparation, reference setup, vocal mixing over
  stereo instrumentals, mix approval, mastering candidates, and delivery.
---

# REAPER mix and master operating standard

Use this skill to take a song from raw session to approved delivery through
REAPER MCP. It is one operating procedure for both human engineers and agents,
not a collection of tips or preset recipes.

REAPER is the source of project state. Measurements are technical evidence.
The producer's controlled listening judgment is the source of artistic
approval. An agent must never pretend that project data is hearing.

This process can enforce professional discipline, repeatability, and technical
QC. It cannot guarantee an award, a hit, or excellent source material.

## Canon

Use only this source hierarchy unless the producer requests another authority.

1. Mike Senior, *Mixing Secrets for the Small Studio*: mixing order,
   problem-led processing, balance, arrangement, automation, and mix endgame.
2. Bob Katz, *Mastering Audio*: monitoring, signal integrity, dynamics,
   loudness, peak control, dither, and delivery theory.
3. Ian Shepherd, *Mastering Essentials*: the practical start-to-finish
   mastering pass and the reason for each stage.
4. Official REAPER videos and User Guide: DAW mechanics only.

Do not use vendor presets, genre chains, influencer settings, or generic AI
skills as engineering authority. A demonstration may show how a tool works; it
does not prove that the song needs that tool.

## Action admission test

Before every consequential edit or processor change, answer all seven
questions:

1. What specific problem are we solving?
2. What evidence shows the problem exists?
3. Where does it occur: source, track GUID, section, or time range?
4. Is an earlier-stage fix available?
5. What is the smallest reversible action likely to solve it?
6. How will we run a level-matched A/B?
7. Who must approve the result by listening?

If any answer is missing, do not process. Inspect, measure, or ask for the
required listening judgment instead.

Every admitted action gets this record:

```yaml
problem:
evidence:
scope:
proposal:
earlier_stage_fix_considered:
ab_method:
ab_result: pending
listener_decision: pending
undo_label:
```

Use stable REAPER GUIDs. Keep mutations in named undo steps. Never invent
missing observations.

## Gates

Work in order. Do not skip a gate because later processing is more interesting.

| Gate | Required result | Approval |
| --- | --- | --- |
| 0. Brief | Song intent, lead hierarchy, delivery, reference jobs | Producer |
| 1. Integrity | Complete audit and verified source alignment | Engineer |
| 2. Performance | Comping, timing, tuning, cleanup, and clip gain complete | Producer |
| 3. Balance | Static mix communicates at moderate and low level | Producer |
| 4. Mix | Tone, dynamics, space, and automation solve named problems | Producer |
| 5. Print | Clean premaster passes render and technical QC | Producer |
| 6. Master | Gain-matched candidates pass measurement and translation checks | Producer |
| 7. Delivery | Approved files, codec checks, hashes, and manifest | Engineer |

An agent reports the current gate, evidence obtained, decisions pending, and
the next permitted action. It must not call unfinished work approved.

## Gate 0: brief and reference

Before touching the session:

- State the song's emotional center and the element that must hold attention.
- Name the lead in each section. Classify other vocals as double, harmony,
  ad-lib, answer, or texture.
- Record intended release formats and alternate versions.
- Give every reference a narrow job: vocal position, low-end relationship,
  depth, width, density, or final impact.
- Reject “make it exactly like the reference.” The arrangement and recording
  remain their own song.

One good reference is enough. Keep it muted by default and use
`configure_reference_track` so it reaches the monitor path without passing
through master-bus processing.

## Gate 1: session integrity

Use `get_project_snapshot` and the narrow read or analysis tools needed to
establish facts:

- Every expected source resolves and starts at the intended musical position.
- Sample rates, channel layouts, item bounds, and render bounds are known.
- Duplicate items, unexplained offsets, clipped files, DC, long silence,
  abrupt edits, and extreme level differences are reported.
- Track names and vocal roles are unambiguous.
- Existing FX, sends, routing, automation, tempo, and markers are inventoried.
- Suspected audible problems are separated from measured facts.

Save before creative work. Return an audit with three sections: confirmed
facts, listening checks, and producer decisions.

## Gate 2: performance and cleanup

Fix the source before trying to mix around it:

1. Select or comp the intended takes.
2. Correct timing only where the pocket or intelligibility is weakened.
3. Tune only notes that need it; preserve slides, vibrato, and character.
4. Use item or take gain to reduce avoidable phrase-level jumps.
5. Repair clicks, plosives, intrusive breaths, and isolated sibilance locally.
6. Judge every edit in the arrangement, not only in solo.

When lead and double performances are scattered across source lanes:

1. Preserve the source lanes and label used and unused material explicitly.
2. Create one lead and one double destination track per artist.
3. Audition one phrase at a time and require listening confirmation when the
   lead role is ambiguous.
4. Split the phrase, duplicate the chosen item, and call
   `move_media_item_to_track` on the duplicate with its expected source GUID.
5. Verify the returned destination GUID, unchanged timeline position, and
   preserved take offsets.
6. Check the compiled phrase against the source lanes before continuing.
7. Mute the source lanes only after the complete role tracks pass comparison.

Do not quantize, tune, denoise, or align every event by default.

## Gate 3: static balance

Build the record before building chains:

1. Use a repeatable moderate monitor level.
2. Start with the stereo instrumental and the principal lead.
3. Establish section-by-section hierarchy between singers.
4. Add doubles, harmonies, and ad-libs only when the leads already communicate.
5. Use level, mute, arrangement, and pan before processing.
6. Check low-volume intelligibility and mono compatibility.
7. Mark the exact moments where masking, instability, harshness, or depth
   prevents the song from working.

The static balance is the control condition for later A/B tests.

## Gate 4: problem-led mix

Follow this decision order. Move right only when the earlier action cannot
solve the problem without damage.

| Problem | First response | Then, if evidence remains |
| --- | --- | --- |
| Word or phrase level jumps | Item gain or local automation | Compression for the remaining envelope |
| Vocal buried by stereo beat | Level, timing, arrangement, pan | Vocal EQ; then narrow, vocal-keyed beat reduction |
| Mud or resonance | Identify source and moment | Small static or dynamic EQ move |
| Sibilance or plosive | Local edit or automation | Narrow dynamic control |
| Vocal lacks stability | Lead rides | Compression with a named time-scale job |
| Lead lacks depth or glue | Level and tone | One send with a defined room, plate, or delay job |
| Section lacks movement | Arrangement and rides | Effect throws or return automation |
| Mix lacks width | Arrangement and pan | Source-specific stereo treatment with mono check |
| Mix lacks impact | Balance and transient relationship | Bus dynamics only for a confirmed envelope problem |

### Compression

Compression is not an automatic vocal stage. Name whether it controls peaks,
evens phrases, changes sustain, adds density, or changes groove. If two
compressors are used, each must have a different stated job. Level-match
bypass; louder is not better.

### EQ

EQ requires a location and a symptom. Check level, arrangement, mic character,
and masking before boosting. Do not copy frequencies from another song.

### Stereo-instrumental constraint

When vocals sit over a single stereo instrumental:

- Do not broadly scoop the beat for every vocal layer.
- Solve vocal hierarchy and vocal tone first.
- If masking is limited to a repeatable band and moment, use the smallest
  vocal-triggered dynamic reduction that restores intelligibility.
- Treat source separation as destructive recovery work requiring producer
  approval, not a normal mix step.

### Space and automation

Use shared sends when sources belong in one acoustic world. Every reverb or
delay must have one job. Automate the lead, transitions, throws, and returns
where the arrangement changes; do not expect static compression to keep every
line emotionally forward.

## Reference checkpoints

Reference briefly at three points: static balance, main vocal treatment, and
mix endgame.

- Keep the reference outside master FX.
- Attenuate the louder source before comparing.
- Compare only its assigned traits.
- Use the most comparable section.
- Return to the working song after each short check.

Do not EQ-match a finished master to an unfinished mix.

## Gate 5: mix approval and print

Before print:

- Check every section, transition, edit, start, ending, fade, and render bound.
- Check mono, low level, headphones, speakers, and a lossy preview when those
  paths are actually available.
- Bypass the complete mix processing path at fair loudness and confirm every
  retained stage earns its place.
- Print a clean premaster without a final loudness limiter.
- Print a separate loud listening version when needed; never confuse it with
  the premaster.

Use lossless 32-bit float or 24-bit PCM at the project sample rate. Mastering
cannot begin until the producer explicitly approves the clean mix.

## Gate 6: isolated mastering

Master the approved stereo premaster in a separate project. Use the typed
mastering workflow so source identity, plans, candidates, approvals, and
deliveries remain reproducible.

1. `create_mastering_session`: fingerprint the approved premaster and record
   the brief and reference notes.
2. `create_stereo_mastering_project`: create an isolated stereo project.
3. Audit the entire source for clipping, true peak, loudness, tonal balance,
   dynamics, noise, start, ending, and silence.
4. Return to the mix when the defect is better solved there.
5. `preview_mastering_plan`: document the exact chain and evidence before
   applying it.
6. `apply_mastering_plan`: apply only the approved, revalidated plan.
7. `create_mastering_candidate`: render and measure each materially different
   candidate.
8. `compare_mastering_candidates` and `prepare_mastering_audition`: create a
   fair attenuation-only comparison.
9. `approve_mastering_candidate`: record the producer's listening notes and
   chosen candidate.

Use this mastering decision order:

| Finding | Preferred action |
| --- | --- |
| Mix defect or bad balance | Recall the mix |
| Section-to-section tonal shift | Mix recall or section automation |
| Repeatable whole-program tonal imbalance | Small broad EQ move |
| Macro-dynamic inconsistency | Section gain or automation |
| Micro-dynamic problem | Compression with a named envelope job |
| Excess peak preventing desired impact | Peak control after tone and dynamics |
| Loudness difference only | Gain-match before changing processing |

Do not chase a streaming normalization number. Loudness, true peak, crest
factor or PLR, and codec behavior are evidence about the result, not automatic
artistic targets. Dither once, only when reducing fixed-point bit depth.

## Gate 7: delivery

Use `deliver_mastering_candidate` only for an approved candidate. Then:

- Create and audition codec previews where required.
- Verify sample rate, bit depth, channel layout, duration, true peak, silence,
  clipping, DC, file hash, and naming.
- Build clean, explicit, instrumental, or performance versions only from
  separately rendered and approved mixes.
- Record the source fingerprint, plan identity, candidate identity, listener
  approval, QC results, and delivered hashes in the manifest.

## Stop conditions

Stop instead of guessing when:

- A source is missing or differs from its recorded fingerprint.
- A REAPER GUID or FX identity is stale.
- A plugin parameter has no verified meaning.
- The reference enters the master-FX path.
- Monitoring is unavailable for a required artistic decision.
- The mix or candidate lacks explicit listening approval.
- A requested alternate was not independently created and approved.
- The proposed action fails the action admission test.

## Sources

- [Mike Senior, *Mixing Secrets* contents and audio examples](https://cambridge-mt.com/ms3/contents/)
- [Mike Senior, Chapter 5 sample: mix preparation](https://docs.cambridge-mt.com/MSFTSS/MixingSecretsForTheSmallStudio_MikeSenior_Chapter5.pdf)
- [Mike Senior, Chapter 9 examples: compression and automation](https://cambridge-mt.com/ms3/ch9/)
- [Bob Katz, *Mastering Audio: The Art and the Science*](https://www.routledge.com/Mastering-Audio-The-Art-and-the-Science/Katz/p/book/9780240818962)
- [Ian Shepherd, *Mastering Essentials*](https://productionadvice.co.uk/mastering-essentials/)
- [Official REAPER videos](https://www.reaper.fm/videos.php)
- [Official REAPER User Guide](https://www.reaper.fm/userguide.php)
