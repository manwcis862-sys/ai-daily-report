#!/usr/bin/env python3
"""
AI行业日报 v6 - 多源聚合 + 严格去重
来源：Google News / Bing News / Reddit / YouTube(频道RSS) / X(Nitter) / 科技RSS
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

CST   = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime("%Y-%m-%d")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ========== 工具函数 ==========
def clean(txt):
    txt = re.sub(r'<[^>]+>', '', txt or '')
    txt = html.unescape(txt)
    return txt.strip()[:200]

def fetch_xml(url, timeout=20, extra_headers=None):
    try:
        h = {**HEADERS, **(extra_headers or {})}
        req = Request(url, headers=h)
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
        # 处理 BOM / 非标准编码
        raw = raw.lstrip(b'\xef\xbb\xbf')
        return ET.fromstring(raw)
    except Exception as e:
        print(f"  [XML] {url[:60]}... {e}", file=sys.stderr)
        return None

def fetch_json(url, timeout=20, extra_headers=None):
    try:
        h = {**HEADERS, "Accept": "application/json", **(extra_headers or {})}
        req = Request(url, headers=h)
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [JSON] {url[:60]}... {e}", file=sys.stderr)
        return None

# ========== 1. Google News RSS ==========
def google_news(query, n=8):
    results = []
    url = (f"https://news.google.com/rss/search"
           f"?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")
    tree = fetch_xml(url)
    if tree is None:
        return results
    for item in tree.findall('.//item')[:n]:
        t = item.findtext('title', '').strip()
        if t:
            results.append({
                "title": t,
                "snippet": clean(item.findtext('description', '')),
                "src": "Google新闻"
            })
    return results

# ========== 2. Bing News RSS ==========
def bing_news(query, n=6):
    results = []
    url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss"
    tree = fetch_xml(url)
    if tree is None:
        return results
    for item in tree.findall('.//item')[:n]:
        t = item.findtext('title', '').strip()
        if t:
            results.append({
                "title": t,
                "snippet": clean(item.findtext('description', '')),
                "src": "Bing新闻"
            })
    return results

# ========== 3. Reddit JSON ==========
def reddit(query, n=6):
    results = []
    url = (f"https://www.reddit.com/search.json"
           f"?q={quote_plus(query)}&sort=top&t=day&limit={n}")
    data = fetch_json(url, extra_headers={"Accept": "application/json"})
    if data and 'data' in data:
        for item in data['data'].get('children', [])[:n]:
            p = item.get('data', {})
            t = p.get('title', '').strip()
            if t:
                results.append({
                    "title": t,
                    "snippet": clean(p.get('selftext', '') or p.get('url', '')),
                    "src": "Reddit"
                })
    return results

# ========== 4. YouTube 频道 RSS（稳定可靠）==========
# 直接订阅头部 AI 频道，比搜索 RSS 稳定得多
YT_CHANNELS = [
    ("Two Minute Papers",  "UCbfYPyITQ-7l4upoX8nvctg"),
    ("Lex Fridman",        "UCSHZKyawb77ixDdsGog4iWA"),
    ("Yannic Kilcher",     "UCZHmQk67mSJgfCCTn7xBfew"),
    ("AI Explained",       "UCwRXb5dUK4cvsHbx-rGzSgw"),
    ("Matt Wolfe",         "UCTz3vy5QJKP0o8SWMBQnY0A"),
]

def youtube_channels(n_per_channel=2):
    results = []
    ns_media = "http://search.yahoo.com/mrss/"
    for ch_name, ch_id in YT_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch_id}"
        tree = fetch_xml(url)
        if tree is None:
            continue
        entries = tree.findall('{http://www.w3.org/2005/Atom}entry')
        for entry in entries[:n_per_channel]:
            title = entry.findtext('{http://www.w3.org/2005/Atom}title', '').strip()
            if title:
                results.append({
                    "title": f"[视频] {title}",
                    "snippet": f"频道: {ch_name}",
                    "src": "YouTube"
                })
        time.sleep(0.3)
    return results

# ========== 5. X / Nitter ==========
NITTERS = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

def x_twitter(query, n=6):
    results = []
    for base in NITTERS:
        url = f"{base}/search/rss?f=tweets&q={quote_plus(query)}"
        tree = fetch_xml(url, timeout=10)
        if tree is None:
            continue
        for item in tree.findall('.//item')[:n]:
            t = item.findtext('title', '').strip()
            if t:
                t = re.sub(r'^R @\w+:\s*', '', t)
                t = re.sub(r'^RT @\w+:\s*', '', t)
                results.append({
                    "title": t,
                    "snippet": clean(item.findtext('description', '')),
                    "src": "X/Twitter"
                })
        if results:
            print(f"  [X] via {base}: {len(results)} 条")
            return results
    return results

# ========== 6. 科技媒体 RSS（英文）==========
TECH_RSS = [
    ("The Verge AI",    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("TechCrunch AI",   "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI",  "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
]

def tech_rss(n_per_feed=4):
    results = []
    for feed_name, url in TECH_RSS:
        tree = fetch_xml(url, timeout=20)
        if tree is None:
            continue
        items = tree.findall('.//item')
        for item in items[:n_per_feed]:
            t = item.findtext('title', '').strip()
            if t:
                results.append({
                    "title": t,
                    "snippet": clean(item.findtext('description', '')),
                    "src": feed_name
                })
        time.sleep(0.3)
    return results

# ========== 7. 中文科技媒体 RSS ==========
CN_RSS = [
    ("36氪",   "https://36kr.com/feed"),
    ("虎嗅",   "https://www.huxiu.com/rss/0.xml"),
    ("极客公园", "https://www.geekpark.net/rss"),
]

AI_KW = re.compile(
    r'(AI|人工智能|大模型|LLM|ChatGPT|GPT|Claude|Gemini|DeepSeek|Kimi|'
    r'文心|千问|智谱|Llama|机器学习|神经网络|算法|语言模型|生成式|AIGC)',
    re.IGNORECASE
)

def cn_tech_rss(n_per_feed=6):
    results = []
    for feed_name, url in CN_RSS:
        tree = fetch_xml(url, timeout=20)
        if tree is None:
            continue
        count = 0
        for item in tree.findall('.//item'):
            t = item.findtext('title', '').strip()
            d = item.findtext('description', '') or ''
            if t and AI_KW.search(t + d):
                results.append({
                    "title": t,
                    "snippet": clean(d),
                    "src": feed_name
                })
                count += 1
                if count >= n_per_feed:
                    break
        time.sleep(0.3)
    return results

# ========== 严格去重 ==========
def title_fp(title):
    t = re.sub(r'^[\s\d\.\,\-\—\(\)\[\]【】]+', '', title.strip())
    t = re.sub(r'[\s\.\,\-\—_\(\)\（\)\[\]\【\】""\'\'、，。；：！？]+', '', t)
    t = re.sub(r'^\[?(视频|VIDEO|BREAKING|重磅|突发|刚刚|快讯|日报)\]?\s*', '', t, flags=re.IGNORECASE)
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
        if not title or len(title) < 8:
            continue
        fp = title_fp(title)
        keep = True
        for ex in unique:
            efp = title_fp(ex['title'])
            if fp == efp:
                keep = False
                break
            if len(fp) >= 15 and fp[:15] == efp[:15]:
                keep = False
                break
            if jaccard(fp, efp) > 0.55:
                keep = False
                break
        if keep:
            unique.append(it)
    return unique

# ========== 生成报告 ==========
CATS = [
    ("OpenAI / ChatGPT",   ["openai","chatgpt","gpt-","gpt5","gpt4","sora","o1 ","o3 ","o4 ","operator"]),
    ("Google / Gemini",    ["google","gemini","deepmind","tpu","bard","workspace"]),
    ("Anthropic / Claude", ["claude","anthropic"]),
    ("国内大模型",         ["腾讯","阿里","百度","kimi","月之暗面","智谱","混元","千问","qwen","minimax","百灵","火山","通义","文心","豆包","deepseek"]),
    ("开源生态",           ["llama","hugging face","github","开源模型","开源大模型","mistral","falcon"]),
    ("视频 & 播客",        ["[视频]","youtube","频道"]),
    ("社交媒体",           ["reddit","x/twitter"]),
]

def generate_report(items):
    items = deduplicate(items)
    print(f"\n去重后: {len(items)} 条")

    cats = {k: [] for k, _ in CATS}
    cats["行业动态"] = []

    for it in items:
        t = (it['title'] + it.get('snippet', '') + it.get('src', '')).lower()
        matched = False
        for cat, kws in CATS:
            if any(k.lower() in t for k in kws):
                cats[cat].append(it)
                matched = True
                break
        if not matched:
            cats["行业动态"].append(it)

    lines = [
        f"AI日报｜{TODAY}",
        "",
        f"共收录 {len(items)} 条（多源聚合去重后）",
        "来源：Google新闻 / Bing新闻 / Reddit / YouTube / X / 36氪 / 虎嗅 / 极客公园 / TechCrunch / The Verge",
        "─" * 50,
        "",
    ]

    for cat in list(dict.fromkeys([k for k, _ in CATS] + ["行业动态"])):
        its = cats.get(cat, [])
        if not its:
            continue
        lines.append(f"【{cat}】（{len(its)} 条）")
        lines.append("")
        for i, it in enumerate(its[:10], 1):
            title = re.sub(r'^\[视频\]\s*', '', it['title'].strip())
            snippet = it.get('snippet', '').strip()
            src = it.get('src', '')
            lines.append(f"{i}. {title}")
            if snippet:
                lines.append(f"   摘要｜{snippet[:100]}")
            lines.append(f"   来源｜{src}")
            lines.append("")

    lines += [
        "─" * 50,
        f"生成时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M')} (CST)",
        "由 GitHub Actions 自动运行，每天 08:00 / 20:00 北京时间推送",
    ]
    return "\n".join(lines)

# ========== 邮件发送 ==========
def send_email(subject, body):
    if not SMTP_PASS:
        print("ERROR: SMTP_PASS not set! 请在 GitHub repo Settings → Secrets 添加 SMTP_PASS", file=sys.stderr)
        sys.exit(1)
    msg = MIMEMultipart()
    msg["From"]    = SMTP_FROM
    msg["To"]      = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_FROM, [TO_EMAIL], msg.as_string())
        s.quit()
        print(f"[OK] 邮件已发送 -> {TO_EMAIL}")
        return True
    except Exception as e:
        print(f"[ERROR] SMTP 发送失败: {e}", file=sys.stderr)
        return False

# ========== 主流程 ==========
def main():
    mode = os.environ.get("REPORT_MODE", "morning").lower()
    label = "早报" if mode == "morning" else "晚报"
    print(f"=== AI {label} v6 === | {TODAY} | {datetime.now(CST).strftime('%H:%M')} CST")

    all_items = []

    # --- Google News 查询 ---
    gn_queries = [
        "AI 人工智能 最新进展 2026",
        "OpenAI ChatGPT 最新动态",
        "Google Gemini Claude Anthropic AI",
        "DeepSeek Kimi 国内大模型 最新",
        "artificial intelligence news 2026",
        "LLM machine learning breakthrough",
    ]
    print("\n[Google News]")
    for q in gn_queries:
        r = google_news(q, n=6)
        print(f"  {q[:40]}: {len(r)} 条")
        all_items.extend(r)
        time.sleep(0.5)

    # --- Bing News ---
    print("\n[Bing News]")
    for q in ["AI大模型 2026", "OpenAI ChatGPT news", "人工智能 今日"]:
        r = bing_news(q, n=5)
        print(f"  {q}: {len(r)} 条")
        all_items.extend(r)
        time.sleep(0.5)

    # --- Reddit ---
    print("\n[Reddit]")
    for q in ["artificial intelligence", "ChatGPT", "LLM AI news"]:
        r = reddit(q, n=5)
        print(f"  {q}: {len(r)} 条")
        all_items.extend(r)
        time.sleep(0.5)

    # --- YouTube 频道 ---
    print("\n[YouTube Channels]")
    r = youtube_channels(n_per_channel=2)
    print(f"  {len(r)} 条视频")
    all_items.extend(r)

    # --- X/Twitter via Nitter ---
    print("\n[X / Nitter]")
    for q in ["AI artificial intelligence", "ChatGPT OpenAI"]:
        r = x_twitter(q, n=5)
        print(f"  {q}: {len(r)} 条")
        all_items.extend(r)
        time.sleep(0.5)

    # --- 英文科技媒体 RSS ---
    print("\n[Tech RSS - 英文]")
    r = tech_rss(n_per_feed=4)
    print(f"  {len(r)} 条")
    all_items.extend(r)

    # --- 中文科技媒体 RSS ---
    print("\n[Tech RSS - 中文]")
    r = cn_tech_rss(n_per_feed=5)
    print(f"  {len(r)} 条")
    all_items.extend(r)

    print(f"\n原始收录: {len(all_items)} 条")

    if not all_items:
        body = f"AI{label}｜{TODAY}\n\n今日数据获取失败，请检查 GitHub Actions 日志。"
    else:
        body = generate_report(all_items)

    subject = f"AI{label}｜{TODAY}"
    ok = send_email(subject, body)

    # 保存到文件（Actions artifact 可查）
    fname = f"ai-report-{TODAY}-{mode}.txt"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"报告已保存 -> {fname}")

    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
