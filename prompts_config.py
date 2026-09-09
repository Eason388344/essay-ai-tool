# prompts_config.py
# AI写作教练 - 文体配置与提示词工厂

# ============================================================
# 一、文体配置中心
# ============================================================

GENRE_CONFIG = {
    "议论文": {
        "label": "议论文",
        "icon": "📊",
        "dimensions": {
            "审题立意": 20,
            "结构与逻辑": 15,
            "语言表达": 15,
            "论据与内容": 10
        },
        "diagnose_prompt": """你是一位资深高考作文阅卷老师。请严格按以下标准对议论文进行评分（满分60分）：

【审题立意】（20分）：是否精准理解题目核心？是否存在概念置换、偷换主语？
【结构与逻辑】（15分）：层次是否分明？论证是否严密？是否有递进或对比逻辑？
【语言表达】（15分）：是否流畅精准？有无语病？节奏是否得当？
【论据与内容】（10分）：素材是否充实？阐释是否深入？是否有效支撑论点？

请按以下JSON格式输出（不要包含其他废话）：
{
  "score": 总分(整数),
  "detail": {"审题立意": 分数, "结构与逻辑": 分数, "语言表达": 分数, "论据与内容": 分数},
  "strengths": ["优点1(附原文证据)", "优点2", "优点3"],
  "weaknesses": ["不足1(附原文证据)", "不足2", "不足3"],
  "summary": "一句话总评(20字以内)"
}""",
        "revise_strategy": """修缮策略：
- 重点强化论点与论据的咬合
- 优化论证层次（递进/对比）
- 精炼语言，删除冗余表达
- 保持原文核心立场不变""",
        "system_prompt": "你是一位资深高考作文辅导老师，擅长精修议论文。只输出修缮后的文章正文。",
        "writing_tips": "议论文核心：明确的论点 + 严密的论证 + 有力的论据"
    },

    "记叙文": {
        "label": "记叙文",
        "icon": "📖",
        "dimensions": {
            "叙事技巧": 20,
            "描写生动性": 15,
            "语言表达": 15,
            "情感真挚度": 10
        },
        "diagnose_prompt": """你是一位资深语文教师。请严格按以下标准对记叙文进行评分（满分60分）：

【叙事技巧】（20分）：情节是否完整？是否有起伏？详略是否得当？
【描写生动性】（15分）：人物/环境描写是否具体？是否有画面感？
【语言表达】（15分）：语言是否流畅？是否有文学感染力？
【情感真挚度】（10分）：情感表达是否真实？是否打动读者？

请按以下JSON格式输出（不要包含其他废话）：
{
  "score": 总分(整数),
  "detail": {"叙事技巧": 分数, "描写生动性": 分数, "语言表达": 分数, "情感真挚度": 分数},
  "strengths": ["优点1(附原文证据)", "优点2", "优点3"],
  "weaknesses": ["不足1(附原文证据)", "不足2", "不足3"],
  "summary": "一句话总评(20字以内)"
}""",
        "revise_strategy": """修缮策略：
- 强化细节描写（五感：视觉/听觉/触觉/嗅觉/味觉）
- 优化叙事节奏（详略安排）
- 增强情感共鸣点
- 保持原文的真实感和个人风格""",
        "system_prompt": "你是一位资深语文教师，擅长指导记叙文写作。只输出修缮后的文章正文。",
        "writing_tips": "记叙文核心：具体的故事 + 生动的细节 + 真挚的情感"
    },

    "散文": {
        "label": "散文",
        "icon": "🌿",
        "dimensions": {
            "意境营造": 20,
            "语言韵味": 15,
            "结构美感": 15,
            "情感表达": 10
        },
        "diagnose_prompt": """你是一位资深语文教师。请严格按以下标准对散文进行评分（满分60分）：

【意境营造】（20分）：是否营造出独特的意境？情景是否交融？
【语言韵味】（15分）：语言是否优美？是否有节奏感和韵律感？
【结构美感】（15分）：结构是否浑然一体？起承转合是否自然？
【情感表达】（10分）：情感是否细腻？是否含蓄而有力量？

请按以下JSON格式输出（不要包含其他废话）：
{
  "score": 总分(整数),
  "detail": {"意境营造": 分数, "语言韵味": 分数, "结构美感": 分数, "情感表达": 分数},
  "strengths": ["优点1(附原文证据)", "优点2", "优点3"],
  "weaknesses": ["不足1(附原文证据)", "不足2", "不足3"],
  "summary": "一句话总评(20字以内)"
}""",
        "revise_strategy": """修缮策略：
- 强化意象的选取与组合
- 优化语言的节奏感和韵律
- 调整结构使其更自然流畅
- 保留原文的个人风格和情感基调""",
        "system_prompt": "你是一位资深语文教师，擅长指导散文写作。只输出修缮后的文章正文。",
        "writing_tips": "散文核心：独特的意境 + 优美的语言 + 真挚的情感"
    }
}


# ============================================================
# 二、年级策略
# ============================================================

def get_grade_strategy(grade="高三"):
    grade_map = {
        "高一": "侧重基础写作能力培养，语言流畅、结构完整即可。",
        "高二": "在基础之上强化逻辑思辨或文学表现力，要有一定深度。",
        "高三": "对标高考满分作文标准，立意深刻、结构严谨、语言精准。"
    }
    return grade_map.get(grade, grade_map["高三"])


# ============================================================
# 三、文风策略
# ============================================================

def get_style_prompt(style="标准"):
    style_map = {
        "标准": "采用稳健、理性的写作风格。",
        "批判犀利": "增强批判性语气，使用对比、质疑和反思措辞。",
        "文学抒情": "增强文学性，运用比喻、拟人、排比等修辞。",
        "逻辑严密": "强化因果链和演绎推理，多用'由此可见''究其本质'等连接词。"
    }
    return style_map.get(style, style_map["标准"])


# ============================================================
# 四、写作阶段提示词
# ============================================================

def build_idea_prompt(title, genre, grade="高三", additional_hint=""):
    """阶段一：构思破题"""
    genre_label = GENRE_CONFIG[genre]["label"]
    tips = GENRE_CONFIG[genre]["writing_tips"]
    return f"""你是一位经验丰富的写作导师。请帮助一位{grade}学生构思一篇{genre_label}。

【题目/话题】：{title}
{additional_hint}

【任务要求】：
请输出以下内容（结构清晰，便于学生理解）：

## 1. 破题角度（3个）
从不同视角切入题目，每个角度给出一个核心观点。

## 2. 写作提纲
为推荐的角度搭建一个清晰的写作框架。

## 3. 素材推荐（3-5个）
推荐与题目相关的素材（名言、事例、数据等），附简短说明。

## 4. 写作提醒
一句话提醒学生注意{genre_label}的核心要素：{tips}

请用中文输出，语气亲切鼓励，不要过于学术化。"""


def build_draft_prompt(title, genre, keywords_or_ideas, style="标准", grade="高三"):
    """阶段二：起草扩写"""
    genre_label = GENRE_CONFIG[genre]["label"]
    style_prompt = get_style_prompt(style)
    
    return f"""你是一位写作助手。请帮助一位{grade}学生将以下内容扩展成一篇完整的{genre_label}。

【题目/话题】：{title}
【学生提供的思路/关键词】：{keywords_or_ideas}
【目标文风】：{style_prompt}

【任务要求】：
1. 根据学生提供的思路，扩展成一篇结构完整的文章
2. 保持{genre_label}的基本特征：{GENRE_CONFIG[genre]['writing_tips']}
3. 语言要适合高中生的表达水平
4. 直接输出扩展后的文章正文，不要任何分析或说明"""


def build_diagnose_prompt(title, body, genre):
    """阶段三：诊断评分（根据文体动态生成）"""
    config = GENRE_CONFIG[genre]
    # 获取该文体的诊断提示词（已包含维度定义和JSON格式要求）
    return config["diagnose_prompt"]


def build_revise_prompt(title, body, diagnosis_text, genre, selected_options,
                        custom_instruction="", style="标准", calibration_note="",
                        sample_text="", target_paras=None, grade="高三"):
    """阶段三：修缮（根据文体动态生成）"""
    config = GENRE_CONFIG[genre]
    genre_label = config["label"]
    base_strategy = config["revise_strategy"]
    system_prompt = config["system_prompt"]
    
    # 预设方向
    option_map = {
        "1": "提升立意/中心思想的深度",
        "2": "优化结构/叙事的层次感",
        "3": "精炼语言表达，提升文采",
        "4": "充实内容/细节/论据"
    }
    instructions = [option_map[k] for k in sorted(selected_options) if k in option_map]
    base_instruction = "；".join(instructions) if instructions else "根据诊断结果自主判断优化方向"
    
    # 年级策略
    grade_strategy = get_grade_strategy(grade)
    style_prompt = get_style_prompt(style)
    
    # 可选参数
    custom_note = f"【用户特别定制】：{custom_instruction.strip()}" if custom_instruction and custom_instruction.strip() else ""
    calibration_context = f"\n【校准参考意见】：{calibration_note}" if calibration_note else ""
    sample_context = f"\n【参考范文/素材】：\n{sample_text}" if sample_text and sample_text.strip() else ""
    
    # 局部修缮
    if target_paras and len(target_paras) > 0:
        marked_original = body
        for para in target_paras:
            if para in body:
                marked_original = marked_original.replace(para, f"【待修改开始】\n{para}\n【待修改结束】")
        modification_instruction = f"""
【局部修缮模式】用户选定了以下段落（共{len(target_paras)}段），只修改这些段落：
{chr(10).join(['- ' + p[:50] + '...' for p in target_paras])}
请只修改被【待修改开始】和【待修改结束】标记的段落，其他部分一字不改。
"""
        output_instruction = "输出完整文章。被标记的段落已修改，其他部分一字不差照抄。"
    else:
        modification_instruction = "（全文修缮模式）"
        output_instruction = "输出修缮后的完整文章。"
    
    # 静默纠错
    silent_correction = """【静默纠错规则（必须执行，无需说明）】：
- 发现OCR导致的明显错别字，直接纠正
- 常见同音字错误（的/地/得）自动修正
- 无法确定的人名/地名/专有名词保持原样"""

    prompt = f"""【年级要求】：{grade_strategy}
【文体】：{genre_label}
【作文题目】：{title}

【原文】：
{marked_original if target_paras and len(target_paras) > 0 else body}

【诊断结果】：
{diagnosis_text}
{calibration_context}
{sample_context}

【修缮策略】：
{base_strategy}

【修缮综合指令】：
1. 基础方向：{base_instruction}
2. 整体文风：{style_prompt}
3. {custom_note if custom_note else "（无额外要求）"}
4. {modification_instruction}

{silent_correction}

【核心要求】：
{output_instruction}
只输出文章正文，不要任何分析过程。"""

    return prompt, system_prompt


# ============================================================
# 五、辅助函数：获取配置
# ============================================================

def get_genre_list():
    """获取所有文体列表"""
    return list(GENRE_CONFIG.keys())

def get_genre_dimensions(genre):
    """获取指定文体的评分维度"""
    config = GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])
    return config["dimensions"]

def get_genre_label(genre):
    return GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])["label"]

def get_genre_icon(genre):
    return GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])["icon"]

def get_genre_tips(genre):
    return GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])["writing_tips"]


# ============================================================
# 六、自检
# ============================================================
if __name__ == "__main__":
    print("✅ prompts_config.py 加载成功！")
    print("📚 支持文体：", get_genre_list())
    for g in get_genre_list():
        dims = get_genre_dimensions(g)
        print(f"   {get_genre_icon(g)} {get_genre_label(g)}: {list(dims.keys())}")
