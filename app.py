# app.py
# AI作文批改研究平台 - 完整版
# 功能：OCR识别 · 多维诊断 · 人机校准 · 段落级修缮 · 闭环验证

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

# 导入提示词配置
from prompts_config import (
    DIAGNOSE_SYSTEM_PROMPT,
    REVISE_SYSTEM_PROMPT,
    build_revise_prompt,
    build_revision_plan_prompt,
    build_calibration_prompt,
    build_ocr_prompt
)

# ============================================================
# ⚠️ API Key 配置（从 secrets 读取）
# ============================================================
DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
ZHIPU_API_KEY = st.secrets.get("ZHIPU_API_KEY", "")

st.set_page_config(page_title="AI作文批改研究平台", page_icon="📝", layout="wide")

# ============================================================
# 日志系统
# ============================================================
def setup_logging():
    """配置日志"""
    log_dir = "./logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, f"wenxiu_{datetime.now().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def log_action(action_type, details=""):
    """记录操作到日志"""
    if "logs" not in st.session_state:
        st.session_state.logs = []
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": action_type,
        "details": details
    }
    st.session_state.logs.append(entry)
    logger.info(f"{action_type}: {details}")

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
    .step-active { font-weight: bold; color: #0066cc; font-size: 1.1em; }
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

# ============================================================
# 工具函数
# ============================================================
def compress_image(image_bytes, max_size=(1024, 1024), quality=85):
    """压缩图片"""
    img = Image.open(BytesIO(image_bytes))
    img.thumbnail(max_size, Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()

def validate_input(title, body):
    """输入预检查"""
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
    # 特殊字符检测
    if len(re.findall(r'[<>]', body)) > 0:
        return False, "正文包含非法字符（< >），请清理后重试"
    return True, f"✅ 校验通过：正文{word_count}字，汉字占比{chinese_ratio:.1%}"

def clean_text(text):
    """清洗文本，移除特殊字符和超长内容"""
    # 移除HTML标签
    text = re.sub(r'<[^>]+>', '', text)
    # 移除控制字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # 截断过长的文本（防止超Token）
    if len(text) > 3000:
        text = text[:3000] + "\n...（内容过长已截断）"
    return text

def split_paragraphs(text):
    """按段落分割"""
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
    """提取JSON（增强版）"""
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

def generate_diff_html(original, revised):
    """生成Diff对比"""
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
    """OCR识别"""
    if not api_key:
        raise ValueError("请先设置智谱API Key")
    compressed = compress_image(image_bytes)
    image_base64 = base64.b64encode(compressed).decode("utf-8")
    client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")
    ocr_prompt = build_ocr_prompt()
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

def single_diagnose(title, body, api_key, temperature=0.3):
    """单次诊断"""
    if not api_key:
        raise ValueError("请配置DeepSeek API Key")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": DIAGNOSE_SYSTEM_PROMPT},
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
    """多次诊断+信度校验"""
    raw_results = []
    temps = [0.1, 0.3, 0.5] * ((runs // 3) + 1)
    for i in range(runs):
        try:
            temp = temps[i % len(temps)]
            raw = single_diagnose(title, body, api_key, temp)
            raw_results.append(raw)
        except Exception as e:
            logger.warning(f"第{i+1}次诊断失败: {e}")
            continue
    if len(raw_results) < 2:
        raise RuntimeError("有效诊断次数不足")
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
    """快速诊断（用于闭环对比）"""
    return single_diagnose(title, body, api_key, temperature=0.3)

def recalibrate_score(title, body, original_diagnosis, dimension, deviation, comment):
    """人机校准"""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    prompt = build_calibration_prompt(
        title, body, 
        json.dumps(original_diagnosis, ensure_ascii=False),
        dimension, deviation, comment
    )
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

def get_revision_plan(title, body, diagnosis_text, selected_options, custom_instruction, style):
    """生成修改计划"""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    prompt = build_revision_plan_prompt(
        title, body, diagnosis_text, selected_options, custom_instruction, style
    )
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"生成计划失败: {e}")
        return "（生成计划失败，可直接执行修缮）"

def revise_essay(title, original_body, diagnosis_text, selected_options, 
                 calibration_note="", custom_instruction="", style="标准",
                 sample_text="", target_paras=None, grade="高三"):
    """修缮引擎"""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    
    # 清洗原文
    clean_body = clean_text(original_body)
    
    # 构建Prompt
    prompt = build_revise_prompt(
        title, clean_body, diagnosis_text, selected_options,
        custom_instruction, style, calibration_note,
        sample_text, target_paras, grade
    )
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": REVISE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.75,
            max_tokens=2048
        )
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(f"修缮失败: {e}")

# ============================================================
# Streamlit UI
# ============================================================

def init_session():
    defaults = {
        "ocr_title": "", "ocr_body": "", "diagnosis_raw": "", "diagnosis_dict": {},
        "revised_text": "", "calibration_note": "", "calibrated_dict": {},
        "current_title": "", "current_body": "", "step": 1,
        "logs": [], "preset_instructions": [], "select_all": False,
        "has_diagnosed": False, "has_revised": False, "comparison_report": None,
        "sample_text": "", "revision_plan": "", "selected_paragraphs": [],
        "grade": "高三"
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
    steps = ["📄 作文录入", "📊 多维诊断", "✍️ 智能修缮"]
    current = st.session_state.step
    cols = st.columns(len(steps))
    for i, (col, label) in enumerate(zip(cols, steps)):
        with col:
            if i + 1 == current:
                st.markdown(f"<span class='step-active'>👉 {label}</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"<span class='step-inactive'>{label}</span>", unsafe_allow_html=True)
    st.divider()

# ============================================================
# 主界面
# ============================================================
st.title("📝 AI作文批改研究平台")
st.caption("信度校验 · 人机协同 · 段落级修缮 · 闭环评价")

# 侧边栏
with st.sidebar:
    st.header("⚙️ 配置")
    user_zhipu = st.text_input("智谱API Key", value="", type="password", placeholder="留空则使用云端Secret")
    user_deepseek = st.text_input("DeepSeek API Key", value="", type="password", placeholder="留空则使用云端Secret")
    
    final_zhipu = user_zhipu if user_zhipu else ZHIPU_API_KEY
    final_deepseek = user_deepseek if user_deepseek else DEEPSEEK_API_KEY
    
    col_status1, col_status2 = st.columns(2)
    with col_status1:
        if final_zhipu:
            st.success("✅ 智谱")
        else:
            st.warning("⚠️ 智谱")
    with col_status2:
        if final_deepseek:
            st.success("✅ DeepSeek")
        else:
            st.warning("⚠️ DeepSeek")
    
    st.markdown("---")
    if st.button("🔄 重置所有数据", use_container_width=True):
        reset_all()
    
    if st.button("📥 导出诊断报告", use_container_width=True):
        report = {
            "timestamp": datetime.now().isoformat(),
            "title": st.session_state.get("current_title", ""),
            "diagnosis": st.session_state.get("diagnosis_dict", {}),
            "comparison": st.session_state.get("comparison_report", {}),
            "logs": st.session_state.get("logs", [])
        }
        report_json = json.dumps(report, ensure_ascii=False, indent=2)
        st.download_button("⬇️ 下载", report_json, "诊断报告.json", "application/json")
    
    st.markdown("---")
    st.caption("📌 研究平台 v2.0")

# 步骤条
render_step_bar()

# ===== 主标签页 =====
tab1, tab2, tab3 = st.tabs(["📄 作文录入", "📊 多维诊断", "✍️ 智能修缮"])

# ---------- TAB1: 录入 ----------
with tab1:
    st.session_state.step = 1
    col1, col2 = st.columns([1, 1])
    with col1:
        uploaded_file = st.file_uploader("上传作文照片", type=["jpg", "jpeg", "png", "bmp"])
        if uploaded_file is not None:
            if st.button("🔍 识别文字 (OCR)", type="primary"):
                if not final_zhipu:
                    st.error("⚠️ 请配置智谱API Key")
                else:
                    with st.spinner("正在识别..."):
                        try:
                            result = recognize_image(uploaded_file.getvalue(), final_zhipu)
                            st.session_state.ocr_title = result["title"]
                            st.session_state.ocr_body = result["body"]
                            st.success("✅ 识别完成！")
                            log_action("OCR识别", "成功")
                        except Exception as e:
                            st.error(f"识别失败: {e}")
    with col2:
        st.markdown("**✏️ 编辑区**")
        grade = st.selectbox("年级（影响评分策略）", ["高三", "高二", "高一"], index=0)
        st.session_state.grade = grade
        
        title = st.text_area("作文题目", value=st.session_state.ocr_title, height=80)
        body = st.text_area("作文正文", value=st.session_state.ocr_body, height=300)
        
        st.session_state.ocr_title = title
        st.session_state.ocr_body = body
        
        if body.strip():
            is_valid, msg = validate_input(title, body)
            if is_valid:
                st.success(msg)
            else:
                st.warning(f"⚠️ {msg}")
        
        if st.button("📌 确认文本 → 进入诊断", type="primary", use_container_width=True):
            is_valid, msg = validate_input(title, body)
            if is_valid:
                st.session_state.current_title = title
                st.session_state.current_body = body
                st.session_state.step = 2
                st.success("✅ 文本已锁定！")
                log_action("文本确认", f"字数:{len(body)}")
            else:
                st.error(f"❌ {msg}")

# ---------- TAB2: 诊断 ----------
with tab2:
    st.session_state.step = 2
    if not st.session_state.get("current_title"):
        st.info("👆 请先在「作文录入」确认文本")
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
                col_m1, col_m2, col_m3 = st.columns(3)
                col_m1.metric("📈 平均分", f"{reliability.get('avg_score', 0)}/60")
                col_m2.metric("📉 标准差", f"{reliability.get('std_score', 0)}", 
                              delta="✅ 信度良好" if reliability.get('is_reliable') else "⚠️ 争议较大",
                              delta_color="normal" if reliability.get('is_reliable') else "inverse")
                col_m3.metric("🔄 次数", f"{reliability.get('runs', 0)} 次")
            
            st.divider()
            st.subheader("📋 四维评分")
            detail = d.get("detail", {})
            cols = st.columns(4)
            metrics = [("立意", 20), ("结构", 15), ("语言", 15), ("论据", 10)]
            for idx, (label, total) in enumerate(metrics):
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
            
            # ===== 人机校准 =====
            st.divider()
            st.subheader("🤝 人机协同校准")
            with st.form("calibration_form"):
                dim = st.selectbox("有异议的维度", ["立意", "结构", "语言", "论据", "总分"])
                deviation = st.radio("你认为AI评分", ["偏高", "偏低", "基本准确"])
                comment = st.text_area("补充说明", placeholder="例如：立意虽然扣题，但深度不足")
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
                                d, dim, deviation, comment
                            )
                            st.session_state.calibrated_dict = new_score
                            st.session_state.calibration_note = f"{dim}评分{deviation}，{comment}"
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
            
            if st.button("✍️ 进入修缮 →", type="primary"):
                st.session_state.step = 3
                st.rerun()

# ---------- TAB3: 修缮 ----------
with tab3:
    st.session_state.step = 3
    if not st.session_state.get("current_title"):
        st.info("👆 请先在「作文录入」确认文本")
    elif not st.session_state.has_diagnosed:
        st.warning("⚠️ 请先执行诊断")
    else:
        st.subheader("🔧 全维度定向修缮")
        
        # ===== 范文上传 =====
        with st.expander("📚 参考范文/素材（可选）"):
            sample_file = st.file_uploader("上传范文 (txt/md)", type=["txt", "md"])
            if sample_file:
                sample_content = sample_file.read().decode("utf-8")
                st.session_state.sample_text = sample_content
                st.success(f"✅ 已加载 ({len(sample_content)}字)")
            sample_textarea = st.text_area("或直接粘贴", value=st.session_state.sample_text, height=150)
            if sample_textarea:
                st.session_state.sample_text = sample_textarea
        
        # ===== 预设管理 =====
        with st.expander("💾 预设指令"):
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                new_preset = st.text_area("新预设", height=60, placeholder="例如：增加对比论证")
                if st.button("保存"):
                    if new_preset.strip():
                        if "preset_instructions" not in st.session_state:
                            st.session_state.preset_instructions = []
                        st.session_state.preset_instructions.append(new_preset.strip())
                        st.success("已保存")
            with col_p2:
                if st.session_state.get("preset_instructions"):
                    idx = st.selectbox("加载", range(len(st.session_state.preset_instructions)),
                                       format_func=lambda i: st.session_state.preset_instructions[i][:30])
                    if st.button("加载"):
                        st.session_state.custom_text = st.session_state.preset_instructions[idx]
                        st.success("已加载")
        
        # ===== 修缮表单 =====
        with st.form("revise_form"):
            st.markdown("**① 快捷预设**")
            col_o1, col_o2 = st.columns(2)
            with col_o1:
                opt1 = st.checkbox("① 提升思维深度", key="opt1")
                opt2 = st.checkbox("② 优化文章结构", key="opt2")
            with col_o2:
                opt3 = st.checkbox("③ 精炼语言表达", key="opt3")
                opt4 = st.checkbox("④ 充实论据阐释", key="opt4")
            c1, c2 = st.columns(2)
            with c1:
                if st.form_submit_button("☑️ 全选"):
                    st.session_state.opt1 = st.session_state.opt2 = st.session_state.opt3 = st.session_state.opt4 = True
            with c2:
                if st.form_submit_button("⬜ 清空"):
                    st.session_state.opt1 = st.session_state.opt2 = st.session_state.opt3 = st.session_state.opt4 = False
            
            st.divider()
            
            st.markdown("**② 自定义指令**")
            custom_text = st.text_area("修改要求", height=80, 
                                      placeholder="例如：增加排比句，强化结尾升华",
                                      key="custom_text")
            
            st.markdown("**③ 文风迁移**")
            style_option = st.selectbox("目标文风", ["标准", "批判犀利", "文学抒情", "逻辑严密"], index=0)
            style_map = {"标准": "标准", "批判犀利": "批判犀利", 
                        "文学抒情": "文学抒情", "逻辑严密": "逻辑严密"}
            selected_style = style_map[style_option]
            
            st.divider()
            
            # ===== 局部修缮（段落勾选） =====
            st.markdown("**④ 局部修缮**")
            st.caption("勾选要修改的段落，不勾选则修缮全文")
            
            paragraphs = split_paragraphs(st.session_state.current_body)
            
            if len(paragraphs) > 1:
                selected_indices = []
                for i, para in enumerate(paragraphs):
                    preview = get_paragraph_preview(para, 80)
                    checked = st.checkbox(
                        f"**第{i+1}段**：{preview}",
                        key=f"para_{i}",
                        value=False
                    )
                    if checked:
                        selected_indices.append(i)
                
                col_sel1, col_sel2 = st.columns(2)
                with col_sel1:
                    if st.form_submit_button("☑️ 全选段落"):
                        for i in range(len(paragraphs)):
                            st.session_state[f"para_{i}"] = True
                with col_sel2:
                    if st.form_submit_button("⬜ 清空段落"):
                        for i in range(len(paragraphs)):
                            st.session_state[f"para_{i}"] = False
                
                selected_paras = [paragraphs[i] for i in selected_indices]
                st.session_state.selected_paragraphs = selected_paras
                
                if selected_paras:
                    st.info(f"✅ 已选 **{len(selected_paras)}** 段进行局部修缮")
                else:
                    st.info("📝 将执行 **全文修缮**")
            else:
                st.info("📝 原文仅有一段，执行全文修缮")
                st.session_state.selected_paragraphs = []
            
            st.divider()
            
            st.markdown("**⑤ 高级选项**")
            show_plan = st.checkbox("📋 先显示修改计划", value=False)
            use_calibration = st.checkbox("📌 联动校准反馈", value=bool(st.session_state.get("calibration_note")))
            use_sample = st.checkbox("📚 模仿范文风格", value=bool(st.session_state.get("sample_text")))
            
            submit_revise = st.form_submit_button("✍️ 执行修缮", type="primary", use_container_width=True)
        
        # ===== 处理修缮 =====
        if submit_revise:
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
                if show_plan:
                    with st.spinner("生成修改计划..."):
                        try:
                            plan = get_revision_plan(
                                st.session_state.current_title,
                                st.session_state.current_body,
                                st.session_state.diagnosis_raw,
                                selected,
                                custom_text,
                                selected_style
                            )
                            st.session_state.revision_plan = plan
                            log_action("生成计划", "成功")
                        except Exception as e:
                            st.error(f"生成计划失败: {e}")
                
                if st.session_state.get("revision_plan"):
                    st.markdown("**📋 修改计划**")
                    st.info(st.session_state.revision_plan)
                    if not st.button("✅ 确认执行"):
                        st.stop()
                
                with st.spinner("正在精修文章..."):
                    try:
                        cal_note = st.session_state.calibration_note if use_calibration else ""
                        sample = st.session_state.sample_text if use_sample else ""
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
                            st.session_state.get("grade", "高三")
                        )
                        st.session_state.revised_text = revised
                        st.session_state.has_revised = True
                        st.success("✅ 修缮完成！")
                        log_action("修缮", f"局部段数:{len(target_paras)}")
                        
                        with st.spinner("评估修缮效果..."):
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
        
        # ===== 显示结果 =====
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
                        orig = comp["original_details"].get(k, 0)
                        st.text(f"{k}: {v} ({v - orig:+})")
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
            
            st.download_button(
                label="⬇️ 下载修缮稿",
                data=st.session_state.revised_text,
                file_name="修缮稿.txt",
                mime="text/plain",
                use_container_width=True
            )

# ============================================================
# 底部
# ============================================================
st.sidebar.markdown("---")
st.sidebar.caption("📌 信度校验 · 人机协同 · 段落级修缮 · 闭环评价")
