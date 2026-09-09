# app.py
# AI写作教练 - 支持多文体 · 三段式工作流

import streamlit as st
import os
import base64
import time
import json
import re
import statistics
import difflib
import logging
from datetime import datetime
from io import BytesIO
from PIL import Image
from openai import OpenAI

# 导入配置
from prompts_config import (
    GENRE_CONFIG,
    get_genre_list,
    get_genre_label,
    get_genre_icon,
    get_genre_dimensions,
    get_genre_tips,
    build_idea_prompt,
    build_draft_prompt,
    build_diagnose_prompt,
    build_revise_prompt
)

# ============================================================
# API Key 配置
# ============================================================
DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
ZHIPU_API_KEY = st.secrets.get("ZHIPU_API_KEY", "")

st.set_page_config(page_title="AI写作教练", page_icon="✍️", layout="wide")

# ============================================================
# 日志系统
# ============================================================
def setup_logging():
    log_dir = "./logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, f"wenxiu_{datetime.now().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler()]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def log_action(action_type, details=""):
    if "logs" not in st.session_state:
        st.session_state.logs = []
    st.session_state.logs.append({
        "timestamp": datetime.now().isoformat(),
        "type": action_type,
        "details": details
    })
    logger.info(f"{action_type}: {details}")

# ============================================================
# 样式
# ============================================================
st.markdown("""
<style>
    .step-active { font-weight: bold; color: #0066cc; font-size: 1.1em; }
    .step-inactive { color: #999; }
    .diff-add { background-color: #d4edda; color: #155724; padding: 2px 4px; border-radius: 3px; }
    .diff-remove { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; }
    .genre-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 工具函数
# ============================================================
def compress_image(image_bytes, max_size=(1024, 1024), quality=85):
    img = Image.open(BytesIO(image_bytes))
    img.thumbnail(max_size, Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()

def validate_input(title, body):
    if not title or not title.strip():
        return False, "题目/话题不能为空"
    if not body or not body.strip():
        return False, "内容不能为空"
    word_count = len(body.strip())
    if word_count < 50:
        return False, f"内容仅{word_count}字，建议至少50字以保证诊断准确性"
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', body)
    chinese_ratio = len(chinese_chars) / max(len(body), 1)
    if chinese_ratio < 0.3:
        return False, "内容中汉字占比过低，请检查OCR结果或手动输入"
    return True, f"✅ 校验通过：正文{word_count}字，汉字占比{chinese_ratio:.1%}"

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

def extract_json(text):
    try:
        try:
            import json_repair
            return json_repair.repair_json(text)
        except:
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

# ============================================================
# API调用函数
# ============================================================
@st.cache_data(show_spinner=False)
def recognize_image(image_bytes, api_key):
    if not api_key:
        raise ValueError("请先设置智谱API Key")
    compressed = compress_image(image_bytes)
    image_base64 = base64.b64encode(compressed).decode("utf-8")
    client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")
    ocr_prompt = """请精准识别图片中的全部文字。图片包含了【题目/话题】和【正文】两部分。
请严格按以下格式输出：
===题目===
（识别出的题目）
===正文===
（识别出的正文）"""
    for attempt in range(5):
        try:
            response = client.chat.completions.create(
                model="glm-4.6v-flash",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                        {"type": "text", "text": ocr_prompt}
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

def call_deepseek(messages, temperature=0.3, max_tokens=800):
    """通用DeepSeek调用"""
    if not DEEPSEEK_API_KEY:
        raise ValueError("请配置DeepSeek API Key")
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(f"API调用失败: {e}")

def single_diagnose(title, body, genre, temperature=0.3):
    """单次诊断（根据文体动态调整）"""
    system_prompt = build_diagnose_prompt(title, body, genre)
    user_content = f"作文题目/话题：{title}\n\n正文：{body}"
    raw = call_deepseek([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ], temperature=temperature, max_tokens=800)
    return json.loads(extract_json(raw))

def diagnose_with_reliability(title, body, genre, runs=3):
    raw_results = []
    temps = [0.1, 0.3, 0.5]
    for i in range(runs):
        try:
            temp = temps[i % len(temps)]
            raw = single_diagnose(title, body, genre, temp)
            raw_results.append(raw)
        except Exception as e:
            logger.warning(f"第{i+1}次诊断失败: {e}")
            continue
    if len(raw_results) < 2:
        raise RuntimeError("有效诊断次数不足")
    scores = [r["score"] for r in raw_results]
    avg_score = round(statistics.mean(scores), 1)
    std_score = round(statistics.stdev(scores) if len(scores) > 1 else 0, 2)
    main = raw_results[0]
    main["reliability"] = {
        "avg_score": avg_score,
        "std_score": std_score,
        "is_reliable": std_score <= 2.0,
        "runs": len(raw_results)
    }
    return main

def quick_diagnose(title, body, genre):
    return single_diagnose(title, body, genre, 0.3)

def generate_ideas(title, genre, grade, hint=""):
    """构思破题"""
    prompt = build_idea_prompt(title, genre, grade, hint)
    return call_deepseek([{"role": "user", "content": prompt}], temperature=0.7, max_tokens=1000)

def expand_draft(title, genre, keywords, style, grade):
    """起草扩写"""
    prompt = build_draft_prompt(title, genre, keywords, style, grade)
    return call_deepseek([{"role": "user", "content": prompt}], temperature=0.8, max_tokens=1500)

def revise_essay(title, body, diagnosis_text, genre, selected_options,
                 custom_instruction="", style="标准", calibration_note="",
                 sample_text="", target_paras=None, grade="高三"):
    """修缮"""
    prompt, system_prompt = build_revise_prompt(
        title, body, diagnosis_text, genre, selected_options,
        custom_instruction, style, calibration_note,
        sample_text, target_paras, grade
    )
    return call_deepseek([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ], temperature=0.75, max_tokens=2048)

def recalibrate_score(title, body, original_diagnosis, dimension, deviation, comment, genre):
    """人机校准"""
    prompt = f"""【题目/话题】：{title}
【原文】：{body}
【AI原始评分】：{json.dumps(original_diagnosis, ensure_ascii=False)}
【教师反馈】：维度“{dimension}”认为评分 {deviation}，补充：{comment}
请重新审视，输出新的评分JSON：
{{"score": 总分, "detail": {{维度: 分数, ...}}, "summary": "校准后的总评"}}"""
    raw = call_deepseek([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=600)
    return json.loads(extract_json(raw))

# ============================================================
# Session State 初始化
# ============================================================
def init_session():
    defaults = {
        "ocr_title": "", "ocr_body": "", "diagnosis_raw": "", "diagnosis_dict": {},
        "revised_text": "", "calibration_note": "", "calibrated_dict": {},
        "current_title": "", "current_body": "", "current_genre": "议论文",
        "logs": [], "preset_instructions": [], "has_diagnosed": False,
        "has_revised": False, "comparison_report": None,
        "sample_text": "", "selected_paragraphs": [],
        "grade": "高三", "ideas_output": "", "draft_output": "",
        "writing_stage": "构思"  # 构思 / 起草 / 修缮
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session()

def reset_all():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.header("⚙️ 配置")
    user_zhipu = st.text_input("智谱API Key", value="", type="password", placeholder="留空则使用云端Secret")
    user_deepseek = st.text_input("DeepSeek API Key", value="", type="password", placeholder="留空则使用云端Secret")
    final_zhipu = user_zhipu if user_zhipu else ZHIPU_API_KEY
    final_deepseek = user_deepseek if user_deepseek else DEEPSEEK_API_KEY
    
    col1, col2 = st.columns(2)
    with col1:
        st.success("✅ 智谱") if final_zhipu else st.warning("⚠️ 智谱")
    with col2:
        st.success("✅ DeepSeek") if final_deepseek else st.warning("⚠️ DeepSeek")
    
    st.markdown("---")
    if st.button("🔄 重置", use_container_width=True):
        reset_all()
    
    if st.button("📥 导出报告", use_container_width=True):
        report = {
            "timestamp": datetime.now().isoformat(),
            "title": st.session_state.get("current_title", ""),
            "genre": st.session_state.get("current_genre", ""),
            "diagnosis": st.session_state.get("diagnosis_dict", {}),
            "comparison": st.session_state.get("comparison_report", {}),
            "logs": st.session_state.get("logs", [])
        }
        st.download_button("⬇️ 下载", json.dumps(report, ensure_ascii=False, indent=2), "报告.json", "application/json")
    
    st.markdown("---")
    st.caption("✍️ AI写作教练 v3.0")

# ============================================================
# 主界面
# ============================================================
st.title("✍️ AI写作教练")
st.caption("构思 · 起草 · 修缮 — 多文体智能写作助手")

# ===== 文体选择 =====
genre_col, grade_col = st.columns([2, 1])
with genre_col:
    genre_list = get_genre_list()
    genre_labels = [f"{get_genre_icon(g)} {get_genre_label(g)}" for g in genre_list]
    selected_idx = genre_list.index(st.session_state.current_genre) if st.session_state.current_genre in genre_list else 0
    genre_label = st.selectbox("选择文体", genre_labels, index=selected_idx)
    current_genre = genre_list[genre_labels.index(genre_label)]
    st.session_state.current_genre = current_genre

with grade_col:
    grade = st.selectbox("年级", ["高一", "高二", "高三"], 
                         index=["高一", "高二", "高三"].index(st.session_state.grade))
    st.session_state.grade = grade

# ===== 写作阶段 =====
st.markdown("---")
stage = st.radio(
    "选择写作阶段",
    ["🧠 构思破题", "✍️ 起草扩写", "📊 诊断修缮"],
    horizontal=True,
    index=["构思", "起草", "修缮"].index(st.session_state.writing_stage)
)
stage_map = {"🧠 构思破题": "构思", "✍️ 起草扩写": "起草", "📊 诊断修缮": "修缮"}
st.session_state.writing_stage = stage_map[stage]

# ============================================================
# 阶段一：构思破题
# ============================================================
if st.session_state.writing_stage == "构思":
    st.markdown(f"### 🧠 构思破题 · {get_genre_icon(current_genre)} {get_genre_label(current_genre)}")
    st.caption(f"💡 {get_genre_tips(current_genre)}")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        title = st.text_input("题目/话题", value=st.session_state.ocr_title, placeholder="输入作文题目或写作话题")
        hint = st.text_area("补充说明（可选）", placeholder="例如：需要包含辩证思考 / 希望偏向抒情风格")
    with col2:
        st.markdown("**📌 构思产出**")
        if st.button("🚀 生成构思", type="primary", use_container_width=True):
            if not title.strip():
                st.error("请先输入题目或话题")
            elif not final_deepseek:
                st.error("请配置DeepSeek API Key")
            else:
                with st.spinner("正在生成构思..."):
                    try:
                        ideas = generate_ideas(title, current_genre, grade, hint)
                        st.session_state.ideas_output = ideas
                        st.session_state.ocr_title = title
                        log_action("构思生成", f"{current_genre}: {title[:20]}")
                    except Exception as e:
                        st.error(f"生成失败: {e}")
        
        if st.session_state.ideas_output:
            st.markdown("---")
            st.markdown("**🧠 构思结果**")
            st.markdown(st.session_state.ideas_output)

# ============================================================
# 阶段二：起草扩写
# ============================================================
elif st.session_state.writing_stage == "起草":
    st.markdown(f"### ✍️ 起草扩写 · {get_genre_icon(current_genre)} {get_genre_label(current_genre)}")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        title = st.text_input("题目/话题", value=st.session_state.ocr_title)
        keywords = st.text_area("思路/关键词", height=150, placeholder="输入你的核心想法、关键词或提纲，AI将帮你扩展成完整文章")
        style = st.selectbox("目标文风", ["标准", "批判犀利", "文学抒情", "逻辑严密"], index=0)
    with col2:
        st.markdown("**📌 草稿产出**")
        if st.button("✍️ 生成草稿", type="primary", use_container_width=True):
            if not title.strip():
                st.error("请先输入题目")
            elif not keywords.strip():
                st.error("请输入思路或关键词")
            elif not final_deepseek:
                st.error("请配置DeepSeek API Key")
            else:
                with st.spinner("正在生成草稿..."):
                    try:
                        draft = expand_draft(title, current_genre, keywords, style, grade)
                        st.session_state.draft_output = draft
                        st.session_state.ocr_title = title
                        st.session_state.ocr_body = draft
                        log_action("起草生成", f"{current_genre}: {title[:20]}")
                    except Exception as e:
                        st.error(f"生成失败: {e}")
        
        if st.session_state.draft_output:
            st.markdown("---")
            st.markdown("**📝 草稿预览**")
            st.text_area("生成的草稿", value=st.session_state.draft_output, height=300)
            st.info("💡 草稿已自动保存，可切换到「诊断修缮」阶段进行评分和精修")

# ============================================================
# 阶段三：诊断修缮
# ============================================================
else:
    st.markdown(f"### 📊 诊断修缮 · {get_genre_icon(current_genre)} {get_genre_label(current_genre)}")
    
    # ---- 输入区 ----
    tab_input, tab_diagnosis, tab_revise = st.tabs(["📝 输入", "📊 诊断报告", "🔧 修缮"])
    
    with tab_input:
        col1, col2 = st.columns([1, 1])
        with col1:
            uploaded_file = st.file_uploader("上传照片", type=["jpg", "jpeg", "png", "bmp"])
            if uploaded_file is not None:
                if st.button("🔍 OCR识别"):
                    if not final_zhipu:
                        st.error("⚠️ 请配置智谱API Key")
                    else:
                        with st.spinner("识别中..."):
                            try:
                                result = recognize_image(uploaded_file.getvalue(), final_zhipu)
                                st.session_state.ocr_title = result["title"]
                                st.session_state.ocr_body = result["body"]
                                st.success("✅ 识别完成！")
                                log_action("OCR识别", "成功")
                            except Exception as e:
                                st.error(f"识别失败: {e}")
        with col2:
            title = st.text_area("题目/话题", value=st.session_state.ocr_title, height=80)
            body = st.text_area("正文", value=st.session_state.ocr_body, height=300)
            st.session_state.ocr_title = title
            st.session_state.ocr_body = body
            
            if body.strip():
                is_valid, msg = validate_input(title, body)
                if is_valid:
                    st.success(msg)
                else:
                    st.warning(f"⚠️ {msg}")
            
            if st.button("📌 确认文本 → 开始诊断", type="primary", use_container_width=True):
                is_valid, msg = validate_input(title, body)
                if is_valid:
                    st.session_state.current_title = title
                    st.session_state.current_body = body
                    st.success("✅ 文本已确认，请切换到「诊断报告」标签")
                    log_action("文本确认", f"字数:{len(body)}")
                else:
                    st.error(f"❌ {msg}")
    
    # ---- 诊断报告 ----
    with tab_diagnosis:
        if not st.session_state.get("current_title"):
            st.info("👆 请先在「输入」标签确认文本")
        else:
            if st.button("🚀 执行多维诊断", type="primary"):
                if not final_deepseek:
                    st.error("⚠️ 请配置DeepSeek API Key")
                else:
                    with st.spinner("正在进行3次独立诊断..."):
                        try:
                            diagnosis = diagnose_with_reliability(
                                st.session_state.current_title,
                                st.session_state.current_body,
                                current_genre,
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
                    c1, c2, c3 = st.columns(3)
                    c1.metric("📈 平均分", f"{reliability.get('avg_score', 0)}/60")
                    c2.metric("📉 标准差", f"{reliability.get('std_score', 0)}",
                              delta="✅ 信度良好" if reliability.get('is_reliable') else "⚠️ 争议较大",
                              delta_color="normal" if reliability.get('is_reliable') else "inverse")
                    c3.metric("🔄 次数", f"{reliability.get('runs', 0)} 次")
                
                st.divider()
                st.subheader("📋 评分详情")
                dims = get_genre_dimensions(current_genre)
                detail = d.get("detail", {})
                cols = st.columns(len(dims))
                for idx, (label, total) in enumerate(dims.items()):
                    score = detail.get(label, 0)
                    with cols[idx]:
                        st.metric(label, f"{score}/{total}")
                        st.progress(score/total if total>0 else 0)
                
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
                
                # 人机校准
                st.divider()
                st.subheader("🤝 人机协同校准")
                with st.form("calibration_form"):
                    dim_list = list(dims.keys())
                    dim = st.selectbox("有异议的维度", dim_list + ["总分"])
                    deviation = st.radio("你认为AI评分", ["偏高", "偏低", "基本准确"])
                    comment = st.text_area("补充说明", placeholder="例如：立意虽然扣题但深度不足")
                    if st.form_submit_button("🔄 执行校准"):
                        if deviation == "基本准确":
                            st.info("你认可AI评分，无需校准")
                        else:
                            with st.spinner("重新评估..."):
                                try:
                                    new_score = recalibrate_score(
                                        st.session_state.current_title,
                                        st.session_state.current_body,
                                        d, dim, deviation, comment, current_genre
                                    )
                                    st.session_state.calibrated_dict = new_score
                                    st.session_state.calibration_note = f"{dim}评分{deviation}"
                                    st.success("✅ 校准完成！")
                                    log_action("校准", f"{dim}:{deviation}")
                                except Exception as e:
                                    st.error(f"校准失败: {e}")
                
                if st.session_state.calibrated_dict:
                    new_d = st.session_state.calibrated_dict
                    st.markdown("**📊 原始 vs 校准**")
                    co1, co2 = st.columns(2)
                    with co1:
                        st.markdown("**🤖 原始**")
                        st.metric("总分", f"{d.get('score', 0)}/60")
                        for k, v in d.get("detail", {}).items():
                            st.text(f"{k}: {v}")
                    with co2:
                        st.markdown("**👨‍🏫 校准后**")
                        st.metric("总分", f"{new_d.get('score', 0)}/60",
                                  delta=f"{new_d.get('score', 0) - d.get('score', 0):+}")
                        for k, v in new_d.get("detail", {}).items():
                            orig_v = d.get("detail", {}).get(k, 0)
                            st.text(f"{k}: {v} ({v - orig_v:+})")
                    st.info(f"📌 {new_d.get('summary', '')}")
    
    # ---- 修缮 ----
    with tab_revise:
        if not st.session_state.has_diagnosed:
            st.warning("⚠️ 请先在「诊断报告」标签执行诊断")
        else:
            st.markdown("**🔧 定向修缮**")
            
            # 预设
            c1, c2 = st.columns(2)
            with c1:
                opt1 = st.checkbox("① 提升中心思想/立意", key="opt1")
                opt2 = st.checkbox("② 优化结构/层次", key="opt2")
            with c2:
                opt3 = st.checkbox("③ 精炼语言表达", key="opt3")
                opt4 = st.checkbox("④ 充实内容/细节", key="opt4")
            
            # 自定义
            custom_text = st.text_area("自定义指令（可选）", height=60, placeholder="例如：增加排比句，强化结尾", key="custom_text")
            
            # 文风
            style = st.selectbox("目标文风", ["标准", "批判犀利", "文学抒情", "逻辑严密"], index=0)
            
            # 局部修缮
            st.markdown("**🎯 局部修缮（可选）**")
            st.caption("勾选要修改的段落，不勾选则修缮全文")
            paras = split_paragraphs(st.session_state.current_body)
            selected_paras = []
            if len(paras) > 1:
                for i, p in enumerate(paras):
                    if st.checkbox(f"第{i+1}段：{get_paragraph_preview(p, 60)}", key=f"para_{i}"):
                        selected_paras.append(p)
                st.session_state.selected_paragraphs = selected_paras
                if selected_paras:
                    st.info(f"✅ 已选 {len(selected_paras)} 段")
                else:
                    st.info("📝 将执行全文修缮")
            else:
                st.info("📝 原文仅有一段，执行全文修缮")
            
            # 高级选项
            use_sample = st.checkbox("📚 参考范文/素材", value=bool(st.session_state.sample_text))
            if use_sample:
                sample_text = st.text_area("粘贴范文", value=st.session_state.sample_text, height=100)
                st.session_state.sample_text = sample_text
            
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
                    with st.spinner("正在精修..."):
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
                            st.session_state.has_revised = True
                            st.success("✅ 修缮完成！")
                            log_action("修缮", f"{current_genre}")
                            
                            # 闭环诊断
                            with st.spinner("评估效果..."):
                                try:
                                    revised_diag = quick_diagnose(
                                        st.session_state.current_title,
                                        revised,
                                        current_genre
                                    )
                                    orig = st.session_state.diagnosis_dict
                                    comp = {
                                        "original_score": orig.get("score"),
                                        "revised_score": revised_diag.get("score"),
                                        "score_change": revised_diag.get("score") - orig.get("score"),
                                        "original_details": orig.get("detail"),
                                        "revised_details": revised_diag.get("detail"),
                                        "local_paragraphs": len(st.session_state.get("selected_paragraphs", []))
                                    }
                                    st.session_state.comparison_report = comp
                                    log_action("闭环诊断", f"提升:{comp['score_change']:+}分")
                                except Exception as e:
                                    st.warning(f"闭环诊断失败: {e}")
                        except Exception as e:
                            st.error(f"修缮失败: {e}")
            
            # 显示结果
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
                            orig_v = comp["original_details"].get(k, 0)
                            st.text(f"{k}: {v} ({v - orig_v:+})")
                    if comp.get("local_paragraphs", 0) > 0:
                        st.caption(f"🎯 修缮了 {comp['local_paragraphs']} 个段落")
                
                with st.expander("📖 逐句对比"):
                    diff_html = generate_diff_html(
                        st.session_state.current_body,
                        st.session_state.revised_text
                    )
                    st.markdown(f'<div style="background:#f8f9fa;padding:15px;border-radius:8px;font-family:monospace;font-size:14px;">{diff_html}</div>',
                               unsafe_allow_html=True)
                    st.caption("🟢 新增/修改  🔴 删除")
                
                st.download_button("⬇️ 下载修缮稿", st.session_state.revised_text, "修缮稿.txt", "text/plain")

# ============================================================
# 底部
# ============================================================
st.sidebar.markdown("---")
st.sidebar.caption("✍️ AI写作教练 · 支持议论文/记叙文/散文")
