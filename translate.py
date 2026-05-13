#!/usr/bin/env python3
"""
translate.py — 用 Gemini Flash 把 avalla_hints.json 里的意大利文 hint 全部翻译成中文。

用法:
  1. 把 GEMINI_API_KEY 设为环境变量，或者直接改下面第 18 行
  2. 把 avalla_hints.json 放在同目录
  3. python3 translate.py
  4. 完成后会生成 hints_zh.json （断点续传，挂了重跑就行）

依赖: requests  (pip install requests --break-system-packages)
"""

import json, os, re, sys, time

# ─── 配置 ────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
INP  = os.path.join(ROOT, 'avalla_hints.json')
OUT  = os.path.join(ROOT, 'hints_zh.json')

API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
if not API_KEY:
    API_KEY = ''  # ← 没设环境变量的话直接填进引号里

MODEL = 'gemini-2.5-flash'  # 免费 1500/天，够用
SLEEP_BETWEEN = 0.6  # 秒，避免触发 15 RPM 限流
SAVE_EVERY = 10      # 每翻译 10 条保存一次

if not API_KEY:
    print("❌ 没设 API key。请设置环境变量 GEMINI_API_KEY 或编辑第 18 行")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("缺 requests 库，运行: pip install requests --break-system-packages")
    sys.exit(1)

# ─── Prompt ──────────────────────────────────────────
SYS_PROMPT = """你是意大利驾照 Patente B 资深教师，正在把意大利官方驾考解析翻译给中国学生看。

输入是意大利语的解析文本（针对某个驾考主题），输出是简洁清晰的中文翻译。

要求：
1. 准确翻译事实和数字（限速 km/h、距离 m、罚款 €、年龄、吨位等绝对要正确）
2. 保留原文里 "Non è vero che..." 这种"破陷阱"句子，翻译成「⚠️ 陷阱：题目说"XXX"是错的，因为...」
3. 意大利语法规专用词括号保留原文：例「停车（sosta）」「让行（precedenza）」「义务（obbligo）」
4. 风格简洁，不要套客套话「这道题考察」「让我来解释」
5. 适当分段，可用「• 」做小列表
6. 字数：原文短的翻译也短，原文长的翻译也长但不要冗余
7. 直接输出中文翻译，不要任何前缀如「翻译：」「以下是中文：」"""

def clean_html(s):
    if not s: return ''
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('\\n', '\n')
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def translate_one(title, italian_text, retry=2):
    user_msg = f"主题：{title}\n\n意大利文解析：\n{italian_text}\n\n请翻译成中文（按上述要求）。"
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}'
    body = {
        'system_instruction': {'parts': [{'text': SYS_PROMPT}]},
        'contents': [{'role': 'user', 'parts': [{'text': user_msg}]}],
        'generationConfig': {'maxOutputTokens': 1500, 'temperature': 0.3},
    }
    for attempt in range(retry+1):
        try:
            r = requests.post(url, json=body, timeout=60)
            if r.status_code == 429:
                print(f"   ⏳ 429 限流，等 30 秒...")
                time.sleep(30)
                continue
            if r.status_code >= 500:
                print(f"   🌊 {r.status_code} 服务器忙，等 5 秒重试...")
                time.sleep(5)
                continue
            if not r.ok:
                print(f"   ❌ HTTP {r.status_code}: {r.text[:200]}")
                return None
            d = r.json()
            t = d.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            return t.strip()
        except Exception as e:
            print(f"   ⚠️ 异常: {e}")
            time.sleep(3)
    return None

# ─── 主流程 ──────────────────────────────────────────
def main():
    if not os.path.exists(INP):
        print(f"❌ 缺文件: {INP}")
        print(f"   去 https://github.com/avalla/quiz-patente-ab/blob/main/src/services/hints.json 下载并改名为 avalla_hints.json")
        sys.exit(1)

    with open(INP, 'r', encoding='utf-8') as f:
        raw_hints = json.load(f)
    hints = [h for h in raw_hints if 'id' in h]
    print(f"加载到 {len(hints)} 个 hint")

    # 断点续传
    if os.path.exists(OUT):
        with open(OUT, 'r', encoding='utf-8') as f:
            zh = json.load(f)
        print(f"已有 {len(zh)} 条翻译（继续未完成的）")
    else:
        zh = {}

    todo = [h for h in hints if str(h['id']) not in zh]
    print(f"待翻译: {len(todo)} 条\n")

    for i, h in enumerate(todo, 1):
        hid = str(h['id'])
        title = h.get('title', '').strip()
        italian = clean_html(h.get('description', ''))
        if not italian:
            print(f"[{i}/{len(todo)}] id={hid} ({title}) — 跳过(无内容)")
            zh[hid] = {'title': title, 'text': ''}
            continue

        print(f"[{i}/{len(todo)}] id={hid} ({title}) — {len(italian)} 字...", end=' ', flush=True)
        result = translate_one(title, italian)

        if result:
            zh[hid] = {'title': title, 'text': result}
            print(f"✓ {len(result)} 字")
        else:
            print(f"✗ 失败，跳过")
            zh[hid] = {'title': title, 'text': italian, 'lang': 'it', 'translate_failed': True}

        # 周期性保存
        if i % SAVE_EVERY == 0:
            with open(OUT, 'w', encoding='utf-8') as f:
                json.dump(zh, f, ensure_ascii=False, indent=2)
            print(f"   💾 保存进度 ({len(zh)} 条)")

        time.sleep(SLEEP_BETWEEN)

    # 最终保存
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(zh, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成！共翻译 {len(zh)} 条 → {OUT}")
    print(f"   下一步：python3 build_explanations.py")

if __name__ == '__main__':
    main()
