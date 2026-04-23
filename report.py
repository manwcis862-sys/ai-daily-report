#!/usr/bin/env python3
"""
AI行业日报自动生成 + 邮件发送脚本
用于 GitHub Actions 定时执行
搜索使用 Bing RSS + 多源聚合
"""

import os
import sys
import smtplib
import json
import time
import re
import xml.etree.ElementTree as ET
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError

# ========== 配置 ==========
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = os.environ.get("SMTP_EMAIL", "victory3690@qq.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = SMTP_USER
TO_EMAIL = os.environ.get("TO_EMAIL", SMTP_USER)

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime("%Y-%m-%d")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ========== 搜索方法 ==========

def search_bing(query, max_results=8):
    """通过 Bing News RSS 搜索"""
    results = []
    try:
        url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss"
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            tree = ET.fromstring(resp.read())
        for item in tree.findall('.//item')[:max_results]:
            title = item.findtext('title', '').strip()
            desc = item.findtext('description', '').strip()
            link = item.findtext('link', '').strip()
            # 清理 HTML 标签
            desc = re.sub(r'<[^>]+>', '', desc)
            if title:
                results.append({"title": title, "snippet": desc[:200], "link": link})
    except Exception as e:
        print(f"Bing search error: {e}", file=sys.stderr)
    return results


def search_google_news_rss(query, max_results=8):
    """通过 Google News RSS 搜索"""
    results = []
    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            tree = ET.fromstring(resp.read())
        for item in tree.findall('.//item')[:max_results]:
            title = item.findtext('title', '').strip()
            desc = item.findtext('description', '').strip()
            link = item.findtext('link', '').strip()
            desc = re.sub(r'<[^>]+>', '', desc)
            if title:
                results.append({"title": title, "snippet": desc[:200], "link": link})
    except Exception as e:
        print(f"Google News RSS error: {e}", file=sys.stderr)
    return results


def search_searxng(query, max_results=8):
    """使用 SearXNG 公共实例搜索"""
    results = []
    instances = [
        "https://search.sapti.me",
        "https://searx.be",
        "https://search.mdosch.de",
    ]
    for base in instances:
        try:
            url = f"{base}/search?q={quote_plus(query)}&format=json&language=zh"
            req = Request(url, headers={**HEADERS, "Accept": "application/json"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for item in data.get("results", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("content", "")[:200],
                    "link": item.get("url", "")
                })
            if results:
                return results
        except Exception:
            continue
    return results


def search(query, max_results=8):
    """按优先级尝试多种搜索源"""
    # 1. Bing News RSS（最稳定）
    results = search_bing(query, max_results)
    if results:
        return results
    # 2. Google News RSS
    results = search_google_news_rss(query, max_results)
    if results:
        return results
    # 3. SearXNG
    results = search_searxng(query, max_results)
    return results


# ========== 新闻收集 ==========
def gather_news():
    queries = [
        "OpenAI ChatGPT AI 最新消息",
        "Google Gemini Claude AI 大模型",
        "腾讯 阿里 百度 Kimi AI 大模型",
        "DeepSeek Qwen 开源大模型 AI",
        "AI 人工智能 行业动态 最新",
    ]

    all_results = {}
    for q in queries:
        print(f"Searching: {q}")
        results = search(q)
        all_results[q] = results
        print(f"  -> {len(results)} results")
        time.sleep(2)

    return all_results


# ========== 报告生成 ==========
def generate_report(all_results):
    seen_titles = set()
    news_items = []

    for query, results in all_results.items():
        for r in results:
            title = r.get("title", "").strip()
            snippet = r.get("snippet", "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            news_items.append({"title": title, "snippet": snippet, "query": query})

    categories = {
        "OpenAI": [],
        "Google / Gemini": [],
        "Anthropic / Claude": [],
        "国内大模型": [],
        "开源生态": [],
        "行业动态": [],
    }

    for item in news_items:
        t = item["title"] + item["snippet"]
        if any(k in t for k in ["OpenAI", "ChatGPT", "GPT", "Codex"]):
            categories["OpenAI"].append(item)
        elif any(k in t for k in ["Google", "Gemini", "TPU", "DeepMind"]):
            categories["Google / Gemini"].append(item)
        elif any(k in t for k in ["Claude", "Anthropic"]):
            categories["Anthropic / Claude"].append(item)
        elif any(k in t for k in ["腾讯", "阿里", "百度", "Kimi", "月之暗面", "智谱", "混元", "千问", "Qwen", "MiniMax", "百灵", "火山"]):
            categories["国内大模型"].append(item)
        elif any(k in t for k in ["开源", "DeepSeek", "Llama", "GitHub", "Hugging"]):
            categories["开源生态"].append(item)
        else:
            categories["行业动态"].append(item)

    lines = [
        f"AI日报｜{TODAY}",
        "",
        f"共收录 {len(news_items)} 条动态，自动搜索整理。",
        "",
    ]

    for cat, items in categories.items():
        if not items:
            continue
        lines.append(f"【{cat}】")
        for i, item in enumerate(items[:6], 1):
            lines.append(f"  {i}. {item['title']}")
            if item["snippet"]:
                lines.append(f"     {item['snippet']}")
        lines.append("")

    lines.append(f"生成时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"数据来源：Bing News / Google News / SearXNG")

    return "\n".join(lines)


# ========== 邮件发送 ==========
def send_email(subject, body):
    if not SMTP_PASS:
        print("ERROR: SMTP_PASS not set!", file=sys.stderr)
        return False

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM, [TO_EMAIL], msg.as_string())
        server.quit()
        print(f"Email sent to {TO_EMAIL}")
        return True
    except Exception as e:
        print(f"Email error: {e}", file=sys.stderr)
        return False


# ========== 主流程 ==========
def main():
    mode = os.environ.get("REPORT_MODE", "evening").lower()
    print(f"=== AI Daily Report ===")
    print(f"Mode: {mode} | Date: {TODAY} | To: {TO_EMAIL}")

    all_results = gather_news()
    total = sum(len(v) for v in all_results.values())
    print(f"Total results: {total}")

    if total == 0:
        body = f"AI日报｜{TODAY}\n\n今日搜索未获取到结果。\n生成时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M')}"
    else:
        body = generate_report(all_results)

    subject = f"AI早报｜{TODAY}" if mode == "morning" else f"AI晚报｜{TODAY}"
    success = send_email(subject, body)

    report_file = f"ai-report-{TODAY}.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"Report saved to {report_file}")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
