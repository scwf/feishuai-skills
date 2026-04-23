# Style Options

Offer this selector when the user has not specified a style.

Default recommendation: **A. Light Cool Consulting**.

## A. Light Cool Consulting

Best for model briefs, benchmarks, AI product launches, technical architecture, executive summaries.

- Background: cool white `#F6F8FC`, pale blue tint `#EEF3FB`.
- Accent: deep academic blue `#0F3D91`.
- Highlight: amber `#F59E0B`.
- Cards: white, thin slate border `#CBD5E1`, subtle shadow.
- Feeling: rational, premium, consulting research brief, executive-readable.

## B. Light Warm Strategy Memo

Best for product strategy, industry trend, business model, ecosystem analysis.

- Background: warm off-white `#FAF7F0`, light paper grid.
- Accent: clay orange `#C76A3A` or warm brown `#7C4A2D`.
- Highlight: golden amber `#D89A2B`.
- Cards: ivory, warm thin border, paper-like texture.
- Feeling: strategic memo, thoughtful, high-level, human but still analytical.

## C. Light Minimal Research Card

Best for dense material, high readability, clean executive decks.

- Background: pure white or near-white.
- Accent: black/slate plus one restrained color.
- Highlight: one color only for key numbers.
- Cards: minimal borders, more whitespace, fewer icons.
- Feeling: clean, sober, high signal, less decorative.

## D. Dark Technical Brief

Use only when the user chooses dark style or the topic strongly benefits from it.

- Background: deep blue/green/blackboard.
- Accent: pale cyan or chalk white.
- Highlight: orange/yellow.
- Cards: outlined dark panels, line icons, arrows, large type.
- Feeling: engineering keynote, technical evolution, system map.

## Style Selection Prompt

If the user has not specified style, ask:

```text
请选择信息图风格：
A. 浅色冷静咨询风（默认，适合技术/产品/benchmark）
B. 浅色暖调战略备忘录风（适合商业/行业/生态）
C. 浅色极简研究卡风（适合高密度信息）
D. 深色技术演示风（可选，不默认）

如果你不选，我将默认使用 A。
```
