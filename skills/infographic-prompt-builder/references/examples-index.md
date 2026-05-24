# Examples Index

Use the images in `examples/` as visual references only. They are not source facts unless the user explicitly says to use their content as source material.

Default behavior:

- Do not open example images unless visual matching is requested or the chosen layout/style is unclear.
- Use at most 1-2 closest examples for a task to avoid context and visual drift.
- Treat historical prompt files as structure/style references only; never copy their claims, dates, benchmark numbers, or product facts into a new prompt.
- All current bundled image examples are vertical/poster-oriented visual references. For horizontal PPT-ratio tasks, do not imitate their vertical composition; use `references/prompt-horizontal-ppt-example.txt` and the horizontal pattern in `references/prompt-recipes.md`.

## Best References

- `kimi-2.6.png`: light cool consulting style, model brief, benchmark bars, pricing and technical levers, insight block.
- `老黄2026GTC演讲.png`: light keynote/event brief, spec strip, capability columns, performance/economics chart, key insights.
- `Claude Managed Agents.png`: single-product deep dive, architecture diagram, old-vs-new comparison, security process, performance proof, bottom conclusion.
- `Anthropic产品战略-顶尖编程模型到Agent全栈生态.png`: product strategy, pillar cards, product stack, flywheel, strategic conclusion.
- `Hermes-Agent-自进化学习闭环与Skills体系.png`: mechanism explainer, closed-loop learning diagram, mechanism cards, comparison, insight summary.
- `GLM-5.1-开源长程任务-8小时自主工作演进.png`: dark technical evolution narrative, timeline, benchmark cards, scenario validation.
- `扣子Coze-2.5-Agent-World-数字员工全景.png`: dark ecosystem panorama, three capability pillars, ecosystem route, bottom value judgment.

## Horizontal References

Use these user-curated examples for horizontal/landscape infographic composition. They are bundled inside this skill directory.

Important:

- These examples are horizontal `1536x1024` images, about 3:2 ratio. Use them for landscape composition, hierarchy, density, and style references.
- For horizontal PPT-ratio output, still generate `16:9, recommended 1920x1080px`; do not copy the 3:2 canvas ratio.
- Treat their prompt files as structure/style references only unless the user explicitly says to use their content as source material.

Best horizontal references:

- `examples/百炼推理服务.png` + `references/prompt-horizontal-百炼推理服务.txt`: Agent inference service platform, performance metrics, scheduling/serving architecture.
- `examples/模型训推能力.png` + `references/prompt-horizontal-模型训推能力.txt`: model training and inference capability panorama, infrastructure layers, capability comparison.
- `examples/千问模型.png` + `references/prompt-horizontal-千问模型.txt`: Qwen model family brief, model capability evolution, benchmark and product positioning.
- `examples/千问云.png` + `references/prompt-horizontal-千问云.txt`: Qwen Cloud / ATH strategy panorama, organization-to-product capability map.
- `examples/Agentic Data.png` + `references/prompt-horizontal-agentic-data.txt`: Agentic Cloud data plane and storage architecture, data-for-model and data-for-agent framing.

## Prompt References

- `references/prompt-kimi-2.6.txt`: complete prompt for a light cool model brief.
- `references/prompt-gtc-2026.txt`: complete prompt for a light cool keynote/performance brief.
- `references/prompt-horizontal-ppt-example.txt`: horizontal 16:9 PPT-ratio prompt skeleton for slide-like landscape infographics.
- `references/source-guide.md`: original Chinese production manual and methodology.
