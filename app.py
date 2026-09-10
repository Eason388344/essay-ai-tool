# app.py
# AI写作教练 - 图片识文 + 多文体三段式工作流

import streamlit as st
import base64
import time
import json
import re
import statistics
import difflib
from io import BytesIO
from PIL import Image
from openai import OpenAI

# ============================================================
# 配置
# ============================================================
DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
ZHIPU_API_KEY = st.secrets.get("ZHIPU_API_KEY", "")

st.set_page_config(page_title="AI写作教练", page_icon="✍️", layout="wide")

# ============================================================
# 文体配置中心
# ============================================================
GENRE_CONFIG = {
    "议论文": {
        "icon": "📊",
        "dimensions": {"审题立意": 20, "结构与逻辑": 15, "语言表达": 15, "论据与内容": 10},
        "diagnose_prompt": """你是一位资深高考作文阅卷老师。请严格按以下标准对议论文评分（满分60分）：
【审题立意】20分：是否精准理解题目核心？有无跑题？
【结构与逻辑】15分：层次分明？论证严密？
【语言表达】15分：流畅精准？有无语病？
【论据与内容】10分：素材充实？支撑论点？
请按以下JSON格式输出（不要其他文字）：
{"score": 总分, "detail": {"审题立意":分数, "结构与逻辑":分数, "语言表达":分数, "论据与内容":分数}, "strengths": ["优点1", "优点2", "优点3"], "weaknesses": ["不足1", "不足2", "不足3"], "summary": "总评(20字以内)"}""",
        "revise_strategy": "强化论点与论据的咬合，优化论证层次，精炼语言，保持核心立场。",
        "system_prompt": "你是一位资深高考作文辅导老师，擅长精修议论文。只输出修缮后的文章正文，不要任何分析。",
        "writing_tips": "明确的论点 + 严密的论证 + 有力的论据"
    },
    "记叙文": {
        "icon": "📖",
        "dimensions": {"叙事技巧": 20, "描写生动性": 15, "语言表达": 15, "情感真挚度": 10},
        "diagnose_prompt": """你是一位资深语文教师。请严格按以下标准对记叙文评分（满分60分）：
【叙事技巧】20分：情节完整？详略得当？
【描写生动性】15分：画面感强？具体？
【语言表达】15分：流畅？有感染力？
【情感真挚度】10分：真实？打动读者？
请按以下JSON格式输出（不要其他文字）：
{"score": 总分, "detail": {"叙事技巧":分数, "描写生动性":分数, "语言表达":分数, "情感真挚度":分数}, "strengths": ["优点1", "优点2", "优点3"], "weaknesses": ["不足1", "不足2", "不足3"], "summary": "总评(20字以内)"}""",
        "revise_strategy": "强化细节描写，优化叙事节奏，增强情感共鸣，保持个人风格。",
        "system_prompt": "你是一位资深语文教师，擅长指导记叙文。只输出修缮后的文章正文。",
        "writing_tips": "具体的故事 + 生动的细节 + 真挚的情感"
    },
    "散文": {
        "icon": "🌿",
        "dimensions": {"意境营造": 20, "语言韵味": 15, "结构美感": 15, "情感表达": 10},
        "diagnose_prompt": """你是一位资深语文教师。请严格按以下标准对散文评分（满分60分）：
【意境营造】20分：情景交融？独特意境？
【语言韵味】15分：优美？有节奏感？
【结构美感】15分：浑然一体？起承转合自然？
【情感表达】10分：细腻？含蓄有力？
请按以下JSON格式输出（不要其他文字）：
{"score": 总分, "detail": {"意境营造":分数, "语言韵味":分数, "结构美感":分数, "情感表达":分数}, "strengths": ["优点1", "优点2", "优点3"], "weaknesses": ["不足1", "不足2", "不足3"], "summary": "总评(20字以内)"}""",
        "revise_strategy": "强化意象选取与组合，优化语言节奏，调整结构流畅度，保留情感基调。",
        "system_prompt": "你是一位资深语文教师，擅长指导散文。只输出修缮后的文章正文。",
        "writing_tips": "独特的意境 + 优美的语言 + 真挚的情感"
    }
}

def get_genre_list():
    return list(GENRE_CONFIG.keys())

def get_genre_dimensions(genre):
    return GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])["dimensions"]

def get_genre_icon(genre):
    return GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])["icon"]

def get_genre_tips(genre):
    return GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])["writing_tips"]

def get_grade_strategy(grade="高三"):
    return {
        "高一": "侧重基础，语言流畅、结构完整即可。",
        "高二": "在基础之上强化思辨或文学表现力。",
        "高三": "对标高考满分标准，立意深刻、结构严谨、语言精准。"
    }.get(grade, "对标高考满分标准。")

def get_style_prompt(style="标准"):
    return {
        "标准": "稳健理性的写作风格。",
        "批判犀利": "增强批判性语气，使用对比、质疑和反思。",
        "文学抒情": "增强文学性，运用比喻、拟人、排比等修辞。",
        "逻辑严密": "强化因果链和演绎推理，多用逻辑连接词。"
    }.get(style, "稳健理性的写作风格。")

# ============================================================
# 提示词构建
# ============================================================
def build_idea_prompt(title, genre, grade="高三", hint=""):
    tips = get_genre_tips(genre)
    return f"""你是一位经验丰富的写作导师。请帮助一位{grade}学生构思一篇{genre}。

【题目/话题】：{title}
{hint if hint else ""}

【任务要求】请输出：
## 1. 破题角度（3个）
从不同视角切入题目，每个角度给出核心观点。

## 2. 写作提纲
为推荐角度搭建清晰的写作框架。

## 3. 素材推荐（3-5个）
推荐相关名言、事例、数据，附简短说明。

## 4. 写作提醒
提醒学生注意{genre}的核心要素：{tips}

请用中文输出，语气亲切鼓励，不要过于学术化。"""

def build_draft_prompt(title, genre, keywords, style="标准", grade="高三"):
    return f"""你是一位写作助手。请帮助一位{grade}学生将以下内容扩展成一篇完整的{genre}。

【题目/话题】：{title}
【学生思路/关键词】：{keywords}
【目标文风】：{get_style_prompt(style)}

【任务要求】
1. 根据思路扩展成结构完整的文章
2. 保持{genre}的基本特征：{get_genre_tips(genre)}
3. 语言适合高中生水平
4. 直接输出文章正文，不要任何分析"""

def build_revise_prompt(title, body, diagnosis_text, genre, selected_options,
                        custom_instruction="", style="标准", calibration_note="",
                        sample_text="", target_paras=None, grade="高三"):
    config = GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])
    option_map = {"1": "提升立意/中心思想深度", "2": "优化结构/层次感",
                  "3": "精炼语言表达", "4": "充实内容/细节/论据"}
    opts = [option_map[k] for k in sorted(selected_options) if k in option_map]
    base = "；".join(opts) if opts else "根据诊断自主判断"

    if target_paras and len(target_paras) > 0:
        marked = body
        for p in target_paras:
            if p in body:
                marked = marked.replace(p, f"【待修改开始】\n{p}\n【待修改结束】")
        modify_inst = f"局部修缮：只修改被【待修改开始】和【待修改结束】标记的{len(target_paras)}段，其他原样不动。"
        output_inst = "输出完整文章，被标记段落已修改，其他一字不差照抄。"
    else:
        marked = body
        modify_inst = "全文修缮。"
        output_inst = "输出修缮后的完整文章。"

    silent = "自动纠正OCR导致的明显错别字（如同音字、形近字），无需说明。人名地名专有名词保持原样。"

    prompt = f"""【年级要求】：{get_grade_strategy(grade)}
【文体】：{genre}
【题目】：{title}

【原文】：
{marked}

【诊断结果】：
{diagnosis_text}
{chr(10) + '【校准意见】：' + calibration_note if calibration_note else ''}
{chr(10) + '【参考范文】：' + chr(10) + sample_text if sample_text.strip() else ''}

【修缮策略】：
{config['revise_strategy']}

【综合指令】：
1. 基础方向：{base}
2. 整体文风：{get_style_prompt(style)}
3. {custom_instruction.strip() if custom_instruction.strip() else "（无额外要求）"}
4. {modify_inst}

【静默纠错】：{silent}

【核心要求】：{output_inst}
只输出文章正文，不要任何分析过程。"""

    return prompt, config["system_prompt"]

# ============================================================
# 工具函数
# ============================================================
def compress_image(image_bytes, max_size=(1024, 1024), quality=85):
    img = Image.open(BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.thumbnail(max_size, Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()

def validate_input(title, body):
    if not title or not title.strip():
        return False, "题目不能为空"
    if not body or not body.strip():
        return False, "正文不能为空"
    wc = len(body.strip())
    if wc < 50:
        return False, f"正文仅{wc}字，建议至少50字"
    chinese = len(re.findall(r'[\u4e00-\u9fff]', body))
    ratio = chinese / max(len(body), 1)
    if ratio < 0.3:
        return False, "汉字占比过低，请检查OCR结果"
    return True, f"✅ 校验通过：{wc}字，汉字占比{ratio:.0%}"

def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    if len(text) > 3000:
        text = text[:3000] + "\n...（内容过长已截断）"
    return text

def split_paragraphs(text):
    if not text:
        return []
    text = clean_text(text)
    paras = [p.strip() for p in re.split(r'\n\s*\n|\n', text) if p.strip()]
    if len(paras) <= 1 and len(text) > 100:
        sents = re.split(r'[。！？；]', text)
        paras = [s.strip() + '。' for s in sents if s.strip()]
    return paras

def para_preview(p, n=80):
    return p if len(p) <= n else p[:n] + "..."

def extract_json(text):
    text = text.strip()
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end+1]
    raise ValueError("未找到有效JSON")

def generate_diff_html(original, revised):
    diff = difflib.ndiff(original.splitlines(), revised.splitlines())
    parts = []
    for line in diff:
        if line.startswith('+ '):
            parts.append(f'<span style="background:#d4edda;color:#155724;padding:2px 4px;border-radius:3px;">{line[2:]}</span>')
        elif line.startswith('- '):
            parts.append(f'<span style="background:#f8d7da;color:#721c24;padding:2px 4px;border-radius:3px;">{line[2:]}</span>')
        elif line.startswith('  '):
            parts.append(line[2:])
    return '<br>'.join(parts)

# ============================================================
# API 调用
# ============================================================
def recognize_image(image_bytes, api_key):
    """图片识文：识别作文题目 + 正文"""
    if not api_key:
        raise ValueError("请先设置智谱API Key")
    compressed = compress_image(image_bytes)
    image_b64 = base64.b64encode(compressed).decode("utf-8")
    client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")
    prompt = """请精准识别图片中的全部手写文字。图片包含【作文题目】和【学生作文正文】两部分。

严格按以下格式输出（不要任何额外说明）：

===题目===
（识别出的作文题目全文；如果没有题目，写"未识别到题目"）

===正文===
（识别出的学生作文正文全文）"""
    for attempt in range(5):
        try:
            resp = client.chat.completions.create(
                model="glm-4.6v-flash",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        {"type": "text", "text": prompt}
                    ]
                }],
                max_tokens=2048,
                temperature=0.1
            )
            raw = resp.choices[0].message.content
            tm = re.search(r'===题目===\s*(.*?)\s*===正文===', raw, re.DOTALL)
            bm = re.search(r'===正文===\s*(.*?)$', raw, re.DOTALL)
            title = tm.group(1).strip() if tm else "未识别到题目"
            body = bm.group(1).strip() if bm else raw.strip()
            return {"title": title, "body": body}
        except Exception as e:
            if "429" in str(e):
                time.sleep((attempt + 1) * 5)
            else:
                raise e
    raise RuntimeError("识别重试失败")

def call_deepseek(messages, temperature=0.3, max_tokens=800):
    if not DEEPSEEK_API_KEY:
        raise ValueError("请配置DeepSeek API Key")
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return resp.choices[0].message.content

def single_diagnose(title, body, genre, temperature=0.3):
    prompt = GENRE_CONFIG.get(genre, GENRE_CONFIG["议论文"])["diagnose_prompt"]
    raw = call_deepseek([
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"题目：{title}\n\n正文：{body}"}
    ], temperature=temperature, max_tokens=800)
    return json.loads(extract_json(raw))

def diagnose_with_reliability(title, body, genre, runs=3):
    results = []
    for i in range(runs):
        try:
            temp = [0.1, 0.3, 0.5][i % 3]
            results.append(single_diagnose(title, body, genre, temp))
        except Exception as e:
            st.warning(f"第{i+1}次诊断失败：{e}")
    if len(results) < 2:
        raise RuntimeError("有效诊断次数不足")
    scores = [r["score"] for r in results]
    main = results[0]
    main["reliability"] = {
        "avg_score": round(statistics.mean(scores), 1),
        "std_score": round(statistics.stdev(scores) if len(scores) > 1 else 0, 2),
        "is_reliable": (statistics.stdev(scores) if len(scores) > 1 else 0) <= 2.0,
        "runs": len(results)
    }
    return main

def quick_diagnose(title, body, genre):
    return single_diagnose(title, body, genre, 0.3)

def generate_ideas(title, genre, grade, hint=""):
    return call_deepseek([{"role": "user", "content": build_idea_prompt(title, genre, grade, hint)}],
                         temperature=0.7, max_tokens=1000)

def expand_draft(title, genre, keywords, style, grade):
    return call_deepseek([{"role": "user", "content": build_draft_prompt(title, genre, keywords, style, grade)}],
                         temperature=0.8, max_tokens=1500)

def revise_essay(title, body, diagnosis_text, genre, selected_options,
                 custom_instruction="", style="标准", calibration_note="",
                 sample_text="", target_paras=None, grade="高三"):
    prompt, sys_prompt = build_revise_prompt(
        title, body, diagnosis_text, genre, selected_options,
        custom_instruction, style, calibration_note, sample_text, target_paras, grade
    )
    return call_deepseek([
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt}
    ], temperature=0.75, max_tokens=2048)

def recalibrate_score(title, body, original, dimension, deviation, comment, genre):
    prompt = f"""题目：{title}
原文：{body}
AI原评分：{json.dumps(original, ensure_ascii=False)}
教师反馈：维度「{dimension}」评分{deviation}，{comment}
请重新评分，输出JSON：
{{"score": 总分, "detail": {{维度: 分数}}, "summary": "总评"}}"""
    raw = call_deepseek([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=600)
    return json.loads(extract_json(raw))

# ============================================================
# Session State
# ============================================================
def init_session():
    defaults = {
        "ocr_title": "", "ocr_body": "",
        "diagnosis_raw": "", "diagnosis_dict": {},
        "revised_text": "", "calibration_note": "", "calibrated_dict": {},
        "current_title": "", "current_body": "", "current_genre": "议论文",
        "has_diagnosed": False, "comparison_report": None,
        "sample_text": "", "selected_paragraphs": [],
        "grade": "高三", "ideas_output": "", "draft_output": "",
        "writing_stage": "构思"
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

def reset_all():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.header("⚙️ 配置")
    user_zhipu = st.text_input("智谱API Key", value="", type="password", placeholder="留空用云端Secret")
    user_deepseek = st.text_input("DeepSeek API Key", value="", type="password", placeholder="留空用云端Secret")
    final_zhipu = user_zhipu if user_zhipu else ZHIPU_API_KEY
    final_deepseek = user_deepseek if user_deepseek else DEEPSEEK_API_KEY

    if final_zhipu:
        st.success("✅ 智谱Key")
    else:
        st.warning("⚠️ 智谱Key（OCR用）")
    if final_deepseek:
        st.success("✅ DeepSeekKey")
    else:
        st.warning("⚠️ DeepSeekKey（诊断用）")

    st.markdown("---")
    if st.button("🔄 重置所有数据", use_container_width=True):
        reset_all()
    st.caption("✍️ AI写作教练 v3.1")

# ============================================================
# 主界面
# ============================================================
st.title("✍️ AI写作教练")
st.caption("图片识文 · 构思 · 起草 · 修缮 — 多文体智能写作助手")

col_g, col_grade = st.columns([2, 1])
with col_g:
    genres = get_genre_list()
    genre_labels = [f"{get_genre_icon(g)} {g}" for g in genres]
    default_idx = genres.index(st.session_state.current_genre) if st.session_state.current_genre in genres else 0
    sel = st.selectbox("📚 选择文体", genre_labels, index=default_idx)
    st.session_state.current_genre = genres[genre_labels.index(sel)]
    current_genre = st.session_state.current_genre

with col_grade:
    grade_opts = ["高一", "高二", "高三"]
    g_idx = grade_opts.index(st.session_state.grade) if st.session_state.grade in grade_opts else 2
    st.session_state.grade = st.selectbox("🎓 年级", grade_opts, index=g_idx)
    grade = st.session_state.grade

# ============================================================
# 📷 图片识文功能区（全局可用，所有阶段通用）
# ============================================================
with st.expander("📷 图片识文 — 上传作文照片，自动提取题目和原文", expanded=False):
    st.caption("识别出的题目和正文会自动填入下方各阶段的输入框。识别后请务必手动检查一遍，如有错误可直接修改。")

    col_up, col_res = st.columns([1, 1])
    with col_up:
        img_file = st.file_uploader("上传作文照片（含题目和正文）", 
                                     type=["jpg", "jpeg", "png", "bmp"],
                                     key="global_ocr_upload")
        if img_file is not None:
          st.image(img_file, caption="已上传的图片", use_container_width=True)
            if st.button("🔍 开始识别", type="primary", use_container_width=True):
                if not final_zhipu:
                    st.error("⚠️ 请先配置智谱API Key")
                else:
                    with st.spinner("正在识别图片中的文字..."):
                        try:
                            result = recognize_image(img_file.getvalue(), final_zhipu)
                            st.session_state.ocr_title = result["title"]
                            st.session_state.ocr_body = result["body"]
                            st.success("✅ 识别完成！请在右侧检查和修改")
                        except Exception as e:
                            st.error(f"识别失败：{e}")

    with col_res:
        st.markdown("**✏️ 识别结果（可编辑）**")
        edit_title = st.text_area(
            "📌 作文题目", 
            value=st.session_state.ocr_title, 
            height=80, 
            key="global_ocr_title",
            placeholder="识别出的题目会显示在这里，可手动修改"
        )
        edit_body = st.text_area(
            "📄 作文正文", 
            value=st.session_state.ocr_body, 
            height=250, 
            key="global_ocr_body",
            placeholder="识别出的正文会显示在这里，可手动修改"
        )
        # 同步回 session_state
        st.session_state.ocr_title = edit_title
        st.session_state.ocr_body = edit_body

        if edit_body.strip():
            ok, msg = validate_input(edit_title, edit_body)
            if ok:
                st.success(msg)
            else:
                st.warning(f"⚠️ {msg}")

        if st.button("📌 确认文本并锁定", use_container_width=True):
            ok, msg = validate_input(edit_title, edit_body)
            if ok:
                st.session_state.current_title = edit_title
                st.session_state.current_body = edit_body
                st.success("✅ 已锁定！下方所有阶段将自动使用该文本")
            else:
                st.error(f"❌ {msg}")

    # 状态提示
    if st.session_state.get("current_title"):
        st.info(f"📎 当前已锁定的文本：**{st.session_state.current_title[:30]}...**")

st.markdown("---")

# ============================================================
# 写作阶段
# ============================================================
stage_options = ["🧠 构思破题", "✍️ 起草扩写", "📊 诊断修缮"]
stage_map = {"🧠 构思破题": "构思", "✍️ 起草扩写": "起草", "📊 诊断修缮": "修缮"}
reverse_map = {v: k for k, v in stage_map.items()}
default_stage = reverse_map.get(st.session_state.writing_stage, "🧠 构思破题")
stage = st.radio("选择写作阶段", stage_options, index=stage_options.index(default_stage), horizontal=True)
st.session_state.writing_stage = stage_map[stage]

# ============================================================
# 阶段一：构思
# ============================================================
if st.session_state.writing_stage == "构思":
    st.markdown(f"### 🧠 构思破题 · {get_genre_icon(current_genre)} {current_genre}")
    st.caption(f"💡 {get_genre_tips(current_genre)}")

    col1, col2 = st.columns([1, 1])
    with col1:
        title = st.text_input("题目/话题", 
                              value=st.session_state.get("current_title") or st.session_state.ocr_title,
                              placeholder="输入题目或写作话题（也可以从上方图片识文自动带入）")
        hint = st.text_area("补充说明（可选）", placeholder="例如：需要包含辩证思考 / 希望偏向抒情")
        if st.button("🚀 生成构思", type="primary", use_container_width=True):
            if not title.strip():
                st.error("请输入题目")
            elif not final_deepseek:
                st.error("请配置DeepSeek API Key")
            else:
                with st.spinner("生成中..."):
                    try:
                        st.session_state.ideas_output = generate_ideas(title, current_genre, grade, hint)
                        st.session_state.current_title = title
                        st.success("✅ 完成！")
                    except Exception as e:
                        st.error(f"失败：{e}")
    with col2:
        if st.session_state.ideas_output:
            st.markdown("**🧠 构思结果**")
            st.markdown(st.session_state.ideas_output)

# ============================================================
# 阶段二：起草
# ============================================================
elif st.session_state.writing_stage == "起草":
    st.markdown(f"### ✍️ 起草扩写 · {get_genre_icon(current_genre)} {current_genre}")

    col1, col2 = st.columns([1, 1])
    with col1:
        title = st.text_input("题目/话题", 
                              value=st.session_state.get("current_title") or st.session_state.ocr_title)
        keywords = st.text_area("思路/关键词", height=150, 
                                placeholder="输入核心想法、关键词或提纲（也可以直接把上方识别的原文粘贴进来作为参考）")
        style = st.selectbox("目标文风", ["标准", "批判犀利", "文学抒情", "逻辑严密"], index=0)
        if st.button("✍️ 生成草稿", type="primary", use_container_width=True):
            if not title.strip():
                st.error("请输入题目")
            elif not keywords.strip():
                st.error("请输入思路")
            elif not final_deepseek:
                st.error("请配置DeepSeek API Key")
            else:
                with st.spinner("生成中..."):
                    try:
                        st.session_state.draft_output = expand_draft(title, current_genre, keywords, style, grade)
                        st.session_state.current_title = title
                        st.session_state.current_body = st.session_state.draft_output
                        st.session_state.ocr_body = st.session_state.draft_output
                        st.success("✅ 完成！草稿已保存，可切换到诊断阶段")
                    except Exception as e:
                        st.error(f"失败：{e}")
    with col2:
        if st.session_state.draft_output:
            st.markdown("**📝 草稿预览**")
            st.text_area("草稿", value=st.session_state.draft_output, height=350)
            st.info("💡 草稿已自动保存，可切换到「诊断修缮」阶段进行评分和精修")

# ============================================================
# 阶段三：诊断修缮
# ============================================================
else:
    st.markdown(f"### 📊 诊断修缮 · {get_genre_icon(current_genre)} {current_genre}")

    tab_input, tab_diag, tab_rev = st.tabs(["📝 输入", "📊 诊断报告", "🔧 修缮"])

    # ---------- 输入 ----------
    with tab_input:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("**📷 局部上传识别**")
            st.caption("也可以直接使用顶部「图片识文」功能区，效果相同")
            uploaded = st.file_uploader("上传作文照片", type=["jpg", "jpeg", "png", "bmp"], key="local_ocr")
            if uploaded is not None:
                if st.button("🔍 OCR识别"):
                    if not final_zhipu:
                        st.error("请配置智谱API Key")
                    else:
                        with st.spinner("识别中..."):
                            try:
                                r = recognize_image(uploaded.getvalue(), final_zhipu)
                                st.session_state.ocr_title = r["title"]
                                st.session_state.ocr_body = r["body"]
                                st.success("✅ 识别完成！")
                            except Exception as e:
                                st.error(f"识别失败：{e}")
        with col2:
            title = st.text_area("题目/话题", value=st.session_state.ocr_title, height=80)
            body = st.text_area("正文", value=st.session_state.ocr_body, height=300)
            st.session_state.ocr_title = title
            st.session_state.ocr_body = body

            if body.strip():
                ok, msg = validate_input(title, body)
                if ok:
                    st.success(msg)
                else:
                    st.warning(f"⚠️ {msg}")

            if st.button("📌 确认文本 → 诊断", type="primary", use_container_width=True):
                ok, msg = validate_input(title, body)
                if ok:
                    st.session_state.current_title = title
                    st.session_state.current_body = body
                    st.success("✅ 已确认，请切换到「诊断报告」标签")
                else:
                    st.error(f"❌ {msg}")

    # ---------- 诊断报告 ----------
    with tab_diag:
        if not st.session_state.get("current_title"):
            st.info("👆 请先在上方「图片识文」或「输入」标签确认文本")
        else:
            if st.button("🚀 执行多维诊断", type="primary"):
                if not final_deepseek:
                    st.error("请配置DeepSeek API Key")
                else:
                    with st.spinner("3次独立诊断中..."):
                        try:
                            d = diagnose_with_reliability(
                                st.session_state.current_title,
                                st.session_state.current_body,
                                current_genre, runs=3
                            )
                            st.session_state.diagnosis_dict = d
                            st.session_state.diagnosis_raw = json.dumps(d, ensure_ascii=False)
                            st.session_state.has_diagnosed = True
                            st.success("✅ 诊断完成！")
                        except Exception as e:
                            st.error(f"诊断失败：{e}")

            if st.session_state.diagnosis_dict:
                d = st.session_state.diagnosis_dict
                rel = d.get("reliability", {})

                if rel:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("📈 平均分", f"{rel.get('avg_score', 0)}/60")
                    c2.metric("📉 标准差", f"{rel.get('std_score', 0)}",
                              delta="✅ 信度良好" if rel.get('is_reliable') else "⚠️ 争议较大",
                              delta_color="normal" if rel.get('is_reliable') else "inverse")
                    c3.metric("🔄 次数", f"{rel.get('runs', 0)} 次")

                st.divider()
                st.markdown("**📋 四维评分**")
                dims = get_genre_dimensions(current_genre)
                detail = d.get("detail", {})
                cols = st.columns(len(dims))
                for i, (label, total) in enumerate(dims.items()):
                    s = detail.get(label, 0)
                    with cols[i]:
                        st.metric(label, f"{s}/{total}")
                        st.progress(min(max(s / total if total > 0 else 0, 0.0), 1.0))

                st.divider()
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**✅ 亮点**")
                    for item in d.get("strengths", []):
                        st.info(f"• {item}")
                with c2:
                    st.markdown("**⚠️ 不足**")
                    for item in d.get("weaknesses", []):
                        st.warning(f"• {item}")
                st.markdown(f"**📝 总评：** {d.get('summary', '')}")

                st.divider()
                st.markdown("**🤝 人机协同校准**")
                dim_opts = list(dims.keys()) + ["总分"]
                dim = st.selectbox("有异议的维度", dim_opts)
                dev = st.radio("AI评分", ["偏高", "偏低", "基本准确"], horizontal=True)
                cmt = st.text_area("补充说明", placeholder="例如：立意虽然扣题但深度不足")
                if st.button("🔄 执行校准"):
                    if dev == "基本准确":
                        st.info("你认可AI评分，无需校准")
                    else:
                        with st.spinner("重新评估..."):
                            try:
                                new_d = recalibrate_score(
                                    st.session_state.current_title,
                                    st.session_state.current_body,
                                    d, dim, dev, cmt, current_genre
                                )
                                st.session_state.calibrated_dict = new_d
                                st.session_state.calibration_note = f"{dim}评分{dev}，{cmt}"
                                st.success("✅ 校准完成！")
                            except Exception as e:
                                st.error(f"校准失败：{e}")

                if st.session_state.calibrated_dict:
                    nd = st.session_state.calibrated_dict
                    st.markdown("**📊 原始 vs 校准**")
                    co1, co2 = st.columns(2)
                    with co1:
                        st.markdown("**🤖 原始**")
                        st.metric("总分", f"{d.get('score', 0)}/60")
                        for k, v in d.get("detail", {}).items():
                            st.text(f"{k}: {v}")
                    with co2:
                        st.markdown("**👨‍🏫 校准后**")
                        st.metric("总分", f"{nd.get('score', 0)}/60",
                                  delta=f"{nd.get('score', 0) - d.get('score', 0):+}")
                        for k, v in nd.get("detail", {}).items():
                            ov = d.get("detail", {}).get(k, 0)
                            st.text(f"{k}: {v} ({v - ov:+})")
                    st.info(f"📌 {nd.get('summary', '')}")

    # ---------- 修缮 ----------
    with tab_rev:
        if not st.session_state.has_diagnosed:
            st.warning("⚠️ 请先在「诊断报告」标签执行诊断")
        else:
            st.markdown("**🔧 定向修缮**")

            c1, c2 = st.columns(2)
            with c1:
                st.checkbox("① 提升中心思想/立意", key="opt1")
                st.checkbox("② 优化结构/层次", key="opt2")
            with c2:
                st.checkbox("③ 精炼语言表达", key="opt3")
                st.checkbox("④ 充实内容/细节", key="opt4")

            btn_c1, btn_c2 = st.columns(2)
            with btn_c1:
                if st.button("☑️ 全选", use_container_width=True):
                    st.session_state.opt1 = st.session_state.opt2 = True
                    st.session_state.opt3 = st.session_state.opt4 = True
                    st.rerun()
            with btn_c2:
                if st.button("⬜ 清空", use_container_width=True):
                    st.session_state.opt1 = st.session_state.opt2 = False
                    st.session_state.opt3 = st.session_state.opt4 = False
                    st.rerun()

            custom_text = st.text_area("自定义指令（可选）", height=60,
                                       placeholder="例如：增加排比句，强化结尾")

            style = st.selectbox("目标文风", ["标准", "批判犀利", "文学抒情", "逻辑严密"], index=0)

            st.markdown("**🎯 局部修缮（可选）**")
            st.caption("勾选要修改的段落，不勾选则修缮全文")
            paras = split_paragraphs(st.session_state.current_body)
            selected_paras = []
            if len(paras) > 1:
                for i, p in enumerate(paras):
                    if st.checkbox(f"第{i+1}段：{para_preview(p, 60)}", key=f"para_{i}"):
                        selected_paras.append(p)
                st.session_state.selected_paragraphs = selected_paras
                if selected_paras:
                    st.info(f"✅ 已选 {len(selected_paras)} 段")
                else:
                    st.info("📝 将执行全文修缮")
            else:
                st.info("📝 原文仅一段，全文修缮")
                st.session_state.selected_paragraphs = []

            use_sample = st.checkbox("📚 参考范文/素材", value=bool(st.session_state.sample_text))
            if use_sample:
                st.session_state.sample_text = st.text_area("粘贴范文", value=st.session_state.sample_text, height=100)

            if st.button("✍️ 执行修缮", type="primary", use_container_width=True):
                selected = []
                if st.session_state.get("opt1"): selected.append("1")
                if st.session_state.get("opt2"): selected.append("2")
                if st.session_state.get("opt3"): selected.append("3")
                if st.session_state.get("opt4"): selected.append("4")

                if not selected and not custom_text.strip():
                    st.warning("请勾选预设或输入自定义指令")
                elif not final_deepseek:
                    st.error("请配置DeepSeek API Key")
                else:
                    with st.spinner("精修中..."):
                        try:
                            revised = revise_essay(
                                st.session_state.current_title,
                                st.session_state.current_body,
                                st.session_state.diagnosis_raw,
                                current_genre,
                                selected,
                                custom_text,
                                style,
                                st.session_state.get("calibration_note", ""),
                                st.session_state.get("sample_text", ""),
                                st.session_state.get("selected_paragraphs", []),
                                grade
                            )
                            st.session_state.revised_text = revised
                            st.success("✅ 修缮完成！")

                            with st.spinner("评估效果..."):
                                try:
                                    rd = quick_diagnose(st.session_state.current_title, revised, current_genre)
                                    orig = st.session_state.diagnosis_dict
                                    st.session_state.comparison_report = {
                                        "original_score": orig.get("score"),
                                        "revised_score": rd.get("score"),
                                        "score_change": rd.get("score") - orig.get("score"),
                                        "original_details": orig.get("detail"),
                                        "revised_details": rd.get("detail"),
                                        "local_paragraphs": len(st.session_state.get("selected_paragraphs", []))
                                    }
                                except Exception as e:
                                    st.warning(f"闭环诊断失败：{e}")
                        except Exception as e:
                            st.error(f"修缮失败：{e}")

            if st.session_state.revised_text:
                st.subheader("📝 修缮稿")
                st.text_area("修缮后文章", value=st.session_state.revised_text, height=400)

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
                            ov = comp["original_details"].get(k, 0)
                            st.text(f"{k}: {v} ({v - ov:+})")
                    if comp.get("local_paragraphs", 0) > 0:
                        st.caption(f"🎯 修缮了 {comp['local_paragraphs']} 个段落")

                with st.expander("📖 逐句对比"):
                    html = generate_diff_html(st.session_state.current_body, st.session_state.revised_text)
                    st.markdown(f'<div style="background:#f8f9fa;padding:15px;border-radius:8px;font-family:monospace;font-size:14px;">{html}</div>',
                                unsafe_allow_html=True)
                    st.caption("🟢 新增/修改  🔴 删除")

                st.download_button("⬇️ 下载修缮稿", st.session_state.revised_text, "修缮稿.txt", "text/plain")
