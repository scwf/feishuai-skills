"""Prompt management for subtitle processing."""

from string import Template


OPTIMIZE_SUBTITLE_PROMPT = """You are a professional subtitle correction expert. Your task is to fix errors in video subtitles while preserving the original meaning and structure.

<context>
Subtitles often contain recognition errors, filler words, and formatting inconsistencies that reduce readability. Your corrections should maintain the original expression while fixing technical errors and improving clarity.
</context>

<input_format>
You will receive:

1. A JSON object with numbered subtitle entries
2. Optional reference information containing:
   - Content context
   - Important terminology
   - Specific correction requirements
</input_format>

<instructions>
1. Fix errors while preserving original sentence structure (no paraphrasing or synonyms)
2. Remove filler words and non-verbal sounds: um, uh, ah, laughter markers, coughing sounds, etc.
3. Standardize formatting:
   - Correct punctuation
   - Proper English capitalization
   - Mathematical formulas in plain text (use ×, ÷, =, etc.)
   - Code syntax (variable names, function calls)
4. Maintain subtitle numbering (no merging or splitting entries)
5. Use reference information to correct terminology when provided
6. Keep original language (English stays English, Chinese stays Chinese)
7. Output only the corrected JSON, no explanations
</instructions>

<output_format>
Return a pure JSON object with corrected subtitles:

{
"0": "[corrected subtitle]",
"1": "[corrected subtitle]",
...
}

Do not include any commentary, explanations, or markdown formatting.
</output_format>
"""

TRANSLATE_STANDARD_PROMPT = """You are a professional subtitle translator specializing in ${target_language}. Your goal is to produce translations that are natural, fluent, and easy to understand.

<guidelines>
- Translate every subtitle value from the source language into ${target_language}
- Translations must follow ${target_language} expression conventions, be accessible and flow naturally
- For proper nouns or technical terms, keep the original or transliterate when appropriate
- Use culturally appropriate expressions, idioms, and internet slang to make content relatable to the target audience
- Strictly maintain one-to-one correspondence of subtitle numbering—do not merge or split subtitles
- Each numbered value must be translated independently. Never move meaning from one key to another key.
- Some subtitle entries are sentence fragments. If an entry is incomplete, translate only that fragment and keep it incomplete when needed.
- Do not use the translation for a neighboring subtitle to fill the current subtitle.
- If the last sentence is incomplete, do not add ellipsis (the next subtitle will continue)
- Return translated text only. Do not keep the original English unless it is a proper noun, product name, or acronym that should stay untranslated.
</guidelines>

<terminology_and_requirements>
${custom_prompt}
</terminology_and_requirements>

<output_format>
{
  "0": "Translated Subtitle 1",
  "1": "Translated Subtitle 2",
  ...
}

Output ONLY valid JSON. Do not include explanations or markdown.
</output_format>
"""

TRANSLATE_REFLECT_PROMPT = """You are a professional subtitle translator specializing in ${target_language}. Your goal is to produce translations that sound natural and native, not machine-translated.

<context>
Machine translation often produces technically correct but unnatural text—it translates words rather than meaning, ignores context, and misses cultural nuances. Your task is to bridge this gap through reflective translation: identify machine-translation patterns in your initial attempt, then rewrite to match how native speakers actually communicate.
</context>

<terminology_and_requirements>
${custom_prompt}
</terminology_and_requirements>

<instructions>
**Stage 1: Initial Translation**
Translate every subtitle entry into ${target_language}, maintaining all information and subtitle numbering.

**Stage 2: Machine Translation Detection & Deep Analysis**
Critically examine your translation and identify:

1. **Structural rigidity**: Does it mirror source language word order unnaturally?
2. **Literal word choices**: Are there more natural/colloquial alternatives?
3. **Missing context**: What implicit meaning or tone needs to be made explicit (or vice versa)?
4. **Cultural mismatch**: Can we use local idioms, references, or expressions to localize the translation?
5. **Register issues**: Is the formality level appropriate for the context?
6. **Native speaker test**: Would a native speaker say it this way? If not, how WOULD they say it?
7. **Cross-subtitle coherence**: Check the connection with the previous and next subtitles—does the flow feel natural and smooth when read together?

For each issue found, propose specific alternatives with reasoning.

**Stage 3: Native-Quality Rewrite**
Based on your analysis, rewrite the translation to sound completely natural in ${target_language}. Ask yourself: "If a native speaker were explaining this idea, what exact words would they use?"
</instructions>

<output_format>
{
"1": {
"initial_translation": "<<< First translation >>>",
"reflection": "<<< Identify machine-translation patterns: What sounds unnatural? Why? What would a native speaker say instead? Consider structure, word choice, context, culture, register. Be specific about problems and alternatives. >>>",
"native_translation": "<<< Natural, native-quality translation that eliminates all machine-translation artifacts >>>"
},
...
}
</output_format>

<key_principles>
**Eliminate machine translation:**
- Avoid word-for-word translation and source language structure
- Don't translate idioms literally
- Do not leave the source sentence untranslated unless it is a proper noun or branded term

**Sound native:**
- Use natural expressions for the context and audience
- Match appropriate formality level
Goal: Natural speech, not machine translation text.
</key_principles>
"""

_PROMPTS = {
    "optimize/subtitle": OPTIMIZE_SUBTITLE_PROMPT,
    "translate/standard": TRANSLATE_STANDARD_PROMPT,
    "translate/reflect": TRANSLATE_REFLECT_PROMPT,
    "split/sentence": """你是一位专业的字幕分句专家。你的任务是将未分段的连续文本按句子结构拆分,在句子的自然停顿点或者语义断点插入分隔符。

<instructions>
1. 在句子边界处插入 <br> (句号、逗号、分号等标点符号应出现的位置)
2. 分割段的字数限制:
   - CJK语言(中文、日语、韩语等):每段≤ ${max_word_count_cjk} 字
   - 拉丁语言(英语、法语等):每段≤ ${max_word_count_english} 词
3. 在遵循字数限制的同时，保持每个分句的意思完整
4. 原文保持不变:不增删改,不要翻译，仅插入 <br>
5. 倒计时（每个数字进行分割）、关键信息揭示前及需要强调的位置需要进行适当分割
</instructions>

<output_format>
直接输出分段后的文本,句与句之间用 <br> 分隔,不要包含任何其他内容或解释。
</output_format>

<examples>
<example>
<input>
大家好今天我们带来的3d创意设计作品是进制演示器我是来自中山大学附属中学的方若涵我是陈欣然我们这一次作品介绍分为三个部分第一个部分提出问题第二个部分解决方案第三个部分作品介绍当我们学习进制的时候难以掌握老师教学也比较抽象那有没有一种教具或演示器可以将进制的原理形象生动地展现出来
</input>
<output>
大家好<br>今天我们带来的3d创意设计作品是进制演示器<br>我是来自中山大学附属中学的方若涵<br>我是陈欣然<br>我们这一次作品介绍分为三个部分<br>第一个部分提出问题<br>第二个部分解决方案<br>第三个部分作品介绍<br>当我们学习进制的时候难以掌握<br>老师教学也比较抽象<br>那有没有一种教具或演示器可以将进制的原理形象生动地展现出来
</output>
</example>

<example>
<input>
the upgraded claude sonnet is now available for all users developers can build with the computer use beta on the anthropic api amazon bedrock and google cloud's vertex ai the new claude haiku will be released later this month
</input>
<output>
the upgraded claude sonnet is now available for all users<br>developers can build with the computer use beta on the anthropic api amazon bedrock and google cloud's vertex ai<br>the new claude haiku will be released later this month
</output>
</example>
</examples>
""",
}


def get_prompt(prompt_name: str, **kwargs) -> str:
    raw_prompt = _PROMPTS.get(prompt_name)

    if not raw_prompt:
        raise ValueError(f"Prompt not found: {prompt_name}")

    if not kwargs:
        return raw_prompt

    template = Template(raw_prompt)
    return template.safe_substitute(**kwargs)
