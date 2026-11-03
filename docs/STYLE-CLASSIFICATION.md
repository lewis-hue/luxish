# Style classification

What the app can and cannot say about the style of an outfit, and how well it
says it. Numbers here come from `services/api/scripts/eval_style.py` against
the hand-labelled corpus in `datasets/style/`.

## The model is not trained, and cannot be

`muse-spark-1.3` and `sam-3.1` are hosted inference. There is no training or
fine-tuning endpoint, and the adapter whitelists request parameters by name
(ADR-006, ADR-007). So nothing in this project is trained on the corpus.

That is not a gap to be closed later by trying harder. It is the shape of the
provider, and it decides what a labelled corpus is *for* here:

- **measuring accuracy**, which the project previously had no way to do;
- **grounding the prompt** in the vocabulary a human labeller actually used.

Both are real. Neither is training, and calling them training would make the
next person expect a model artefact that does not exist.

## The labels were collapsed, on purpose

The corpus folders encode style crossed with the wearer's identity. The same
clothes appear three times:

```
LGBT CASUAL WEAR  = 13      MEN CASUAL  = 10      WOMEN CASUAL  = 12
LGBT ELEGANT WEAR = 15      MEN ELEGANT = 11      WOMEN ELEGANT = 13
```

Those are one style. Keeping them apart would mean building something that
claims to read gender or sexual orientation off clothing, which is:

- **wrong**, because clothing does not encode identity, and outfits move with
  trend, culture and individual expression while the inference would not;
- **incoherent with the system**, because the outfit detector's prompt already
  forbids reporting anything about the person, and a model whose labels force
  it to predict identity cannot honour that rule at inference time;
- **worse data**, because collapsing gives eight classes of 13 to 40 images
  instead of twenty of nought to sixteen.

`COLORS YOU CAN MATCH` is excluded as well: it is a colour-pairing reference,
not a style of dress, so scoring a style classifier against it measures
nothing.

## Where it stands

Forty photographs, five per class, seeded so a prompt change is measured
against a moved prompt rather than a moved sample.

| prompt | sample | accuracy | notes |
|---|---|---|---|
| `style.v1` | 40 | 52.5% | `sport` 0%. Every sport image called streetwear. |
| `style.v2` | 40 | 57.5% | `sport` 60%. Ten images lost to a token cap, then fixed. |
| `style.v3` | 40 | 53.8% | **Worse. Reverted.** See below. |
| `style.v2` | **225** | **50.2%** | The full corpus. See *The sample was flattering*. |

Random choice across eight classes is 12.5%.

### The sample was flattering, by seven points

The 57.5% above rests on forty images, five per class. Run against all 225
scorable ones it is **50.2%**, and that gap is the single most useful thing
this harness has produced: every prompt decision before now was made on
differences of three to five points measured on a sample whose own error is
larger than that. Two images failed outright and are excluded.

Per-image answers are written to `datasets/style-eval.jsonl` as the run goes,
so a 225-call run can be re-analysed without paying for it again.

**v1's failure was the prompt, not the model.** It defined streetwear as
including "layered sportswear worn off the pitch", which swallows the entire
sport class by definition. v2 makes the definitions disjoint and gives them a
test order, so a kaftan is heritage before it is modest, and a tracksuit is
sport before it is streetwear.

**The token cap bit again.** Spelling out eight styles made the prompt long
enough that ten of forty answers came back empty with `finish_reason:
length` — the cap covers reasoning tokens, which this model spends before it
emits anything. Raised 2048 to 4096. This is the third time that mistake has
appeared in this codebase, after categorisation at 512 and the stylist at
1200.

### Two classes are eating the others

The confusion table is not noise scattered evenly. Two labels are predicted
roughly twice as often as they are true, and they absorb almost everything
else:

| label | true | predicted | ratio |
|---|---|---|---|
| streetwear | 40 | 78 | **1.95x** |
| elegant | 38 | 69 | **1.82x** |
| occasion | 24 | 19 | 0.79x |
| modest | 14 | 9 | 0.64x |
| official | 34 | 15 | **0.44x** |
| sport | 27 | 11 | **0.41x** |
| casual | 35 | 11 | **0.31x** |
| heritage | 13 | 13 | 1.00x |

Recall tells the same story from the other side: streetwear 90% and heritage
85%, against casual 23%, official 26% and sport 33%. The model is not
uniformly mediocre — it is confident and wrong in a specific direction.

### A quarter of the corpus is a labelling disagreement, not a model failure

Collapsing the pairs a human labeller could defend either way, after the fact:

| merged | accuracy |
|---|---|
| nothing (as scored) | 50.2% |
| `official` with `elegant` | 60.9% |
| ...and `occasion` with `elegant` | 66.7% |
| ...and `sport` with `streetwear` | **75.1%** |

**Read that carefully, because it is easy to overclaim.** 75.1% is what you
get by merging labels *after* scoring an eight-class prompt. It is not what a
five-class prompt would score — that has not been measured, and a shorter
taxonomy might do better (less to confuse) or worse (fewer edges to hang a
definition on). What it does establish is that roughly **25 points of the
"error" is the taxonomy, not the model**: on a quarter of the corpus the
model's answer is one a careful person could also have given.

That makes the most promising next move a different experiment from the one
this document previously recommended.

### Recall by style, at v2

```
streetwear  100%      elegant   80%      occasion  60%
heritage     80%      sport     60%      modest    40%
casual       20%      official  20%
```

### v3 was a failed hypothesis, and that is worth recording

The obvious read of v2's errors was that `streetwear` needed a tighter fence,
so v3 added explicit negatives ("not simply any casual outfit, not any outfit
a young person would wear") and named `casual` as the default to fall back to.

It made things worse: **53.8%**, with `streetwear` recall falling from 100% to
60%. The negatives overcorrected into under-prediction, and naming `casual` as
the default did not lift `casual` recall at all, which it stayed at 40%.

Reverted to v2. The lesson is not that negatives never work; it is that the
cheap fix for an over-predicted class is not obviously a fence around it, and
that without the harness this would have shipped as an improvement because it
reads like one.

### What is still wrong

```
casual   -> streetwear  3
official -> elegant     3
modest   -> streetwear  2
occasion -> elegant      2
sport    -> streetwear  2
```

Two things, and they are different in kind.

**Streetwear is over-predicted.** Seven of the seventeen errors land on it.
The model reaches for it whenever an outfit is casual and has any visual
interest at all.

**`official` against `elegant` is a contested boundary, not an error.** A
labeller put workplace suiting in `official`; the model calls it `elegant`,
which is also defensible. The same is true of `occasion` against `elegant`.
Some of the remaining 42.5% is label disagreement rather than model failure,
and chasing it with prompt changes alone will plateau.

### Confidence carries no information, and that is now measured

Across all 225 answers, **not one came back under 0.5**. The separation
between right and wrong is:

```
confidence when right : min 0.85   mean 0.921
confidence when wrong : min 0.78   mean 0.895
```

A 2.6-point gap on a 0-to-1 scale, with the ranges overlapping almost
completely. There is no threshold that separates a right answer from a wrong
one, so **confidence must not be used as a gate**: "show the style only when
confident" would show wrong styles at exactly the same rate as right ones
while implying it had filtered them. Either show it with the honest caveat
that it is a guess, or do not show it.

This was previously asserted from forty images. It is now measured on 225.

## The decision: it is not wired to anything

**Status: measured, not shipped.** Nothing in the product calls this
classifier, and that is a decision rather than an omission.

At 50.2%, with one class predicted twice as often as it is true and a
confidence score that cannot tell a right answer from a wrong one, there is no
honest way to put a style label in front of somebody. The two framings both
fail:

* *Show it as fact* — half of what people read would be wrong, about their
  own clothes, which is the kind of wrong that is immediately obvious to the
  one person who can check it.
* *Show it only when confident* — there is no "confident". The score does not
  separate.

What it is genuinely good for is what it was built for: **measuring**. The
harness turned a 57.5% that was never real into a 50.2% that is, caught a
prompt change that read like an improvement and was not, and located the
actual problem in the taxonomy rather than the model.

## Next, in order of likely return

1. **Test a five-class taxonomy directly.** Merge `official` into `elegant`
   and `sport` into `streetwear` *in the prompt and the labels*, and measure
   it, rather than inferring 75.1% from a post-hoc merge. This is now the
   first move rather than the third, because the evidence says the taxonomy
   is where a quarter of the error lives.
2. **Fence `streetwear` and `elegant` by what they are not.** Together they
   absorb 147 of 225 predictions. Note that `style.v3` already tried explicit
   negatives and made things worse, so this is the same hypothesis the
   harness has refuted once — try it only alongside (1), and measure.
3. **Re-label the contested boundaries with a second human pass**, so
   `official` against `elegant` can be treated as a model problem or
   dismissed as a labelling one on evidence rather than on inspection.
4. Nothing here is training. `muse-spark-1.3` is hosted inference with no
   fine-tuning endpoint, so every number above moves by changing the prompt
   or the taxonomy, and by nothing else.
