import streamlit as st
import os
import base64
import time
import json
import re
import statistics
import difflib
from datetime import datetime
from io import BytesIO
from PIL import Image
from openai import OpenAI

# ============================================================
# ⚠️ API Key 配置（仅从 secrets 读取，不在界面回显）
# ============================================================
DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "") if hasattr(st, "secrets") else ""
ZHIPU_API_KEY = st.secrets.get("ZHIPU_API_KEY", "") if hasattr(st, "secrets") else ""

st.set_page_config(page_title="AI作文批改研究平台", page_icon="📝", layout="wide")

# ============================================================
# 美化CSS
# ============================================================
st.markdown("""
<style>
    .score-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        border-radius: 10px;
        padding: 15px;
        margin: 5px 0;
    }
    .diff-add { background-color: #d4edda; color: #155724; padding: 2px 4px; border-radius: 3px; }
    .diff-remove { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; }
    .step-active { font-weight: bold; color: #0066cc; }
    .step-inactive { color: #999; }
    .para-checkbox {
        background: #f8f9fa;
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 6px;
        border-left: 3px solid #0066cc;
    }
    .para-checkbox:hover { background: #e9ecef; }
</style>
""", unsafe_allow_html=True)

# ====================== 日志记录 ==============================
def log_action(action_type, details=""):
    if "logs" not in st.session_state:
        st.session_state.logs = []
    st.session_state.logs.append({
        "timestamp": datetime.now().isoformat(),
        "type": action_type,
        "details": details
    })

# ====================== 图片压缩 ==============================
def compress_image(image_bytes, max_size=(1024, 1024), quality=85):
    img = Image.open(BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail(max_size, Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()

# ====================== 输入预检查 ==============================
def validate_input(title, body):
    if not title or not title.strip():
        return False, "题目不能为空"
    if not body or not body.strip():
        return False, "正文不能为空"
    word_count = len(body.strip())
    if word_count < 100:
        return False, f"正文仅{word_count}字，建议至少100字以保证诊断准确性"
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', body)
    chinese_ratio = len(chinese_chars) / max(len(body), 1)
    if chinese_ratio < 0.3:
        return False, "识别内容中汉字占比过低，请检查OCR结果或手动输入"
    return True, f"✅ 校验通过：正文{word_count}字，汉字占比{chinese_ratio:.1%}"

# ====================== 段落分割 ==============================
def split_paragraphs(text):
    if not text:
        return []
    raw_paras = re.split(r'\n\s*\n|\n', text)
    paras = [p.strip() for p in raw_paras if p.strip()]
    if len(paras) <= 1 and len(text) > 100:
        sentences = re.split(r'[。！？；]', text)
        paras = [s.strip() + '。' for s in sentences if s.strip()]
    return paras

def get_paragraph_preview(para, max_len=80):
    if len(para) <= max_len:
        return para
    return para[:max_len] + "..."

# ====================== OCR识别（智谱） ======================
@st.cache_data(show_spinner=False)
def recognize_image(image_bytes, api_key):
    if not api_key:
        raise ValueError("请先设置智谱API Key")
    compressed = compress_image(image_bytes)
    image_base64 = base64.b64encode(compressed).decode("utf-8")
    client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")
    for attempt in range(5):
        try:
            response = client.chat.completions.create(
                model="glm-4.6v-flash",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                        {"type": "text", "text": """请精准识别图片中的全部手写文字。图片中包含了【作文题目】和【学生作文正文】两部分。
请严格按以下格式输出，不要包含任何额外说明或开场白：

===题目===
（在这里粘贴识别出的作文题目全文）

===正文===
（在这里粘贴识别出的学生作文全文）"""}
                    ]
                }],
                max_tokens=2048,
                temperature=0.1
            )
            raw_text = response.choices[0].message.content
            title_match = re.search(r'===题目===\s*(.*?)\s*===正文===', raw_text, re.DOTALL)
            body_match = re.search(r'===正文===\s*(.*?)$', raw_text, re.DOTALL)
            title = title_match.group(1).strip() if title_match else "未识别到题目"
            body = body_match.group(1).strip() if body_match else raw_text.strip()
            return {"title": title, "body": body}
        except Exception as e:
            if "429" in str(e):
                time.sleep((attempt + 1) * 5)
            else:
                raise e
    raise RuntimeError("识别重试失败")

# ====================== 核心诊断（DeepSeek） ======================
def extract_json(text):
    try:
        try:
            import json_repair
            return json_repair.repair_json(text)
        except (ImportError, Exception):
            pass
        text = text.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'^```\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return text[start:end+1]
        raise ValueError("未找到有效的JSON")
    except Exception as e:
        raise ValueError(f"JSON解析失败: {e}")

def single_diagnose(title, body, api_key, temperature=0.3):
    system_prompt = """你是一位资深高考作文阅卷老师。请严格按以下标准对作文进行评分（满分60分）：

【审题立意】（20分）：是否精准理解题目核心？是否存在概念置换、偷换主语？
【结构与逻辑】（15分）：层次是否分明？论证是否严密？
【语言表达】（15分）：是否流畅精准？有无语病？
【论据与内容】（10分）：素材是否充实？阐释是否深入？

请按以下JSON格式输出（确保是有效JSON，不要包含其他废话）：
{
  "score": 总分(整数),
  "detail": {"立意": 分数, "结构": 分数, "语言": 分数, "论据": 分数},
  "strengths": ["优点1(需附带原文证据)", "优点2", "优点3"],
  "weaknesses": ["不足1(需附带原文证据)", "不足2", "不足3"],
  "summary": "一句话总评(20字以内)"
}"""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"作文题目：{title}\n\n学生作文：{body}"}
            ],
            temperature=temperature,
            max_tokens=800
        )
        raw = response.choices[0].message.content
        return json.loads(extract_json(raw))
    except Exception as e:
        raise RuntimeError(f"诊断API调用失败: {e}")

def diagnose_with_reliability(title, body, api_key, runs=3):
    raw_results = []
    temps = [0.1, 0.3, 0.5] * ((runs // 3) + 1)
    for i in range(runs):
        try:
            temp = temps[i % len(temps)]
            raw = single_diagnose(title, body, api_key, temp)
            raw_results.append(raw)
        except Exception as e:
            st.warning(f"第{i+1}次诊断调用失败: {e}")
            continue
    if len(raw_results) < 2:
        raise RuntimeError("有效诊断次数不足，请检查API或网络")
    scores = [r["score"] for r in raw_results]
    avg_score = round(statistics.mean(scores), 1)
    std_score = round(statistics.stdev(scores) if len(scores) > 1 else 0, 2)
    main_diagnosis = raw_results[0]
    main_diagnosis["reliability"] = {
        "avg_score": avg_score,
        "std_score": std_score,
        "is_reliable": std_score <= 2.0,
        "runs": len(raw_results)
    }
    return main_diagnosis

def quick_diagnose(title, body, api_key):
    return single_diagnose(title, body, api_key, temperature=0.3)

# ====================== 人机校准 ==============================
def recalibrate_score(title, body, original_diagnosis, dimension, deviation, comment, api_key):
    prompt = f"""【作文题目】：{title}
【原文】：{body}
【AI原始评分】：{json.dumps(original_diagnosis, ensure_ascii=False)}
【教师反馈】：维度"{dimension}"认为AI评分 {deviation}，补充说明：{comment}
请重新审视这篇作文。输出新的评分JSON：
{{"score": 总分, "detail": {{"立意": 分数, "结构": 分数, "语言": 分数, "论据": 分数}}, "summary": "校准后的总评"}}"""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=600
        )
        return json.loads(extract_json(response.choices[0].message.content))
    except Exception as e:
        raise RuntimeError(f"校准失败: {e}")

# ====================== 修改计划（思维链） ==============================
def get_revision_plan(title, body, diagnosis_text, selected_options, custom_instruction, writing_style, api_key):
    option_map = {"1": "提升思维深度", "2": "优化文章结构", "3": "精炼语言表达", "4": "充实论据阐释"}
    options_desc = "、".join([option_map.get(k, "") for k in sorted(selected_options) if k in option_map])
    style_prompt_map = {"标准": "稳健理性", "批判犀利": "批判思辨", "文学抒情": "文学抒情", "逻辑严密": "逻辑严谨"}
    style_desc = style_prompt_map.get(writing_style, "稳健理性")
    prompt = f"""【作文题目】：{title}
【原文摘要】：{body[:300]}...
【诊断结果】：{diagnosis_text[:500]}
请制定一份修改计划（100字以内），包含：
1. 修改目标（结合方向：{options_desc or '自定义'}，文风：{style_desc}）
2. 关键修改点（3-5个要点）
输出格式（纯文本，不要JSON）：
修改目标：...
关键修改点：
- ..."""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception:
        return "（生成计划失败，可直接执行修缮）"

# ====================== 修缮引擎（支持局部修缮） ==============================
def revise_essay(title, original_body, diagnosis_text, selected_options,
                 calibration_note="", custom_instruction="", writing_style="标准",
                 sample_text="", target_paragraphs=None, api_key=""):
    option_map = {
        "1": "提升思维深度：运用概念界定、三级追问、批判反思等方法，让立意更深刻。",
        "2": "优化文章结构：按递进式或对比式逻辑重组段落，使层次清晰，逻辑推进感强。",
        "3": "精炼语言表达：替换模糊词汇，优化长短句节奏，消除语病。",
        "4": "充实论据阐释：剪裁现有素材，增加假设追问，强化论据与论点的咬合。"
    }
    instructions = [option_map[key] for key in sorted(selected_options) if key in option_map]
    base_instruction = "；".join(instructions) if instructions else "（无预设方向）"

    style_prompt_map = {
        "标准": "采用高考一类文的稳健、理性风格。",
        "批判犀利": "增强批判性语气，使用更强的对比、质疑和反思措辞，凸显思辨张力。",
        "文学抒情": "增强文学性，运用比喻、拟人、排比等修辞，使语言更具感染力和画面感。",
        "逻辑严密": "强化因果链、演绎推理，多用'由此可见''究其本质''反观当下'等逻辑连接词。"
    }
    style_instruction = style_prompt_map.get(writing_style, style_prompt_map["标准"])

    custom_note = f"【用户特别定制要求】：{custom_instruction.strip()}" if custom_instruction and custom_instruction.strip() else ""
    calibration_context = f"\n【校准参考意见】：{calibration_note}" if calibration_note else ""
    sample_context = f"\n【参考范文/素材（请模仿其风格或结构）】：\n{sample_text}" if sample_text and sample_text.strip() else ""

    # ===== 局部修缮逻辑（加固） =====
    marked_original = original_body
    use_local = False

    if target_paragraphs and len(target_paragraphs) > 0:
        matched = 0
        temp = original_body
        for para in target_paragraphs:
            if para and para in temp:
                temp = temp.replace(para, f"【待修改开始】\n{para}\n【待修改结束】", 1)
                matched += 1
        if matched > 0:
            marked_original = temp
            use_local = True

    if use_local:
        modification_instruction = f"""
【局部修缮模式】
用户选定了以下段落要求修改（共{len(target_paragraphs)}段），其他段落必须一字不改地保留：
---已选定段落---
{chr(10).join(['第' + str(i+1) + '段：' + p[:50] + '...' for i, p in enumerate(target_paragraphs)])}
---

请只修改被【待修改开始】和【待修改结束】标记的段落，其余部分完全照抄原文。
被修改的段落可以重写、润色、调整逻辑，但必须保持与原段落字数相近（±20%）。
"""
        output_instruction = "输出完整的修改后文章。被标记的段落已修改，其他部分一字不差照抄。"
        source_text = marked_original
    else:
        modification_instruction = "（全文修缮模式：全面修改整篇文章）"
        output_instruction = "输出修缮后的完整文章。"
        source_text = original_body

    prompt = f"""【作文题目】：{title}
【原文】：
{source_text}
【诊断结果】：
{diagnosis_text}
{calibration_context}
{sample_context}

【修缮综合指令】：
1. 基础方向：{base_instruction}
2. 整体文风：{style_instruction}
3. {custom_note if custom_note else "（用户无额外自定义要求）"}
4. {modification_instruction}

【核心要求】：
{output_instruction}
不要任何分析过程或开场白，直接输出文章正文。"""

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一位资深高考作文辅导老师，擅长根据多维指令精修议论文。请只输出修缮后的文章正文。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.75,
            max_tokens=2048
        )
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(f"修缮API调用失败: {e}")

# ====================== 生成Diff对比 ==============================
def generate_diff_html(original, revised):
    diff = difflib.ndiff(original.splitlines(), revised.splitlines())
    html_parts = []
    for line in diff:
        if line.startswith('+ '):
            html_parts.append(f'<span class="diff-add">{line[2:]}</span>')
        elif line.startswith('- '):
            html_parts.append(f'<span class="diff-remove">{line[2:]}</span>')
        elif line.startswith('  '):
            html_parts.append(line[2:])
    return '<br>'.join(html_parts)

# ====================== 范文生成（新增功能） ==============================
GENRE_GUIDE = {
    "议论文": "中心论点鲜明，分论点递进或并列，论据充分（事实+道理论据），论证有层次",
    "记叙文": "选材典型，细节生动，情感真挚，叙事有波澜（起承转合）",
    "散文": "形散神聚，语言优美，情感细腻，意象丰富，有哲思升华",
}

STYLE_HINT = {
    "稳健理性": "语言克制、逻辑清晰、理性思辨",
    "批判犀利": "观点锋利、善用反问/对比、思辨张力强",
    "文学抒情": "修辞丰富、意象优美、情感饱满",
    "逻辑严密": "因果链清晰、善用'由此可见/究其本质'等连接词",
}

def generate_outline(title, genre, grade_level, style, api_key):
    prompt = f"""你是资深高中语文教师。请为下面这道作文题设计一份完整的构思提纲。

【作文题目】：{title}
【文体】：{genre}
【年级】：{grade_level}
【目标文风】：{STYLE_HINT.get(style, style)}
【文体要求】：{GENRE_GUIDE.get(genre, "")}

请严格按以下格式输出（纯文本，不要 JSON，不要开场白）：

一、破题立意
（用 1-2 句话点明最佳立意方向，要有深度，不要套话）

二、备选角度（3 个）
1. ...
2. ...
3. ...
（每个角度一句话）

三、推荐结构
开头：（怎么开，30字以内说明）
主体段一：（分论点/事件 + 用什么素材）
主体段二：（分论点/事件 + 用什么素材）
主体段三：（分论点/事件 + 用什么素材）
结尾：（怎么收，30字以内说明）

四、可用素材（3-5 个）
- ...
- ...
"""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=1200
    )
    return response.choices[0].message.content

def generate_model_essay(title, genre, grade_level, style, target_words, outline, api_key):
    prompt = f"""你是资深高中语文教师，请根据下面的构思提纲，写一篇完整的{genre}高分范文。

【作文题目】：{title}
【文体】：{genre}
【年级】：{grade_level}
【文风】：{STYLE_HINT.get(style, style)}
【字数要求】：{target_words}字左右

【构思提纲】：
{outline}

【写作要求】：
1. 开头直接入题，抓人，不要空话套话
2. 主体紧扣提纲，段与段之间要有逻辑推进
3. 语言符合"{style}"风格
4. 结尾有力，呼应开头，升华主题
5. 段落分明，每段之间用空行分隔

【输出要求】：
只输出范文正文。不要写"范文""标题"之类的前缀，不要任何分析或点评。"""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是资深高中语文教师，擅长写出高考一类文水准的范文。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=2500
    )
    return response.choices[0].message.content

def generate_essay_directly(title, genre, grade_level, style, target_words, api_key):
    prompt = f"""你是资深高中语文教师，请为下面的作文题写一篇完整的{genre}范文。

【作文题目】：{title}
【文体】：{genre}
【年级】：{grade_level}
【文风】：{STYLE_HINT.get(style, style)}
【字数要求】：{target_words}字左右
【文体要求】：{GENRE_GUIDE.get(genre, "")}

【写作要求】：
1. 开头直接入题，抓人
2. 主体有层次、有深度
3. 语言符合"{style}"风格
4. 结尾有力，升华主题
5. 段落分明，每段之间用空行分隔

【输出要求】：
只输出范文正文。不要写"范文""标题"之类的前缀，不要任何分析或点评。"""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是资深高中语文教师，擅长写出高考一类文水准的范文。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=2500
    )
    return response.choices[0].message.content

# ============================================================
# #################### Streamlit UI ###########################
# ============================================================

def init_session():
    defaults = {
        # OCR / 诊断 / 修缮
        "ocr_title": "", "ocr_body": "", "ocr_version": 0,
        "diagnosis_raw": "", "diagnosis_dict": {},
        "revised_text": "", "calibration_note": "", "calibrated_dict": {},
        "current_title": "", "current_body": "",
        "logs": [], "preset_instructions": [],
        "has_diagnosed": False, "has_revised": False, "comparison_report": None,
        "sample_text": "", "revision_plan": "", "selected_paragraphs": [],
        "genre": "议论文",
        # 修缮表单控件
        "opt1": False, "opt2": False, "opt3": False, "opt4": False,
        "custom_text": "",
        "style_option": "标准 (高考一类文)",
        "show_plan": False, "use_calibration": False, "use_sample": False,
        # 范文生成
        "me_title": "", "me_title_saved": "", "me_essay": "", "me_outline": "",
        "me_version": 0,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session()

def reset_all():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ===== 步骤条 =====
def render_step_bar():
    if st.session_state.get("has_revised"):
        current = 3
    elif st.session_state.get("has_diagnosed"):
        current = 2
    else:
        current = 1
    steps = ["📄 作文录入", "📊 多维诊断", "✍️ 智能修缮"]
    cols = st.columns(len(steps))
    for i, (col, label) in enumerate(zip(cols, steps)):
        with col:
            if i + 1 == current:
                st.markdown(f"<span class='step-active'>👉 {label}</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"<span class='step-inactive'>{label}</span>", unsafe_allow_html=True)
    st.divider()

render_step_bar()

# ===== 侧边栏 =====
with st.sidebar:
    st.header("⚙️ 密钥配置")
    user_zhipu = st.text_input("智谱API Key", value="", type="password", placeholder="留空则使用云端Secret")
    user_deepseek = st.text_input("DeepSeek API Key", value="", type="password", placeholder="留空则使用云端Secret")

    final_zhipu = user_zhipu if user_zhipu else ZHIPU_API_KEY
    final_deepseek = user_deepseek if user_deepseek else DEEPSEEK_API_KEY

    if final_zhipu:
        st.success("✅ 智谱Key已配置")
    else:
        st.warning("⚠️ 请配置智谱Key")
    if final_deepseek:
        st.success("✅ DeepSeekKey已配置")
    else:
        st.warning("⚠️ 请配置DeepSeekKey")

    st.markdown("---")
    if st.button("🔄 重置所有数据", use_container_width=True):
        reset_all()

    st.markdown("---")
    if st.button("📥 生成诊断报告", use_container_width=True):
        report = {
            "timestamp": datetime.now().isoformat(),
            "title": st.session_state.get("current_title", ""),
            "diagnosis": st.session_state.get("diagnosis_dict", {}),
            "comparison": st.session_state.get("comparison_report", {}),
            "logs": st.session_state.get("logs", [])
        }
        st.session_state["_report_json"] = json.dumps(report, ensure_ascii=False, indent=2)

    if st.session_state.get("_report_json"):
        st.download_button(
            "⬇️ 下载报告 (JSON)",
            st.session_state["_report_json"],
            "诊断报告.json",
            "application/json",
            use_container_width=True
        )
    st.caption("💡 输入框为空时自动使用部署Secret")

# ===== 主标签页（4 个） =====
tab1, tab2, tab3, tab4 = st.tabs(
    ["📄 作文录入", "📊 多维诊断", "✍️ 智能修缮", "📖 范文生成"]
)

# ========== TAB1: 录入 ==========
with tab1:
    col1, col2 = st.columns([1, 1])
    with col1:
        # 这里是多图上传核心代码，已修改为可接受多张图片
        uploaded_files = st.file_uploader(
            "上传作文照片（可多选，按顺序自动拼接）",
            type=["jpg", "jpeg", "png", "bmp"],
            accept_multiple_files=True,
            key="t1_uploader"
        )

        if uploaded_files:
            n = len(uploaded_files)
            st.caption(f"📎 已选择 **{n}** 张图片（识别时按上传顺序拼接）")

            # 缩略图预览（最多每行 3 张）
            preview_cols = st.columns(min(n, 3))
            for idx, f in enumerate(uploaded_files):
                with preview_cols[idx % 3]:
                    st.image(f, caption=f"第 {idx+1} 张", use_container_width=True)

            c_up, c_clear = st.columns([3, 1])
            with c_up:
                run_ocr = st.button("🔍 开始识别全部", type="primary", key="t1_ocr_btn", use_container_width=True)
            with c_clear:
                if st.button("⬜ 清空识别结果", key="t1_clear_ocr", use_container_width=True):
                    st.session_state.ocr_title = ""
                    st.session_state.ocr_body = ""
                    st.session_state.ocr_version += 1
                    st.rerun()

            if run_ocr:
                if not final_zhipu:
                    st.error("⚠️ 请配置智谱API Key")
                else:
                    titles = []
                    bodies = []
                    progress = st.progress(0, text="准备识别...")

                    try:
                        for idx, f in enumerate(uploaded_files):
                            progress.progress(
                                idx / n,
                                text=f"识别第 {idx+1}/{n} 张…"
                            )
                            try:
                                result = recognize_image(f.getvalue(), final_zhipu)
                                t = (result.get("title") or "").strip()
                                b = (result.get("body") or "").strip()
                                # 题目只取第一张识别到的，且跳过无效值
                                if not titles and t and t != "未识别到题目":
                                    titles.append(t)
                                if b:
                                    bodies.append(b)
                            except Exception as e:
                                st.warning(f"第 {idx+1} 张识别失败：{e}，已跳过")
                                continue

                        progress.progress(1.0, text="识别完成")

                        merged_title = titles[0] if titles else "未识别到题目"
                        merged_body = "\n\n".join(bodies) if bodies else ""

                        st.session_state.ocr_title = merged_title
                        st.session_state.ocr_body = merged_body
                        st.session_state.ocr_version += 1
                        st.success(
                            f"✅ 已识别 {len(bodies)}/{n} 张，共 {len(merged_body)} 字，已填入右侧编辑区"
                        )
                        log_action(
                            "OCR识别(多图)",
                            f"张数:{n}, 成功:{len(bodies)}, 总字数:{len(merged_body)}"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"识别失败: {e}")

    with col2:
        st.markdown("**✏️ 手动编辑区**")
        genre = st.selectbox(
            "文体",
            ["议论文", "记叙文", "说明文", "书信", "其他"],
            key="genre"
        )

        ocr_v = st.session_state.ocr_version
        title = st.text_area(
            "作文题目",
            value=st.session_state.ocr_title,
            height=80,
            key=f"t1_title_{ocr_v}"
        )
        body = st.text_area(
            "作文正文",
            value=st.session_state.ocr_body,
            height=300,
            key=f"t1_body_{ocr_v}"
        )
        # 同步回 session_state（保证跨 tab 一致）
        st.session_state.ocr_title = title
        st.session_state.ocr_body = body

        if body.strip():
            is_valid, msg = validate_input(title, body)
            if is_valid:
                st.success(msg)
            else:
                st.warning(f"⚠️ {msg}")

        if st.button("📌 确认文本并进入诊断", type="primary", use_container_width=True, key="t1_confirm"):
            is_valid, msg = validate_input(title, body)
            if is_valid:
                st.session_state.current_title = title
                st.session_state.current_body = body
                # 清空上一篇文章的段落勾选状态
                for k in list(st.session_state.keys()):
                    if k.startswith("para_"):
                        del st.session_state[k]
                st.success("✅ 文本已锁定！请切换至「多维诊断」标签")
                log_action("文本确认", f"字数:{len(body)}")
            else:
                st.error(f"❌ {msg}")

# ========== TAB2: 诊断 ==========
with tab2:
    if not st.session_state.get("current_title"):
        st.info("👆 请先在「作文录入」标签页确认文本")
    else:
        col_d1, col_d2 = st.columns([2, 1])
        with col_d1:
            st.subheader("📊 学术诊断 (3次信度校验)")
            if st.button("🚀 执行多维诊断", type="primary", key="t2_diag_btn"):
                if not final_deepseek:
                    st.error("⚠️ 请配置DeepSeek API Key")
                else:
                    with st.spinner("正在进行3次独立诊断..."):
                        try:
                            diagnosis = diagnose_with_reliability(
                                st.session_state.current_title,
                                st.session_state.current_body,
                                final_deepseek,
                                runs=3
                            )
                            st.session_state.diagnosis_dict = diagnosis
                            st.session_state.diagnosis_raw = json.dumps(diagnosis, ensure_ascii=False)
                            st.session_state.has_diagnosed = True
                            st.success("✅ 诊断完成！")
                            log_action("诊断", f"总分:{diagnosis.get('score')}")
                        except Exception as e:
                            st.error(f"诊断失败: {e}")

        if st.session_state.diagnosis_dict:
            d = st.session_state.diagnosis_dict
            reliability = d.get("reliability", {})
            if reliability:
                avg = reliability.get("avg_score", 0)
                std = reliability.get("std_score", 0)
                reliable = reliability.get("is_reliable", True)
                col_m1, col_m2, col_m3 = st.columns(3)
                col_m1.metric("📈 综合平均分", f"{avg}/60")
                col_m2.metric("📉 标准差", f"{std}",
                              delta="✅ 信度良好" if reliable else "⚠️ 争议较大",
                              delta_color="normal" if reliable else "inverse")
                col_m3.metric("🔄 诊断次数", f"{reliability.get('runs', 0)} 次")
            st.divider()
            st.subheader("📋 四维评分")
            detail = d.get("detail", {})
            cols = st.columns(4)
            metrics = [("立意", 20), ("结构", 15), ("语言", 15), ("论据", 10)]
            for idx, (label, total) in enumerate(metrics):
                score = detail.get(label, 0)
                with cols[idx]:
                    st.metric(label, f"{score}/{total}")
                    st.progress(score/total if total > 0 else 0)
            st.divider()
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown("**✅ 亮点**")
                for item in d.get("strengths", []):
                    st.info(f"• {item}")
            with col_s2:
                st.markdown("**⚠️ 不足**")
                for item in d.get("weaknesses", []):
                    st.warning(f"• {item}")
            st.markdown(f"**📝 总评：** {d.get('summary', '')}")

            # ===== 人机校准 =====
            st.divider()
            st.subheader("🤝 人机协同校准")
            with st.form("calibration_form"):
                dim = st.selectbox("有异议的维度", ["立意", "结构", "语言", "论据", "总分"], key="calib_dim")
                deviation = st.radio("你认为AI评分", ["偏高", "偏低", "基本准确"], key="calib_dev")
                comment = st.text_area("补充说明", placeholder="例如：立意虽然扣题，但深度不足", key="calib_comment")
                submit_calib = st.form_submit_button("🔄 执行校准")
            if submit_calib:
                if not final_deepseek:
                    st.error("请配置DeepSeek API Key")
                elif deviation == "基本准确":
                    st.info("你认可AI评分，无需校准")
                else:
                    with st.spinner("重新评估..."):
                        try:
                            new_score = recalibrate_score(
                                st.session_state.current_title,
                                st.session_state.current_body,
                                d, dim, deviation, comment,
                                final_deepseek
                            )
                            st.session_state.calibrated_dict = new_score
                            st.session_state.calibration_note = f"{dim}评分{deviation}；{comment}".strip("；")
                            st.success("✅ 校准完成！")
                            log_action("校准", f"{dim}:{deviation}")
                        except Exception as e:
                            st.error(f"校准失败: {e}")

            if st.session_state.calibrated_dict:
                new_d = st.session_state.calibrated_dict
                st.markdown("**📊 原始 vs 校准**")
                col_orig, col_new = st.columns(2)
                with col_orig:
                    st.markdown("**🤖 原始**")
                    st.metric("总分", f"{d.get('score', 0)}/60")
                    for k, v in d.get("detail", {}).items():
                        st.text(f"{k}: {v}")
                with col_new:
                    st.markdown("**👨‍🏫 校准后**")
                    st.metric("总分", f"{new_d.get('score', 0)}/60",
                              delta=f"{new_d.get('score', 0) - d.get('score', 0):+}")
                    for k, v in new_d.get("detail", {}).items():
                        orig_v = d.get("detail", {}).get(k, 0)
                        st.text(f"{k}: {v} ({v - orig_v:+})")
                st.info(f"📌 {new_d.get('summary', '')}")

            st.divider()
            st.info("👉 请切换至「✍️ 智能修缮」标签继续操作")

# ========== TAB3: 修缮 ==========
with tab3:
    if not st.session_state.get("current_title"):
        st.info("👆 请先在「作文录入」标签确认文本")
    elif not st.session_state.has_diagnosed:
        st.warning("⚠️ 请先在「多维诊断」标签执行诊断")
    else:
        st.subheader("🔧 全维度定向修缮")

        # ===== 范文上传 =====
        with st.expander("📚 参考范文/素材上传（可选）"):
            st.caption("上传一篇范文，AI将分析其结构并模仿其风格修缮")
            sample_file = st.file_uploader("上传范文 (txt/md)", type=["txt", "md"], key="t3_sample_uploader")
            if sample_file:
                try:
                    sample_content = sample_file.read().decode("utf-8")
                except UnicodeDecodeError:
                    sample_content = sample_file.read().decode("gbk", errors="ignore")
                st.session_state.sample_text = sample_content
                st.success(f"✅ 已加载范文 ({len(sample_content)}字)")
            sample_textarea = st.text_area(
                "或直接粘贴范文内容",
                value=st.session_state.sample_text,
                height=150,
                key="t3_sample_textarea"
            )
            if sample_textarea != st.session_state.sample_text:
                st.session_state.sample_text = sample_textarea

        # ===== 段落预处理（form 外，确保 para_i 已初始化） =====
        paragraphs = split_paragraphs(st.session_state.current_body)
        for i in range(len(paragraphs)):
            if f"para_{i}" not in st.session_state:
                st.session_state[f"para_{i}"] = False

        # ===== 快捷操作按钮（全部移出 form） =====
        st.markdown("**① 快捷预设**")
        col_o1, col_o2 = st.columns(2)
        with col_o1:
            st.checkbox("① 提升思维深度", key="opt1")
            st.checkbox("② 优化文章结构", key="opt2")
        with col_o2:
            st.checkbox("③ 精炼语言表达", key="opt3")
            st.checkbox("④ 充实论据阐释", key="opt4")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            if st.button("☑️ 全选方向", key="btn_all_opt", use_container_width=True):
                for k in ["opt1", "opt2", "opt3", "opt4"]:
                    st.session_state[k] = True
                st.rerun()
        with c2:
            if st.button("⬜ 清空方向", key="btn_clear_opt", use_container_width=True):
                for k in ["opt1", "opt2", "opt3", "opt4"]:
                    st.session_state[k] = False
                st.rerun()
        with c3:
            if st.button("☑️ 全选段落", key="btn_all_para", use_container_width=True):
                for i in range(len(paragraphs)):
                    st.session_state[f"para_{i}"] = True
                st.rerun()
        with c4:
            if st.button("⬜ 清空段落", key="btn_clear_para", use_container_width=True):
                for i in range(len(paragraphs)):
                    st.session_state[f"para_{i}"] = False
                st.rerun()

        st.divider()

        # ===== 预设管理（form 外，避免与 custom_text 冲突） =====
        with st.expander("💾 预设指令管理"):
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                new_preset = st.text_area("新预设", height=60, placeholder="例如：增加对比论证", key="new_preset_input")
                if st.button("保存预设", key="btn_save_preset"):
                    if new_preset.strip():
                        st.session_state.preset_instructions.append(new_preset.strip())
                        st.success("已保存")
            with col_p2:
                if st.session_state.get("preset_instructions"):
                    idx = st.selectbox(
                        "加载预设",
                        range(len(st.session_state.preset_instructions)),
                        format_func=lambda i: st.session_state.preset_instructions[i][:30],
                        key="preset_select"
                    )
                    if st.button("加载预设", key="btn_load_preset"):
                        st.session_state.custom_text = st.session_state.preset_instructions[idx]
                        st.rerun()

        st.divider()

        # ===== 主 form =====
        with st.form("revise_form"):
            st.markdown("**② 自定义指令**")
            custom_text = st.text_area(
                "修改要求",
                height=80,
                placeholder="例如：增加排比句，强化结尾升华",
                key="custom_text"
            )

            st.markdown("**③ 文风迁移**")
            style_option = st.selectbox(
                "目标文风",
                ["标准 (高考一类文)", "批判犀利", "文学抒情", "逻辑严密"],
                key="style_option"
            )

            st.divider()

            st.markdown("**④ 🎯 局部修缮（可选）**")
            st.caption("勾选你想要修改的段落，AI将只修改这些段落；若不勾选，则修缮全文")
            if len(paragraphs) > 1:
                for i, para in enumerate(paragraphs):
                    preview = get_paragraph_preview(para, 100)
                    st.checkbox(f"**第{i+1}段**：{preview}", key=f"para_{i}")
            else:
                st.info("📝 原文仅有一段，将执行全文修缮（建议在原文中使用换行分段）")

            st.divider()

            st.markdown("**⑤ 高级选项**")
            st.checkbox("📋 先显示修改计划，确认后再执行", key="show_plan")
            st.checkbox("📌 联动校准反馈", key="use_calibration")
            st.checkbox("📚 模仿范文风格", key="use_sample")

            submit_revise = st.form_submit_button("✍️ 执行修缮", type="primary", use_container_width=True)

        # ===== 处理修缮请求 =====
        if submit_revise:
            selected = [k for k in ["1", "2", "3", "4"] if st.session_state.get(f"opt{k}")]

            # 实时从 session_state 读取段落勾选
            selected_paras = [
                paragraphs[i] for i in range(len(paragraphs))
                if st.session_state.get(f"para_{i}", False)
            ]
            st.session_state.selected_paragraphs = selected_paras

            if not selected and not custom_text.strip():
                st.warning("请勾选预设或输入自定义指令")
            elif not final_deepseek:
                st.error("请配置DeepSeek API Key")
            else:
                style_map = {
                    "标准 (高考一类文)": "标准",
                    "批判犀利": "批判犀利",
                    "文学抒情": "文学抒情",
                    "逻辑严密": "逻辑严密"
                }
                selected_style = style_map[style_option]

                # 思维链模式
                if st.session_state.get("show_plan"):
                    with st.spinner("正在生成修改计划..."):
                        try:
                            plan = get_revision_plan(
                                st.session_state.current_title,
                                st.session_state.current_body,
                                st.session_state.diagnosis_raw,
                                selected,
                                custom_text,
                                selected_style,
                                final_deepseek
                            )
                            st.session_state.revision_plan = plan
                            log_action("生成计划", "成功")
                        except Exception as e:
                            st.error(f"生成计划失败: {e}")

                if st.session_state.get("revision_plan"):
                    st.markdown("**📋 AI 修改计划**")
                    st.info(st.session_state.revision_plan)
                    st.caption("👉 若计划无误，点击下方「执行修缮」按钮继续")

                # 执行正式修缮
                with st.spinner("正在精修文章..."):
                    try:
                        cal_note = st.session_state.calibration_note if st.session_state.get("use_calibration") else ""
                        sample = st.session_state.sample_text if st.session_state.get("use_sample") else ""
                        target_paras = st.session_state.get("selected_paragraphs", [])

                        revised = revise_essay(
                            st.session_state.current_title,
                            st.session_state.current_body,
                            st.session_state.diagnosis_raw,
                            selected,
                            cal_note,
                            custom_text,
                            selected_style,
                            sample,
                            target_paras,
                            final_deepseek
                        )
                        st.session_state.revised_text = revised
                        st.session_state.has_revised = True
                        st.success("✅ 修缮完成！")
                        log_action("修缮", f"风格:{selected_style}, 局部段数:{len(target_paras)}")

                        # 闭环诊断
                        with st.spinner("正在评估修缮效果..."):
                            try:
                                revised_diag = quick_diagnose(
                                    st.session_state.current_title,
                                    revised,
                                    final_deepseek
                                )
                                orig_diag = st.session_state.diagnosis_dict
                                comparison = {
                                    "original_score": orig_diag.get("score"),
                                    "revised_score": revised_diag.get("score"),
                                    "score_change": revised_diag.get("score") - orig_diag.get("score"),
                                    "original_details": orig_diag.get("detail"),
                                    "revised_details": revised_diag.get("detail"),
                                    "original_summary": orig_diag.get("summary"),
                                    "revised_summary": revised_diag.get("summary"),
                                    "local_paragraphs": len(target_paras)
                                }
                                st.session_state.comparison_report = comparison
                                log_action("闭环诊断", f"提升:{comparison['score_change']:+}分")
                            except Exception as e:
                                st.warning(f"闭环诊断失败: {e}")
                    except Exception as e:
                        st.error(f"修缮失败: {e}")

        # ===== 显示修缮稿 =====
        if st.session_state.revised_text:
            st.divider()
            st.subheader("📝 修缮稿")
            st.text_area("修缮后文章", value=st.session_state.revised_text, height=400, key="revised_display")

            if st.session_state.comparison_report:
                comp = st.session_state.comparison_report
                st.subheader("📊 修缮效果对比")
                cb1, cb2 = st.columns(2)
                with cb1:
                    st.metric("修缮前", f"{comp['original_score']}/60")
                    for k, v in comp["original_details"].items():
                        st.text(f"{k}: {v}")
                with cb2:
                    st.metric("修缮后", f"{comp['revised_score']}/60",
                              delta=f"{comp['score_change']:+}分")
                    for k, v in comp["revised_details"].items():
                        orig = comp["original_details"].get(k, 0)
                        st.text(f"{k}: {v} ({v - orig:+})")
                if comp.get("local_paragraphs", 0) > 0:
                    st.caption(f"🎯 本次修缮了 {comp['local_paragraphs']} 个段落")

            with st.expander("📖 逐句对比 (Diff视图)"):
                diff_html = generate_diff_html(
                    st.session_state.current_body,
                    st.session_state.revised_text
                )
                st.markdown(
                    f'<div style="background:#f8f9fa;padding:15px;border-radius:8px;'
                    f'font-family:monospace;font-size:14px;">{diff_html}</div>',
                    unsafe_allow_html=True
                )
                st.caption("🟢 绿色 = 新增/修改  🔴 红色 = 删除")

            st.download_button(
                label="⬇️ 下载修缮稿 (.txt)",
                data=st.session_state.revised_text,
                file_name="修缮稿_AI精修版.txt",
                mime="text/plain",
                use_container_width=True
            )

# ========== TAB4: 范文生成 ==========
with tab4:
    st.subheader("📖 范文生成器")
    st.caption("上传/输入作文题目 → 选文体文风 → AI 独立完成破题、构思、写作，输出一篇示范作文")

    col_f1, col_f2 = st.columns([1, 1])

    # ---------- 左列：获取题目 ----------
    with col_f1:
        st.markdown("**① 获取作文题目**")

        title_img = st.file_uploader(
            "上传题目图片（可选）",
            type=["jpg", "jpeg", "png", "bmp"],
            key="me_img_uploader"
        )
        if title_img is not None:
            if st.button("🔍 识别题目", key="me_ocr_btn"):
                if not final_zhipu:
                    st.error("⚠️ 请配置智谱API Key")
                else:
                    with st.spinner("正在识别题目..."):
                        try:
                            result = recognize_image(title_img.getvalue(), final_zhipu)
                            st.session_state.me_title = result["title"]
                            st.session_state.me_version += 1
                            st.success("✅ 题目识别完成！")
                            st.rerun()
                        except Exception as e:
                            st.error(f"识别失败: {e}")

        me_v = st.session_state.me_version
        me_title_input = st.text_area(
            "作文题目（可直接手动输入）",
            value=st.session_state.me_title,
            height=120,
            key=f"me_title_input_{me_v}",
            placeholder="例：以'边界'为题写一篇议论文"
        )
        if me_title_input != st.session_state.me_title:
            st.session_state.me_title = me_title_input

    # ---------- 右列：生成配置 ----------
    with col_f2:
        st.markdown("**② 生成配置**")
        me_genre = st.selectbox("文体", ["议论文", "记叙文", "散文"], key="me_genre")
        me_grade = st.selectbox("年级", ["高一", "高二", "高三", "高考冲刺"], index=2, key="me_grade")
        me_style = st.selectbox("文风", ["稳健理性", "批判犀利", "文学抒情", "逻辑严密"], key="me_style")
        me_words = st.slider("目标字数", 600, 1200, 800, step=50, key="me_words")
        me_mode = st.radio(
            "生成模式",
            ["🚀 一步生成（直接出范文）", "🧠 两步生成（先构思，再写全文）"],
            key="me_mode",
            help="一步生成更快；两步生成可让你先审阅提纲，更适合课堂演示"
        )

    st.divider()

    # ---------- 生成按钮 ----------
    if st.button("✨ 开始生成", type="primary", use_container_width=True, key="me_gen_btn"):
        title_for_gen = (st.session_state.get("me_title", "") or "").strip()
        if not title_for_gen:
            st.warning("请先输入或识别作文题目")
        elif not final_deepseek:
            st.error("⚠️ 请配置 DeepSeek API Key")
        else:
            if "一步生成" in me_mode:
                with st.spinner("AI 正在创作范文，约 20-40 秒..."):
                    try:
                        essay = generate_essay_directly(
                            title_for_gen, me_genre, me_grade, me_style,
                            me_words, final_deepseek
                        )
                        st.session_state.me_essay = essay
                        st.session_state.me_title_saved = title_for_gen
                        st.session_state.me_outline = ""
                        st.session_state.me_version += 1
                        log_action("范文生成(一步)", f"题目:{title_for_gen[:20]} 文体:{me_genre}")
                        st.success("✅ 范文生成完成！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"生成失败: {e}")
            else:
                with st.spinner("AI 正在构思提纲..."):
                    try:
                        outline = generate_outline(
                            title_for_gen, me_genre, me_grade, me_style, final_deepseek
                        )
                        st.session_state.me_outline = outline
                        st.session_state.me_title_saved = title_for_gen
                        st.session_state.me_essay = ""
                        log_action("范文生成(提纲)", f"题目:{title_for_gen[:20]}")
                        st.success("✅ 提纲生成完成！请审阅后点击下方按钮继续")
                    except Exception as e:
                        st.error(f"生成提纲失败: {e}")

    # ---------- 两步模式：展示提纲 + 继续生成 ----------
    if st.session_state.get("me_outline"):
        st.markdown("### 💡 构思提纲（可先讲给学生听）")
        st.markdown(st.session_state.me_outline)

        col_o1, col_o2 = st.columns([2, 1])
        with col_o1:
            if st.button("📝 按此提纲生成完整范文", type="primary", use_container_width=True, key="me_gen_from_outline"):
                with st.spinner("AI 正在撰写范文，约 20-40 秒..."):
                    try:
                        essay = generate_model_essay(
                            st.session_state.me_title_saved,
                            st.session_state.me_genre,
                            st.session_state.me_grade,
                            st.session_state.me_style,
                            st.session_state.me_words,
                            st.session_state.me_outline,
                            final_deepseek
                        )
                        st.session_state.me_essay = essay
                        st.session_state.me_version += 1
                        log_action("范文生成(完整)", "成功")
                        st.success("✅ 范文生成完成！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"生成失败: {e}")
        with col_o2:
            if st.button("🔄 重新构思", use_container_width=True, key="me_regen_outline"):
                st.session_state.me_outline = ""
                st.rerun()

    # ---------- 展示范文 ----------
    if st.session_state.get("me_essay"):
        st.divider()
        st.markdown("### 📖 范文")
        me_v2 = st.session_state.me_version
        me_essay_edit = st.text_area(
            "范文正文（可直接编辑）",
            value=st.session_state.me_essay,
            height=500,
            key=f"me_essay_display_{me_v2}"
        )
        if me_essay_edit != st.session_state.me_essay:
            st.session_state.me_essay = me_essay_edit

        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            st.download_button(
                "⬇️ 下载范文 (.txt)",
                st.session_state.me_essay,
                file_name=f"范文_{st.session_state.get('me_title_saved', 'untitled')[:15]}.txt",
                mime="text/plain",
                use_container_width=True
            )
        with col_a2:
            if st.button("📊 投喂给 AI 评分", use_container_width=True, key="me_to_diag"):
                st.session_state.current_title = st.session_state.get("me_title_saved", "")
                st.session_state.current_body = st.session_state.me_essay
                # 清空旧的诊断/修缮数据，避免串台
                st.session_state.diagnosis_dict = {}
                st.session_state.diagnosis_raw = ""
                st.session_state.has_diagnosed = False
                st.session_state.revised_text = ""
                st.session_state.has_revised = False
                st.session_state.comparison_report = None
                st.session_state.calibrated_dict = {}
                log_action("范文导入诊断", st.session_state.current_title[:20])
                st.success("✅ 已导入「多维诊断」。请切换标签页查看评分。")
        with col_a3:
            if st.button("🗑️ 清空范文", use_container_width=True, key="me_clear"):
                st.session_state.me_essay = ""
                st.session_state.me_outline = ""
                st.session_state.me_title_saved = ""
                st.session_state.me_version += 1
                st.rerun()

# ===== 底部 =====
st.sidebar.markdown("---")
st.sidebar.caption("📌 研究平台：信度校验 · 人机协同 · 段落级修缮 · 闭环评价 · 范文生成")
