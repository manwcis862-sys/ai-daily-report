#!/usr/bin/env python3
"""
AI行业日报 v6 - 两步流程：抓取 → Claude API 二次精编
第一步：多源抓取 + 基础去重
第二步：Claude 作为编辑，筛选/分类/撰写摘要，输出精炼日报
"""

import os, sys, smtplib, json, time, re, html
import xml.etree.ElementTree as ET
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.parse import quote_plus

# ========== 配置 ==========
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = os.environ.get("SMTP_EMAIL", "victory3690@qq.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = SMTP_USER
TO_EMAIL  = os.environ.get("TO_EMAIL", SMTP_USER)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

CST   = timezone(timedelta(hours=8))
NOW   = datetime.now(CST)
TODAY = NOW.strftime("%Y-%m-%d")

# 北京时间判断早/晚报（早报：6:00–13:59，晚报：14:00–23:59）
def detect_mode():
    env_mode = os.environ.get("REPORT_MODE", "").lower()
    if env_mode in ("morning", "evening"):
        return env_mode
    hour = NOW.hour
    return "morning" if hour < 14 else "evening"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AI-ReportBot/1.0)"}

# ========== 工具函数 ==========
def clean(txt):
    txt = re.sub(r'<[^>]+>', '', txt or '')
    txt = html.unescape(txt)
    return txt.strip()[:300]

def fetch_xml(url, timeout=15):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as r:
            return ET.fromstring(r.read())
    except Exception as e:
        print(f"  [XML] {e}", file=sys.stderr)
        return None

def fetch_json(url, timeout=15):
    try:
        req = Request(url, headers={**HEADERS, "Accept": "application/json"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [JSON] {e}", file=sys.stderr)
        return None

# ========== 各源抓取（带 pubDate） ==========
def parse_pub_date(raw):
    """尝试解析 RSS pubDate，返回格式化字符串，失败返回空串"""
    if not raw:
        return ""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            dt_cst = dt.astimezone(CST)
            return dt_cst.strftime("%m-%d %H:%M")
        except Exception:
            pass
    return raw.strip()[:16]

def bing_news(query, n=6):
    results = []
    tree = fetch_xml(f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss")
    if tree is None:
        return results
    for item in tree.findall('.//item')[:n]:
        t = item.findtext('title', '').strip()
        if t:
            results.append({
                "title":   t,
                "snippet": clean(item.findtext('description', '')),
                "src":     "Bing新闻",
                "pub":     parse_pub_date(item.findtext('pubDate', '')),
                "link":    item.findtext('link', ''),
            })
    return results

def google_news(query, n=6):
    results = []
    tree = fetch_xml(f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")
    if tree is None:
        return results
    for item in tree.findall('.//item')[:n]:
        t = item.findtext('title', '').strip()
        if t:
            # Google News 标题格式：新闻标题 - 来源名
            parts = t.rsplit(' - ', 1)
            title = parts[0].strip()
            media = parts[1].strip() if len(parts) > 1 else "Google新闻"
            results.append({
                "title":   title,
                "snippet": clean(item.findtext('description', '')),
                "src":     media,
                "pub":     parse_pub_date(item.findtext('pubDate', '')),
                "link":    item.findtext('link', ''),
            })
    return results

def reddit(query, n=5):
    results = []
    data = fetch_json(f"https://www.reddit.com/search.json?q={quote_plus(query)}&sort=top&t=day&limit={n}")
    if data and 'data' in data:
        for item in data['data'].get('children', [])[:n]:
            p = item.get('data', {})
            t = p.get('title', '')
            if t:
                results.append({
                    "title":   t,
                    "snippet": clean(p.get('selftext', '') or p.get('url', '')),
                    "src":     f"Reddit r/{p.get('subreddit', '')}",
                    "pub":     "",
                    "link":    f"https://reddit.com{p.get('permalink', '')}",
                })
    return results

def youtube(query, n=3):
    """YouTube 视频只抓少量，标注为视频内容"""
    results = []
    tree = fetch_xml(f"https://www.youtube.com/feeds/videos.xml?search_query={quote_plus(query)}")
    if tree is None:
        return results
    for entry in tree.findall('.//{http://www.w3.org/2005/Atom}entry')[:n]:
        raw_title = (entry.findtext('{http://www.w3.org/2005/Atom}title') or '').strip()
        author    = (entry.findtext('.//{http://www.w3.org/2005/Atom}name') or '').strip()
        published = (entry.findtext('{http://www.w3.org/2005/Atom}published') or '')[:16]
        vid_id    = (entry.findtext('{http://www.youtube.com/xml/schemas/2015}videoId') or '')
        if raw_title:
            results.append({
                "title":   f"[视频] {raw_title}",
                "snippet": f"频道: {author}",
                "src":     "YouTube",
                "pub":     published,
                "link":    f"https://youtube.com/watch?v={vid_id}" if vid_id else "",
            })
    return results

NITTERS = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.privacytools.io",
]
def x_twitter(query, n=5):
    results = []
    for base in NITTERS:
        url  = f"{base}/search/rss?f=tweets&q={quote_plus(query)}"
        tree = fetch_xml(url)
        if tree is None:
            continue
        for item in tree.findall('.//item')[:n]:
            t = item.findtext('title', '').strip()
            if t:
                t = re.sub(r'^RT @\w+:\s*', '', t)
                results.append({
                    "title":   t,
                    "snippet": clean(item.findtext('description', '')),
                    "src":     "X/Twitter",
                    "pub":     parse_pub_date(item.findtext('pubDate', '')),
                    "link":    item.findtext('link', ''),
                })
        if results:
            return results
    return results

# ========== 综合搜索 ==========
def search_all(query, n=6):
    sources = [
        ("Bing",    bing_news),
        ("Google",  google_news),
        ("Reddit",  reddit),
        ("YouTube", youtube),
        ("X",       x_twitter),
    ]
    all_src = []
    for name, fn in sources:
        r = fn(query, n)
        if r:
            print(f"  [{name}] {len(r)} 条", file=sys.stderr)
            all_src.extend(r)
        time.sleep(0.4)
    return all_src

# ========== 去重 ==========
def title_fp(title):
    t = re.sub(r'^[\s\d\.\,\-\—\(\)]+', '', title.strip())
    t = re.sub(r'[\s\.\,\-\—_\(\)\（\)\[\]\【\】""''、，。；：]+', '', t)
    t = re.sub(r'^(重磅|突发|刚刚|爆料|炸裂|震惊|消息|新闻|快讯|日报|快报|热文|曝光)+', '', t, flags=re.IGNORECASE)
    return t.lower()

def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def deduplicate(items):
    unique = []
    for it in items:
        title = it['title'].strip()
        if not title:
            continue
        fp   = title_fp(title)
        keep = True
        for ex in unique:
            efp = title_fp(ex['title'])
            if fp == efp:
                keep = False; break
            if fp[:15] and efp[:15] and fp[:15] == efp[:15]:
                keep = False; break
            if jaccard(fp, efp) > 0.6:
                keep = False; break
        if keep:
            unique.append(it)
    return unique

# ========== Claude API 二次精编 ==========
EDIT_PROMPT = """\
你是一名专业的 AI 行业情报编辑，不是新闻抓取机器人。

你的任务：基于下面提供的原始新闻列表，进行筛选、分类、重要性排序，输出一份精炼的中文 AI 日报。

【筛选规则】
最高优先级（必须保留）：
- OpenAI / GPT / ChatGPT / Sora / Codex 的实质进展
- Google / Gemini / DeepMind 的实质进展
- Anthropic / Claude / Claude Code 的实质进展
- 国内大模型：DeepSeek、Qwen、Kimi、GLM、文心、混元、豆包、MiniMax、讯飞星火等
- 开源模型：Llama、Mistral、GitHub 热门 AI 项目、推理框架、Agent、RAG 工具

次级关注（选择性保留）：
- AI 融资、并购、政策、监管
- 重要论文或 benchmark
- AI 硬件、AI 生产力工具

直接剔除：
- "ChatGPT 是什么""AI 是什么"这类科普百科文章
- 与当天无关的旧闻
- 标题党、营销软文、无实质信息的直播通知
- 同一事件的重复报道只保留一条
- 与重点模型无强相关的泛 AI 趋势文章
- YouTube/视频内容，除非视频本身是重大发布或评测

【分类规则】
严格按新闻主体归类，不能因关键词误分：
- 重点新闻：OpenAI、Gemini、Claude 的重大进展，或跨公司影响整个行业的大事件
- 国内大模型：中国大模型公司的实质进展
- 开源与开发者生态：开源模型、GitHub、AI coding 工具、Agent 框架
- 行业动态：融资、政策、商业化、AI 应用公司

【输出格式】严格按下面结构输出，不要输出其他内容：

# AI{MODE}｜{DATE}

共筛选 X 条重点新闻

---

## 今日核心摘要

2–3 句话总结今天 AI 行业最重要的变化。

---

## 重点新闻

1. **[标签] 标题：一句话说明核心事件**
   补充 1–2 句，说明发生了什么以及为什么重要。
   来源：来源名｜时间

（如无内容可省略此栏目）

---

## 国内大模型

1. **[标签] 标题**
   补充 1 句说明。
   来源：来源名｜时间

（如无内容可省略此栏目）

---

## 开源与开发者生态

1. **[标签] 标题**
   补充 1 句说明。
   来源：来源名｜时间

（如无内容可省略此栏目）

---

## 行业动态

1. **[标签] 标题**
   补充 1 句说明。
   来源：来源名｜时间

（如无内容可省略此栏目）

---

## 简讯

- **[标签] 标题**：一句话说明。

---

## 今日最重要的 3 条

1. **事件**：一句话说明为什么重要。
2. **事件**：一句话说明为什么重要。
3. **事件**：一句话说明为什么重要。

---

## 一句话总览

一句话总结今天 AI 行业的核心变化。

---

## 已过滤内容

简单说明已过滤的内容类型。

【重要要求】
- 标题必须加粗，不能只复制原标题，要重新概括核心
- 每条补充说明不超过 2 句，说明具体变化和影响
- 正文控制在 8–15 条，宁缺毋滥
- 中文输出，专业克制，不用夸张营销口吻
- 标题格式：**[标签] 重新概括的标题**

以下是原始新闻数据（JSON格式，每条包含 title/snippet/src/pub 字段）：
"""

def claude_edit(raw_items, mode):
    """调用 Claude API 对原始新闻做二次精编"""
    if not ANTHROPIC_API_KEY:
        print("[WARN] ANTHROPIC_API_KEY not set, skipping AI edit", file=sys.stderr)
        return None

    try:
        import urllib.request, urllib.error
        mode_label = "早报" if mode == "morning" else "晚报"
        prompt_data = json.dumps(raw_items, ensure_ascii=False, indent=2)
        full_prompt = (
            EDIT_PROMPT
            .replace("{MODE}", mode_label)
            .replace("{DATE}", TODAY)
            + prompt_data
        )

        payload = json.dumps({
            "model": "claude-opus-4-6",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": full_prompt}]
        }).encode("utf-8")

        req = Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            method="POST",
        )
        with urlopen(req, timeout=120) as r:
            resp = json.loads(r.read().decode())
            return resp["content"][0]["text"]

    except Exception as e:
        print(f"[ERROR] Claude API: {e}", file=sys.stderr)
        return None

# ========== 降级：无 API 时的纯文本格式化 ==========
def fallback_report(items, mode):
    mode_label = "早报" if mode == "morning" else "晚报"
    cats = {
        "OpenAI / ChatGPT":   [],
        "Google / Gemini":    [],
        "Anthropic / Claude": [],
        "国内大模型":         [],
        "开源生态":           [],
        "行业动态":           [],
    }
    rules = [
        ("OpenAI / ChatGPT",   ["OpenAI","ChatGPT","GPT-","GPT5","GPT4","Codex","Sora","o1 ","o3 ","o4 "]),
        ("Google / Gemini",    ["Google","Gemini","DeepMind","Bard"]),
        ("Anthropic / Claude", ["Claude","Anthropic"]),
        ("国内大模型",         ["腾讯","阿里","百度","Kimi","月之暗面","智谱","混元","千问","Qwen","MiniMax","文心","豆包","DeepSeek","讯飞"]),
        ("开源生态",           ["Llama","Hugging Face","GitHub","开源模型","Mistral"]),
    ]
    for it in items:
        t = it['title'] + it['snippet']
        matched = False
        for cat, kws in rules:
            if any(k in t for k in kws):
                cats[cat].append(it); matched = True; break
        if not matched:
            cats["行业动态"].append(it)

    lines = [
        f"# AI{mode_label}｜{TODAY}",
        "",
        f"共收录 {len(items)} 条（去重后，未经 AI 精编）",
        "",
        "---",
        "",
    ]
    for cat, its in cats.items():
        if not its:
            continue
        lines.append(f"## {cat}")
        lines.append("")
        for i, it in enumerate(its[:8], 1):
            title   = re.sub(r'^\[视频\]\s*', '', it['title'].strip())
            snippet = it.get('snippet', '').strip()
            src     = it.get('src', '')
            pub     = it.get('pub', '')
            src_str = f"{src}｜{pub}" if pub else src
            lines.append(f"{i}. **{title}**")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append(f"   来源：{src_str}")
            lines.append("")
    lines.append(f"生成时间：{NOW.strftime('%Y-%m-%d %H:%M')} (CST)")
    lines.append("注：ANTHROPIC_API_KEY 未配置，已跳过 AI 精编。")
    return "\n".join(lines)

# ========== 邮件发送 ==========
def send_email(subject, body):
    if not SMTP_PASS:
        print("ERROR: SMTP_PASS not set!", file=sys.stderr)
        return False
    msg = MIMEMultipart()
    msg["From"]    = SMTP_FROM
    msg["To"]      = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_FROM, [TO_EMAIL], msg.as_string())
        s.quit()
        print(f"[OK] Email sent -> {TO_EMAIL}")
        return True
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return False

# ========== 主流程 ==========
def main():
    mode = detect_mode()
    print(f"=== AI Daily Report v6 === | mode={mode} | {TODAY} | CST hour={NOW.hour}", file=sys.stderr)

    queries = [
        "OpenAI GPT-5 ChatGPT 最新动态 2026",
        "Google Gemini AI 最新进展 2026",
        "Anthropic Claude AI 2026",
        "DeepSeek Qwen Kimi 国内大模型 最新 2026",
        "腾讯混元 百度文心 阿里千问 2026",
        "开源大模型 Llama GitHub AI Agent 2026",
        "AI 融资 并购 政策 2026",
        "AI Reddit trending 2026",
        "AI breakthrough research 2026",
    ]

    all_items = []
    for q in queries:
        print(f"Query: {q}", file=sys.stderr)
        items = search_all(q, n=5)
        all_items.extend(items)
        time.sleep(0.3)

    print(f"\n原始收录: {len(all_items)} 条", file=sys.stderr)
    all_items = deduplicate(all_items)
    print(f"去重后: {len(all_items)} 条", file=sys.stderr)

    # 限制传给 Claude 的条数，节省 token
    raw_for_claude = [
        {"title": it["title"], "snippet": it["snippet"], "src": it["src"], "pub": it["pub"]}
        for it in all_items[:80]
    ]

    print("调用 Claude API 精编...", file=sys.stderr)
    body = claude_edit(raw_for_claude, mode)

    if not body:
        print("Claude API 失败，使用降级报告", file=sys.stderr)
        body = fallback_report(all_items, mode)

    # 追加生成时间戳
    body += f"\n\n---\n生成时间：{NOW.strftime('%Y-%m-%d %H:%M')} (北京时间)\n由 GitHub Actions 自动运行，每天 09:00 / 19:00 北京时间推送"

    mode_label = "早报" if mode == "morning" else "晚报"
    subject = f"AI{mode_label}｜{TODAY}"
    ok = send_email(subject, body)

    fname = f"ai-report-{TODAY}-{mode}.txt"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"Report -> {fname}", file=sys.stderr)

    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
