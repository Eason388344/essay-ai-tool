
import streamlit as st
import os
import base64
import time
import json
import re
from openai import OpenAI
from PIL import Image
import io

# ============================================================
# ⚠️ 请在这里填入你的真实 API KeyDEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
ZHIPU_API_KEY = st.secrets.get("ZHIPU_API_KEY", "")
# ============================================================
        # 改成你申请的
# ============================================================

st.set_page_config(page_title="AI作文批改系统", page_icon="📝", layout="wide")

# ====================== OCR识别（智谱） ======================
def recognize_image(image_bytes, api_key):
    """识别图片，自动分离【作文题目】和【作文正文】"""
    if not api_key:
        raise ValueError("请先设置智谱API Key")
    
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
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
                max_tokens=2048
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

# ====================== AI诊断（DeepSeek） ======================
def diagnose_essay(title, body):
    """诊断作文：切题度 + 按60分量表评分"""
    system_prompt = f"""你是一位资深高考作文阅卷老师。请严格按以下标准对作文进行评分（满分60分）：

【审题立意】（20分）：是否精准理解题目核心？是否存在概念置换、偷换主语、关键遗漏？是否切题？
【结构与逻辑】（15分）：层次是否分明？论证是否严密？是否有递进或对比逻辑？
【语言表达】（15分）：是否流畅精准？有无语病？节奏是否得当？
【论据与内容】（10分）：素材是否充实？阐释是否深入？是否有效支撑论点？

请按以下JSON格式输出（确保是有效JSON，不要包含其他废话）：
{{
  "score": 总分(整数),
  "detail": {{"立意": 分数, "结构": 分数, "语言": 分数, "论据": 分数}},
  "strengths": ["优点1", "优点2", "优点3"],
  "weaknesses": ["不足1", "不足2", "不足3"],
  "summary": "一句话总评(20字以内)"
}}"""

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"作文题目：{title}\n\n学生作文：{body}"}
            ],
            temperature=0.3,
            max_tokens=800
        )
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(f"诊断失败: {e}")

# ====================== AI修缮（DeepSeek，支持多选） ======================
def revise_essay(title, original_body, diagnosis_text, selected_options):
    """根据选中的复选框方向修缮文章"""
    option_map = {
        "1": "提升思维深度：运用概念界定、三级追问、批判反思等方法，让立意更深刻，强化因果溯源。",
        "2": "优化文章结构：按递进式或对比式逻辑重组段落，使层次清晰，逻辑推进感强。",
        "3": "精炼语言表达：替换模糊词汇，优化长短句节奏，使用隐性逻辑连接词（如'这意味着''究其本质'），消除语病。",
        "4": "充实论据阐释：剪裁现有素材，增加'假设追问'（倘若……那么……），强化论据与论点的咬合。"
    }
    
    instructions = [option_map[key] for key in sorted(selected_options) if key in option_map]
    if not instructions:
        return "未选择任何修缮方向，请返回勾选。"

    combined_instruction = "；".join(instructions)
    
    prompt = f"""【作文题目】：{title}

【原文】：
{original_body}

【诊断结果】：
{diagnosis_text}

【修缮要求】：
请基于原文和诊断结果，综合以下所有指令进行修缮（只需输出修缮后的完整文章，不要输出你的分析过程）：
{combined_instruction}"""

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一位资深高考作文辅导老师，擅长根据具体指令精修议论文。请只输出修缮后的文章正文，不要有任何开场白或结束语。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2048
        )
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(f"修缮失败: {e}")

# ====================== Streamlit UI ======================
st.title("📝 AI作文批改系统")

# ----- 侧边栏：API Key 配置 -----
with st.sidebar:
    st.header("⚙️ 配置")
    zhipu_key = st.text_input("智谱API Key", value=ZHIPU_API_KEY, type="password", help="用于OCR识别图片中的文字")
    deepseek_key = st.text_input("DeepSeek API Key", value=DEEPSEEK_API_KEY, type="password", help="用于诊断和修缮")
    
    st.markdown("---")
    st.caption("提示：API Key仅用于本次会话，不会存储。")

# ----- 主区域：左（识别+诊断）右（修缮） -----
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📄 识别与诊断")
    
    # 图片上传
    uploaded_file = st.file_uploader("上传作文照片（含题目和正文）", type=["jpg", "jpeg", "png", "bmp"])
    
    # OCR按钮
    if uploaded_file is not None:
        if st.button("🔍 识别文字（OCR）", type="primary"):
            if not zhipu_key:
                st.error("请先填写智谱API Key")
            else:
                with st.spinner("正在识别图片中的文字..."):
                    try:
                        image_bytes = uploaded_file.getvalue()
                        result = recognize_image(image_bytes, zhipu_key)
                        st.session_state["ocr_title"] = result["title"]
                        st.session_state["ocr_body"] = result["body"]
                        st.success("✅ 识别完成！请检查下方内容，如有错误可手动修改。")
                    except Exception as e:
                        st.error(f"识别失败：{e}")
    
    # 可编辑的题目和正文
    title = st.text_area("作文题目（可编辑）", value=st.session_state.get("ocr_title", ""), height=80)
    body = st.text_area("作文正文（可编辑）", value=st.session_state.get("ocr_body", ""), height=300)
    
    # 诊断按钮
    if st.button("📊 开始诊断评分", type="primary"):
        if not title.strip():
            st.error("请填写作文题目")
        elif not body.strip():
            st.error("请填写作文正文")
        elif not deepseek_key:
            st.error("请填写DeepSeek API Key")
        else:
            with st.spinner("正在诊断分析..."):
                try:
                    diagnosis_raw = diagnose_essay(title, body)
                    # 尝试解析JSON
                    try:
                        json_match = re.search(r'\{.*\}', diagnosis_raw, re.DOTALL)
                        if json_match:
                            diagnosis_dict = json.loads(json_match.group())
                        else:
                            diagnosis_dict = {"score": "解析失败", "summary": diagnosis_raw[:50]}
                    except:
                        diagnosis_dict = {"score": "格式错误", "summary": diagnosis_raw[:50]}
                    
                    st.session_state["diagnosis_raw"] = diagnosis_raw
                    st.session_state["diagnosis_dict"] = diagnosis_dict
                    st.session_state["current_title"] = title
                    st.session_state["current_body"] = body
                    st.success("✅ 诊断完成！")
                except Exception as e:
                    st.error(f"诊断失败：{e}")
    
    # 显示诊断结果
    if "diagnosis_dict" in st.session_state:
        d = st.session_state["diagnosis_dict"]
        st.subheader("📋 诊断结果")
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        with col_s1:
            st.metric("总分", f"{d.get('score', 'N/A')}/60")
        with col_s2:
            st.metric("立意", f"{d.get('detail', {}).get('立意', 'N/A')}/20")
        with col_s3:
            st.metric("结构", f"{d.get('detail', {}).get('结构', 'N/A')}/15")
        with col_s4:
            st.metric("论据", f"{d.get('detail', {}).get('论据', 'N/A')}/10")
        
        st.markdown("**✅ 优点：**")
        for item in d.get("strengths", []):
            st.markdown(f"- {item}")
        
        st.markdown("**⚠️ 不足：**")
        for item in d.get("weaknesses", []):
            st.markdown(f"- {item}")
        
        st.markdown(f"**📝 总评：** {d.get('summary', '')}")

with col_right:
    st.subheader("🔧 修缮选项")
    
    # 复选框
    option1 = st.checkbox("① 提升思维深度（深刻）")
    option2 = st.checkbox("② 优化文章结构（严谨）")
    option3 = st.checkbox("③ 精炼语言表达（流畅）")
    option4 = st.checkbox("④ 充实论据阐释（丰富）")
    
    # 全选/清空按钮
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("☑️ 全选", use_container_width=True):
            st.session_state["select_all"] = True
    with col_btn2:
        if st.button("⬜ 清空", use_container_width=True):
            st.session_state["select_all"] = False
    
    # 如果全选被触发
    if st.session_state.get("select_all", False):
        option1 = option2 = option3 = option4 = True
    
    # 修缮按钮
    if st.button("✍️ 执行修缮", type="primary", use_container_width=True):
        selected = []
        if option1: selected.append("1")
        if option2: selected.append("2")
        if option3: selected.append("3")
        if option4: selected.append("4")
        
        if not selected:
            st.warning("请至少勾选一个修缮方向")
        elif "diagnosis_raw" not in st.session_state:
            st.error("请先进行诊断评分")
        elif not deepseek_key:
            st.error("请填写DeepSeek API Key")
        else:
            with st.spinner("正在修缮文章..."):
                try:
                    revised = revise_essay(
                        st.session_state.get("current_title", ""),
                        st.session_state.get("current_body", ""),
                        st.session_state["diagnosis_raw"],
                        selected
                    )
                    st.session_state["revised_text"] = revised
                    st.success("✅ 修缮完成！")
                except Exception as e:
                    st.error(f"修缮失败：{e}")
    
    # 显示修缮稿
    st.subheader("📝 修缮稿")
    if "revised_text" in st.session_state:
        st.text_area("修缮后的文章", value=st.session_state["revised_text"], height=400)
        
        # 下载按钮
        st.download_button(
            label="⬇️ 下载修缮稿",
            data=st.session_state["revised_text"],
            file_name="修缮稿.txt",
            mime="text/plain",
            use_container_width=True
        )

st.markdown("---")
st.caption("💡 使用说明：上传包含作文题目和正文的照片 → 点击「识别文字」→ 检查并修改识别内容 → 点击「开始诊断评分」→ 勾选修缮方向 → 点击「执行修缮」")
