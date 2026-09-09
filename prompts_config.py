# prompts_config.py
# 所有提示词统一管理，按功能模块分离

DIAGNOSE_SYSTEM_PROMPT = """你是一位资深高考作文阅卷老师。请严格按以下标准对作文进行评分（满分60分）：

【审题立意】（20分）：是否精准理解题目核心？是否存在概念置换、偷换主语？
【结构与逻辑】（15分）：层次是否分明？论证是否严密？
【结构与逻辑】（15分）：层次是否分明？论证是否严密？
【语言表达】（15分）：是否流畅精准？有无语病？
【论据与内容】（10分）：素材是否充实？阐释是否深入？

请按以下JSON格式输出（确保是有效JSON，不要包含其他废话）：
{{
  "score": 总分(整数),
  "detail": {{"立意": 分数, "结构": 分数, "语言": 分数, "论据": 分数}},
  "strengths": ["优点1(需附带原文证据)", "优点2", "优点3"],
  "weaknesses": ["不足1(需附带原文证据)", "不足2", "不足3"],
  "summary": "一句话总评(20字以内)"
}}"""


REVISE_SYSTEM_PROMPT = """你是一位资深高考作文辅导老师，擅长根据多维指令精修议论文。
你的核心能力：
1. 保持原文的核心论点和主体框架不变
2. 根据具体指令进行针对性优化
3. 输出语言流畅、逻辑严密的高质量文章
4. 只输出修缮后的文章正文，不要任何分析过程或开场白"""


def get_style_prompt(style="标准"):
    """获取文风指令"""
    style_map = {
        "标准": "采用高考一类文的稳健、理性风格。",
        "批判犀利": "增强批判性语气，使用更强的对比、质疑和反思措辞，凸显思辨张力。",
        "文学抒情": "增强文学性，运用比喻、拟人、排比等修辞，使语言更具感染力和画面感。",
        "逻辑严密": "强化因果链、演绎推理，多用'由此可见''究其本质''反观当下'等逻辑连接词。"
    }
    return style_map.get(style, style_map["标准"])


def get_grade_strategy(grade="高三"):
    """年级差异化策略（预留接口）"""
    grade_map = {
        "高一": "侧重基础写作能力培养，语言流畅、结构完整即可。",
        "高二": "在基础之上强化逻辑思辨，观点要有一定深度。",
        "高三": "对标高考满分作文标准，立意深刻、结构严谨、语言精准、论据充实。"
    }
    return grade_map.get(grade, grade_map["高三"])


def build_revise_prompt(title, body, diagnosis_text, selected_options, 
                        custom_instruction, style, calibration_note="", 
                        sample_text="", target_paras=None, grade="高三"):
    """
    构建修缮提示词
    所有参数在此组装成完整prompt
    """
    # 预设方向映射
    option_map = {
        "1": "提升思维深度：运用概念界定、三级追问、批判反思等方法，让立意更深刻。",
        "2": "优化文章结构：按递进式或对比式逻辑重组段落，使层次清晰，逻辑推进感强。",
        "3": "精炼语言表达：替换模糊词汇，优化长短句节奏，消除语病。",
        "4": "充实论据阐释：剪裁现有素材，增加假设追问，强化论据与论点的咬合。"
    }
    instructions = [option_map[k] for k in sorted(selected_options) if k in option_map]
    base_instruction = "；".join(instructions) if instructions else "无预设方向"
    
    # 年级策略
    grade_strategy = get_grade_strategy(grade)
    
    # 文风
    style_instruction = get_style_prompt(style)
    
    # 自定义指令
    custom_note = f"【用户特别定制要求】：{custom_instruction.strip()}" if custom_instruction and custom_instruction.strip() else ""
    
    # 校准备注
    calibration_context = f"\n【校准参考意见】：{calibration_note}" if calibration_note else ""
    
    # 范文参考
    sample_context = f"\n【参考范文/素材（请模仿其风格或结构）】：\n{sample_text}" if sample_text and sample_text.strip() else ""
    
    # 局部修缮
    if target_paras and len(target_paras) > 0:
        marked_original = body
        for para in target_paras:
            if para in body:
                marked_original = marked_original.replace(para, f"【待修改开始】\n{para}\n【待修改结束】")
        modification_instruction = f"""
【局部修缮模式】
用户选定了以下段落要求修改（共{len(target_paras)}段），其他段落必须一字不改地保留：
---已选定段落预览---
{chr(10).join(['第' + str(i+1) + '段：' + p[:50] + '...' for i, p in enumerate(target_paras)])}
---
请只修改被【待修改开始】和【待修改结束】标记的段落，其余部分完全照抄原文。
被修改的段落可以重写、润色、调整逻辑。
"""
        output_instruction = "输出完整的修改后文章。被标记的段落已修改，其他部分一字不差照抄。"
    else:
        modification_instruction = "（全文修缮模式：全面优化整篇文章）"
        output_instruction = "输出修缮后的完整文章。"

    # 组装最终Prompt
    prompt = f"""【年级要求】：{grade_strategy}
【作文题目】：{title}

【原文】：
{marked_original if target_paras and len(target_paras) > 0 else body}

【诊断结果】：
{diagnosis_text}
{calibration_context}
{sample_context}

【修缮综合指令】：
1. 基础方向：{base_instruction}
2. 整体文风：{style_instruction}
3. {custom_note if custom_note else "（无额外自定义要求）"}
4. {modification_instruction}

【核心要求】：
{output_instruction}"""

    return prompt


def build_revision_plan_prompt(title, body, diagnosis_text, selected_options, custom_instruction, style):
    """生成修改计划的提示词"""
    option_map = {"1": "提升思维深度", "2": "优化文章结构", "3": "精炼语言表达", "4": "充实论据阐释"}
    options_desc = "、".join([option_map.get(k, "") for k in sorted(selected_options) if k in option_map])
    style_map = {"标准": "稳健理性", "批判犀利": "批判思辨", "文学抒情": "文学抒情", "逻辑严密": "逻辑严谨"}
    style_desc = style_map.get(style, "稳健理性")
    
    return f"""【作文题目】：{title}
【原文摘要】：{body[:300]}...
【诊断结果】：{diagnosis_text[:500]}

请制定一份修改计划（100字以内），包含：
1. 修改目标（结合方向：{options_desc or '自定义'}，文风：{style_desc}）
2. 关键修改点（3-5个要点）

输出格式（纯文本）：
修改目标：...
关键修改点：
- ..."""


def build_calibration_prompt(title, body, original_diagnosis, dimension, deviation, comment):
    """构建校准提示词"""
    return f"""【作文题目】：{title}
【原文】：{body}
【AI原始评分】：{original_diagnosis}
【教师反馈】：维度“{dimension}”认为AI评分 {deviation}，补充说明：{comment}

请重新审视这篇作文。输出新的评分JSON：
{{"score": 总分, "detail": {{"立意": 分数, "结构": 分数, "语言": 分数, "论据": 分数}}, "summary": "校准后的总评"}}"""


def build_ocr_prompt():
    """OCR识别提示词"""
    return """请精准识别图片中的全部手写文字。图片中包含了【作文题目】和【学生作文正文】两部分。
请严格按以下格式输出，不要包含任何额外说明或开场白：

===题目===
（在这里粘贴识别出的作文题目全文）

===正文===
（在这里粘贴识别出的学生作文全文）"""
