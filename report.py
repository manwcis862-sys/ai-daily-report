#!/usr/bin/env python3
"""
AI行业日报 v4 - 多源搜索 + 严格去重
覆盖：Bing News / Google News / 今日头条 / Reddit / YouTube / X(Nitter)
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
TO_EMAIL   = os.environ.get("TO_EMAIL", SMTP_USER)

CST  = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime("%Y-%m-%d")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AI-ReportBot/1.0)"}

# ========== 工具函数 ==========
def clean(txt):
    txt = re.sub(r'<[^>]+>', '', txt or '')
    txt = html.unescape(txt)
    return txt.strip()[:200]

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

# ========== 搜索：Bing News ==========
def bing_news(query, n=6):
    results = []
    tree = fetch_xml(f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss")
    if tree is None:
        return results
    for item in tree.findall('.//item')[:n]:
        t = item.findtext('title','').strip()
        if t:
            results.append({"title": t, "snippet": clean(item.findtext('description','')), "src": "Bing"})
    return results

# ========== 搜索：今日头条 ==========
def toutiao(query, n=6):
    results = []
    data = fetch_json(f"https://www.toutiao.com/api/search/?keyword={quote_plus(query)}&pd=synthesis&offset=0&count={n}")
    if data and 'data' in data:
        for item in data['data'][:n]:
            t = item.get('title','')
            if t:
                results.append({"title": t, "snippet": clean(item.get('abstract','')), "src": "今日头条"})
    return results

# ========== 搜索：Reddit ==========
def reddit(query, n=5):
    results = []
    data = fetch_json(f"https://www.reddit.com/search.json?q={quote_plus(query)}&sort=top&t=day&limit={n}")
    if data and 'data' in data:
        for item in data['data'].get('children', [])[:n]:
            p = item.get('data', {})
            t = p.get('title','')
            if t:
                results.append({"title": t, "snippet": clean(p.get('selftext','') or p.get('url','')), "src": "Reddit"})
    return results

# ========== 搜索：YouTube ==========
def youtube(query, n=5):
    results = []
    tree = fetch_xml(f"https://www.youtube.com/feeds/videos.xml?search_query={quote_plus(query)}")
    if tree is None:
        return results
    ns = 'http://www.youtube.com/xml/schemas/2015'
    for item in tree.findall('.//entry')[:n]:
        title = item.findtext(f'{{{ns}}}videoid', '') or item.findtext('title','')
        author = item.findtext('author/name','').strip()
        raw_title = item.findtext('title','').strip()
        if raw_title:
            results.append({"title": f"[视频] {raw_title}", "snippet": f"UP主: {author}", "src": "YouTube"})
    return results

# ========== 搜索：X / Nitter ==========
NITTERS = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.privacytools.io",
]
def x_twitter(query, n=5):
    results = []
    for base in NITTERS:
        url = f"{base}/search/rss?f=tweets&q={quote_plus(query)}"
        tree = fetch_xml(url)
        if tree is None:
            continue
        for item in tree.findall('.//item')[:n]:
            t = item.findtext('title','').strip()
            if t:
                t = re.sub(r'^RT @\w+:\s*', '', t)
                results.append({"title": t, "snippet": clean(item.findtext('description','')), "src": "X"})
        if results:
            return results
    return results

# ========== 搜索：Google News ==========
def google_news(query, n=6):
    results = []
    tree = fetch_xml(f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")
    if tree is None:
        return results
    for item in tree.findall('.//item')[:n]:
        t = item.findtext('title','').strip()
        if t:
            results.append({"title": t, "snippet": clean(item.findtext('description','')), "src": "Google"})
    return results

# ========== 综合搜索 ==========
def search_all(query, n=5):
    sources = [
        ("Bing",     bing_news),
        ("Google",   google_news),
        ("今日头条", toutiao),
        ("Reddit",   reddit),
        ("YouTube",  youtube),
        ("X",        x_twitter),
    ]
    all_src = []
    for name, fn in sources:
        r = fn(query, n)
        if r:
            print(f"  [{name}] {len(r)} 条")
            all_src.extend(r)
        time.sleep(0.5)
    return all_src

# ========== 严格去重 ==========
def title_fp(title):
    """标题指纹：去除所有空格/标点/数字/开头语气词，统一小写"""
    t = re.sub(r'^[\s\d\.\,\-\—\(\)]+', '', title.strip())
    t = re.sub(r'[\s\.\,\-\—_\(\)\（\)\[\]\【\】""''、，。；：抖音油管]+', '', t)
    t = re.sub(r'^(重磅|突发|刚刚|爆料|炸裂|震惊|消息|新闻|快讯|日报|快报|热文|曝光)+', '', t, flags=re.IGNORECASE)
    return t.lower()

def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def deduplicate(items):
    """严格去重：指纹相同 或 前15字相同 或 Jaccard>0.6 → 只留一条"""
    unique = []
    for it in items:
        title = it['title'].strip()
        if not title:
            continue
        fp = title_fp(title)
        keep = True
        for ex in unique:
            efp = title_fp(ex['title'])
            if fp == efp:
                keep = False
                break
            if fp[:15] and efp[:15] and fp[:15] == efp[:15]:
                keep = False
                break
            if jaccard(fp, efp) > 0.6:
                keep = False
                break
        if keep:
            unique.append(it)
    return unique

# ========== 生成报告 ==========
def generate_report(items):
    items = deduplicate(items)
    print(f"\n去重后: {len(items)} 条")

    cats = {
        "OpenAI / ChatGPT":    [],
        "Google / Gemini":     [],
        "Anthropic / Claude":  [],
        "国内大模型":          [],
        "开源生态":            [],
        "社交媒体热点":        [],
        "行业动态":            [],
    }
    rules = [
        ("OpenAI / ChatGPT",   ["OpenAI","ChatGPT","GPT-","GPT5","GPT4","Codex","Sora","o1 ","o3 ","o4 ","Operator","ChatGPT 5"]),
        ("Google / Gemini",    ["Google","Gemini","TPU","DeepMind","Bard","Workspace"]),
        ("Anthropic / Claude",["Claude","Anthropic"]),
        ("国内大模型",         ["腾讯","阿里","百度","Kimi","月之暗面","智谱","混元","千问","Qwen","MiniMax","百灵","火山","通义","文心","豆包","DeepSeek"]),
        ("开源生态",           ["Llama","llama","Hugging Face","GitHub Trending","开源模型","开源大模型"]),
        ("社交媒体热点",       ["Reddit","X ","Twitter","[视频]"]),  # [视频] 标记 YouTube
    ]
    for it in items:
        t = it['title'] + it['snippet']
        matched = False
        for cat, kws in rules:
            if any(k in t for k in kws):
                cats[cat].append(it)
                matched = True
                break
        if not matched:
            cats["行业动态"].append(it)

    lines = [f"AI日报｜{TODAY}", "", f"共收录 {len(items)} 条（去重后）", ""]
    for cat, its in cats.items():
        if not its:
            continue
        lines.append(f"【{cat}】（{len(its)} 条）")
        for i, it in enumerate(its[:8], 1):
            lines.append(f"  {i}. {it['title']}")
            if it['snippet']:
                lines.append(f"     {it['snippet']}  [{it.get('src','')}]")
        lines.append("")
    lines.append(f"生成时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M')}")
    lines.append("数据源：Bing/Google新闻 / 今日头条 / Reddit / YouTube / X(Nitter)")
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
    mode = os.environ.get("REPORT_MODE", "evening").lower()
    print(f"=== AI Daily Report v4 === | {mode} | {TODAY}")

    queries = [
        # OpenAI / ChatGPT 重点查询
        "ChatGPT 5.5 OR OpenAI 最新动态 2026",
        "OpenAI GPT-5 发布 2026",
        "AI 人工智能 最新进展 2026",
        # 国际大模型
        "Google Gemini Claude AI 动态 2026",
        # 国内
        "腾讯混元 Kimi 阿里千问 百度文心 智谱AI 2026",
        "DeepSeek Qwen2.5 开源大模型 最新 2026",
        # 社交媒体
        "AI Reddit trending 2026",
        "AI YouTube 最新 2026",
        "AI X Twitter Elon Musk 2026",
        # 今日头条
        "人工智能 大模型 最新消息",
    ]

    all_items = []
    for q in queries:
        print(f"Query: {q}")
        items = search_all(q, n=5)
        all_items.extend(items)
        time.sleep(1)

    print(f"\n原始收录: {len(all_items)} 条")
    body = generate_report(all_items) if all_items else f"AI日报｜{TODAY}\n\n今日未获取到数据。"

    subject = f"AI早报｜{TODAY}" if mode == "morning" else f"AI晚报｜{TODAY}"
    ok = send_email(subject, body)

    fname = f"ai-report-{TODAY}.txt"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"Report -> {fname}")

    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
