#!/usr/bin/env python3
"""
build_explanations.py — 把 Italian hints + Chinese translations + Ed0ardo question dataset
组合成一个 explanations.json 供 app 加载。

输入:
  - avalla_questions.json   (avalla 仓库 src/services/questions.json)
  - avalla_hints.json       (avalla 仓库 src/services/hints.json)
  - hints_zh.json           (中文翻译，由 translate.py 生成；格式: {"<theory_id>": {"title":..., "text":...}, ...})
  - ed_questions.json       (Ed0ardo 仓库 quizPatenteB2023.json)

输出:
  - explanations.json
"""
import json, re, sys, os
from collections import defaultdict

# ─── 配置 ────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
AVALLA_Q = os.path.join(ROOT, 'avalla_questions.json')
AVALLA_H = os.path.join(ROOT, 'avalla_hints.json')
HINTS_ZH = os.path.join(ROOT, 'hints_zh.json')
ED_Q     = os.path.join(ROOT, 'ed_questions.json')
OUT      = os.path.join(ROOT, 'explanations.json')

# ─── 题目文本标准化 ──────────────────────────────────
def normalize_q(s):
    """与 app 端 JS 的 qhash 输入保持一致。"""
    s = (s or '').lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def qhash(s):
    """djb2-like 32-bit hash, base36. 必须与 app 端 JS 完全一致。"""
    n = normalize_q(s)
    h = 5381
    for c in n:
        h = ((h * 33) ^ ord(c)) & 0xFFFFFFFF
    if h == 0: return '0'
    digits = '0123456789abcdefghijklmnopqrstuvwxyz'
    out = []
    x = h
    while x:
        out.append(digits[x % 36])
        x //= 36
    return ''.join(reversed(out))

# ─── 加载数据 ────────────────────────────────────────
def load(path):
    if not os.path.exists(path):
        print(f"❌ 缺文件: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def flatten_ed(d, out=None):
    if out is None: out = []
    for k, v in d.items():
        if isinstance(v, dict):
            flatten_ed(v, out)
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, dict) and 'q' in it:
                    out.append(it)
    return out

# ─── 主流程 ──────────────────────────────────────────
def main():
    print("加载 avalla 题库 ...")
    av_questions = load(AVALLA_Q)
    print(f"  {len(av_questions)} 题")

    print("加载 avalla hints ...")
    av_hints_raw = load(AVALLA_H)
    av_hints = {h['id']: h for h in av_hints_raw if 'id' in h}
    print(f"  {len(av_hints)} 个 hint")

    print("加载中文翻译 ...")
    if os.path.exists(HINTS_ZH):
        zh_hints = load(HINTS_ZH)
        print(f"  {len(zh_hints)} 个 hint 有中文")
    else:
        zh_hints = {}
        print(f"  ⚠️ {HINTS_ZH} 不存在，输出文件不会有中文")

    print("加载 Ed0ardo 题库 ...")
    ed_data = load(ED_Q)
    ed_qs = flatten_ed(ed_data)
    print(f"  {len(ed_qs)} 题（展平后）")

    # 构造 avalla 题目索引（按标准化文本）
    av_idx = {normalize_q(q['question']): q for q in av_questions}
    print(f"  avalla 唯一标准化文本: {len(av_idx)}")

    # 对每道 Ed0ardo 题，找对应的 hint id
    qmap = {}  # qhash → theory_id
    matched = 0
    fuzzy_matched = 0
    no_match = 0
    for eq in ed_qs:
        qh = qhash(eq['q'])
        av_q = av_idx.get(normalize_q(eq['q']))
        if av_q:
            t = av_q.get('theory')
            if t and t in av_hints:
                qmap[qh] = t
                matched += 1
                continue
        # 模糊匹配：尝试取题目前 50 个字符作为前缀
        prefix = normalize_q(eq['q'])[:50]
        for k, v in av_idx.items():
            if k.startswith(prefix) and len(k) >= len(prefix):
                t = v.get('theory')
                if t and t in av_hints:
                    qmap[qh] = t
                    fuzzy_matched += 1
                    break
        else:
            no_match += 1

    print(f"\n匹配结果:")
    print(f"  精确匹配: {matched}")
    print(f"  模糊匹配: {fuzzy_matched}")
    print(f"  未匹配: {no_match}  (这些题会走实时 AI 兜底)")
    print(f"  总覆盖: {matched + fuzzy_matched} / {len(ed_qs)} ({100*(matched+fuzzy_matched)/len(ed_qs):.1f}%)")

    # 构造最终 hints 字典：优先用中文，没有就放意大利原文（这样翻译时可以增量）
    hints_final = {}
    used_theory_ids = set(qmap.values())
    for tid in used_theory_ids:
        h = av_hints.get(tid)
        if not h: continue
        zh = zh_hints.get(str(tid)) or zh_hints.get(tid)
        if zh:
            hints_final[str(tid)] = zh
        else:
            # 还没翻译的，先放原文，标记 it
            hints_final[str(tid)] = {
                'title': h.get('title', ''),
                'text': re.sub(r'<[^>]+>', '', h.get('description', '')).replace('\\n', '\n').strip(),
                'lang': 'it',  # 标记是意大利原文
            }

    zh_count = sum(1 for v in hints_final.values() if v.get('lang') != 'it')
    print(f"\n输出 hint:")
    print(f"  总数: {len(hints_final)}")
    print(f"  已翻译中文: {zh_count}")
    print(f"  仍是意大利文: {len(hints_final) - zh_count}")

    out = {
        'version': 1,
        'generated_by': 'build_explanations.py',
        'stats': {
            'total_questions': len(ed_qs),
            'matched': matched + fuzzy_matched,
            'unmatched': no_match,
            'total_hints': len(hints_final),
            'translated_hints': zh_count,
        },
        'hints': hints_final,
        'qmap': qmap,  # qhash → theory_id
    }

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    size = os.path.getsize(OUT)
    print(f"\n✅ 写入 {OUT}  ({size:,} 字节 = {size/1024:.0f} KB)")

if __name__ == '__main__':
    main()
