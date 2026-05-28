# Style Options

Offer this selector when the user has not specified a color system or style.

Default recommendation: **A. Classic Business Red-Black-Gray**.

## A. Classic Business Red-Black-Gray

Best for model briefs, benchmarks, AI product launches, technical architecture, executive summaries.

- Theme: “经典商务红黑灰”. Strictly keep the palette inside red, black, white, and gray unless the user explicitly approves another color.
- Primary accent: `#C7000B` (PANTONE 185C, RGB 199/0/11) for titles, critical keywords, process lines, arrows, key numbers, and core emphasis.
- Background/base: pure white `#FFFFFF`; light gray `#F5F5F5` for panels/cards; medium gray `#E0E0E0` for dividers, axes, and subtle borders.
- Text/contrast: deep black `#1A1A1A` or `#333333` for body text. Emphasized body points, numbers, and metrics use bold black or bold red.
- Cards: white or `#F5F5F5`, thin gray border `#E0E0E0`, minimal shadow if needed.
- Feeling: sober, premium, executive business brief, high-contrast, readable, disciplined.

## B. Light Cool Consulting

Use only if the user prefers a cooler consulting palette over the default red-black-gray system.

- Background: cool white `#F6F8FC`, pale blue tint `#EEF3FB`.
- Accent: deep academic blue `#0F3D91`.
- Highlight: amber `#F59E0B`.
- Cards: white, thin slate border `#CBD5E1`, subtle shadow.
- Feeling: rational, premium, consulting research brief, executive-readable.

## C. Light Warm Strategy Memo

Best for product strategy, industry trend, business model, ecosystem analysis.

- Background: warm off-white `#FAF7F0`, light paper grid.
- Accent: clay orange `#C76A3A` or warm brown `#7C4A2D`.
- Highlight: golden amber `#D89A2B`.
- Cards: ivory, warm thin border, paper-like texture.
- Feeling: strategic memo, thoughtful, high-level, human but still analytical.

## D. Light Minimal Research Card

Best for dense material, high readability, clean executive decks.

- Background: pure white or near-white.
- Accent: black/slate plus one restrained color.
- Highlight: one color only for key numbers.
- Cards: minimal borders, more whitespace, fewer icons.
- Feeling: clean, sober, high signal, less decorative.

## E. Dark Technical Brief

Use only when the user chooses dark style or the topic strongly benefits from it.

- Background: deep blue/green/blackboard.
- Accent: pale cyan or chalk white.
- Highlight: orange/yellow.
- Cards: outlined dark panels, line icons, arrows, large type.
- Feeling: engineering keynote, technical evolution, system map.

## Style Selection Prompt

If the user has not specified style, ask:

```text
请先确认信息图配色体系：
A. 经典商务红黑灰（默认，严控红/黑/白/灰边界；主色 #C7000B）
B. 浅色冷静咨询风（蓝灰/琥珀，适合技术/产品/benchmark）
C. 浅色暖调战略备忘录风（适合商业/行业/生态）
D. 浅色极简研究卡风（适合高密度信息）
E. 深色技术演示风（可选，不默认）

请回复选项或确认默认 A 后，我再继续。
```
