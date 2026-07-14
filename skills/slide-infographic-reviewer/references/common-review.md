# Common One-Page Review

Apply these rules to Prompt, Structural, and Rendered reviews. Diagnose the argument before visual polish.

## Contents

1. Review states
2. Diagnostic order
3. Severity and finding format
4. Compact output contract
5. Common anti-patterns

## Review States

Use one state for each applicable lens:

- `Blocking`: meaning or reading path is not recoverable without substantial inference.
- `Weak`: meaning is recoverable, but the page creates avoidable cognitive or delivery cost.
- `Sound`: the page works with only minor improvement opportunities.
- `Strong`: the page communicates the intended judgment quickly and coherently.
- `Not verified`: the selected mode cannot support the judgment.

Do not calculate a numeric total. One blocking thesis problem is not offset by several strong details.

## Diagnostic Order

### 1. Page Intent and Core Judgment

Recover:

1. The question answered by the page.
2. The complete judgment sentence.
3. The larger argument it supports, if known.
4. The one audience takeaway.

Check that the title states a judgment rather than only naming a topic, the page has one dominant point, and every major region advances that point.

### 2. Page Pattern and Reading Path

Identify the dominant pattern and verify that it matches the argument:

- Left-right: structure or evidence mapped to judgments.
- Top-bottom: conclusion followed by support.
- Center-convergence: surrounding elements support one center.
- Timeline or evolution: sequence and change matter.
- Matrix or comparison: stable dimensions expose differences.
- Another pattern: name its logic explicitly.

Check the intended first, second, and final stops. The page needs one main anchor: judgment, diagram, number, or comparison.

### 3. Diagram Purpose and Relationship Semantics

Treat a diagram as a structured expansion of the judgment, not a knowledge inventory.

Check:

- Every layer or region has a clear role.
- Nodes are included because they advance the judgment.
- Connectors express a named relationship such as support, supply, dependency, mapping, flow, coordination, or evolution.
- Layered architectures explain both what the layers are and how they connect.
- Complex middle layers form a speakable coordination chain rather than an unordered module pile.

Do not assume proximity communicates direction or causality.

### 4. Information Types and Granularity

Classify elements as product or actor, technical module, capability, metric, evidence, strategic judgment, role label, or group coordinate.

Check:

- The same type uses the same visual grammar.
- Different types are distinguishable.
- Parallel elements share one abstraction level.
- Product or actor names include short role definitions when names alone are insufficient.
- Layer titles act as coordinates rather than the main visual.

Do not present a broad application, enterprise platform, and narrow feature as equivalent peers.

### 5. Mapping and Alignment

Check semantic mapping:

- Left-right regions claiming correspondence use the same logical group count, order, and alignment.
- Every lower module in a top-bottom page supports the upper conclusion.
- Comparison rows and columns use stable dimensions and comparable evidence.
- Color, shape, and position encode the same meaning throughout.

Treat misalignment as a semantic fault when it pairs the wrong evidence and claim.

### 6. Evidence and Metrics

For every proof point, ask what claim it supports, which region owns it, whether it is the main story, and whether its visual weight matches its argumentative weight.

Use a standalone metric only when the number is the main narrative. Attach supporting metrics to the relevant module or judgment. Flag unsupported or ambiguous claims without independently fact-checking them.

### 7. Judgment Copy and Content Placement

Check:

- Judgment copy begins with a direct conclusion.
- Supporting copy adds a concrete product, mechanism, metric, or feature.
- Structural facts stay in the diagram.
- Strategic interpretation stays in the judgment area.
- Diagram and commentary do not duplicate each other without adding meaning.

Prefer one direct judgment plus one support sentence.

## Severity and Finding Format

- `P0 Blocking`: unclear or conflicting thesis, unrecoverable structure, misleading relationship, or evidence mapped to the wrong claim.
- `P1 Major`: weak hierarchy, inconsistent mapping, mixed types or granularity, unclear evidence role, broken reading flow, or density that hides the point.
- `P2 Polish`: local wording or craft issue with limited impact on meaning.

Write each finding as:

```md
### [P0/P1/P2] Short diagnosis
- Evidence: exact wording, region, relationship, or omission.
- Impact: comprehension or delivery cost.
- Fix: smallest concrete correction.
```

Report the smallest set of root causes. Do not repeat one problem as several symptoms.

## Compact Output Contract

Use this default structure:

```md
## Overall verdict
- Review target:
- Review mode:
- Evidence basis:
- One-sentence verdict:
- Core judgment recovered:
- Strongest existing element:
- Main communication risk:

## Top findings
### [P0/P1/P2] ...
- Evidence:
- Impact:
- Fix:

## Minimum effective revision
- Revised title, when needed:
- Recommended pattern and reading order:
- Keep:
- Move, regroup, weaken, or remove:
- Relationship and evidence treatment:

## Not verified
- Include only unavailable checks.
```

For complex pages only, add a diagnostic table covering intent, structure, relationships, information types, evidence, and the relevant mode-specific checks.

## Common Anti-Patterns

- Starting with color or spacing before finding the page's claim.
- Treating all visible elements as equally important.
- Recommending more cards or icons as a generic fix.
- Calling a page busy without identifying what to remove or regroup.
- Calling a title weak without proposing a judgment-style replacement.
- Assuming every number deserves a large metric card.
- Praising clean layers that do not express relationships.
- Confusing source accuracy with presentation quality.
- Rebuilding the whole page when one structural change solves the problem.
