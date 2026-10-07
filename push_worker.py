#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
农历/阳历提醒 · 企业微信群机器人推送

做什么：
  1. 从共享日历的云端数据库读取全部提醒（公开读）
  2. 计算「今天」命中的提醒（当天 / 提前N天）
  3. 汇总成 1 条消息，通过企业微信群机器人发到指定群
  4. 记录已发送，避免同一天重复推送

运行环境：GitHub Actions（每天北京时间 09:07 自动跑），也可本地手动跑。
只依赖 Python 标准库，无需安装任何第三方包。

环境变量：
  WEWORK_WEBHOOK_URL  企业微信群机器人 Webhook 地址（必填，形如
                      https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx）
  WB_ACCESS_KEY       共享日历云端读取密钥（可选，不填用默认值）
  CALENDAR_URL        消息末尾附上的日历网页链接（可选，不填用默认值）
"""
import sys, os, json, argparse, urllib.request, urllib.error, datetime, time

ENDPOINT = "https://lunar-reminder.app.workbuddy.host"
ACCESS_KEY = os.environ.get(
    "WB_ACCESS_KEY",
    "wbpk_UsSYCeH8Cpd3mfPHLSq33H_Y7OTn2r1ljvRgoN4e7iwi23pxrCFPrQQ",
)
# 消息末尾附上的日历网页链接：点进去能看到接下来所有人的生日
CALENDAR_URL = os.environ.get("CALENDAR_URL", ENDPOINT + "/")

# ===== 农历换算（1900-2100 标准数据，与日历网页端一致） =====
lunarInfo = [0x04bd8,0x04ae0,0x0a570,0x054d5,0x0d260,0x0d950,0x16554,0x056a0,0x09ad0,0x055d2,
0x04ae0,0x0a5b6,0x0a4d0,0x0d250,0x1d255,0x0b540,0x0d6a0,0x0ada2,0x095b0,0x14977,
0x04970,0x0a4b0,0x0b4b5,0x06a50,0x06d40,0x1ab54,0x02b60,0x09570,0x052f2,0x04970,
0x06566,0x0d4a0,0x0ea50,0x06e95,0x05ad0,0x02b60,0x186e3,0x092e0,0x1c8d7,0x0c950,
0x0d4a0,0x1d8a6,0x0b550,0x056a0,0x1a5b4,0x025d0,0x092d0,0x0d2b2,0x0a950,0x0b557,
0x06ca0,0x0b550,0x15355,0x04da0,0x0a5b0,0x14573,0x052b0,0x0a9a8,0x0e950,0x06aa0,
0x0aea6,0x0ab50,0x04b60,0x0aae4,0x0a570,0x05260,0x0f263,0x0d950,0x05b57,0x056a0,
0x096d0,0x04dd5,0x04ad0,0x0a4d0,0x0d4d4,0x0d250,0x0d558,0x0b540,0x0b6a0,0x195a6,
0x095b0,0x049b0,0x0a974,0x0a4b0,0x0b27a,0x06a50,0x06d40,0x0af46,0x0ab60,0x09570,
0x04af5,0x04970,0x064b0,0x074a3,0x0ea50,0x06b58,0x055c0,0x0ab60,0x096d5,0x092e0,
0x0c960,0x0d954,0x0d4a0,0x0da50,0x07552,0x056a0,0x0abb7,0x025d0,0x092d0,0x0cab5,
0x0a950,0x0b4a0,0x0baa4,0x0ad50,0x055d9,0x04ba0,0x0a5b0,0x15176,0x052b0,0x0a930,
0x07954,0x06aa0,0x0ad50,0x05b52,0x04b60,0x0a6e6,0x0a4e0,0x0d260,0x0ea65,0x0d530,
0x05aa0,0x076a3,0x096d0,0x04afb,0x04ad0,0x0a4d0,0x1d0b6,0x0d250,0x0d520,0x0dd45,
0x0b5a0,0x056d0,0x055b2,0x049b0,0x0a577,0x0a4b0,0x0aa50,0x1b255,0x06d20,0x0ada0,
0x14b63,0x09370,0x049f8,0x04970,0x064b0,0x168a6,0x0ea50,0x06b20,0x1a6c4,0x0aae0,
0x0a2e0,0x0d2e3,0x0c960,0x0d557,0x0d4a0,0x0da50,0x05d55,0x056a0,0x0a6d0,0x055d4,
0x052d0,0x0a9b8,0x0a950,0x0b4a0,0x0b6a6,0x0ad50,0x055a0,0x0aba4,0x0a5b0,0x052b0,
0x0b273,0x06930,0x07337,0x06aa0,0x0ad50,0x14b55,0x04b60,0x0a570,0x054e4,0x0d160,
0x0e968,0x0d520,0x0daa0,0x16aa6,0x056d0,0x04ae0,0x0a9d4,0x0a2d0,0x0d150,0x0f252,
0x0d520]

def lYearDays(y):
    s = 348
    i = 0x8000
    while i > 0x8:
        if lunarInfo[y-1900] & i: s += 1
        i >>= 1
    return s + leapDays(y)

def leapDays(y):
    if leapMonth(y):
        return 30 if (lunarInfo[y-1900] & 0x10000) else 29
    return 0

def leapMonth(y):
    return lunarInfo[y-1900] & 0xf

def monthDays(y, m):
    return 30 if (lunarInfo[y-1900] & (0x10000 >> m)) else 29

baseDate = datetime.date(1900, 1, 31)

def solarToLunar(yy, mm, dd):
    d = datetime.date(yy, mm, dd)
    offset = (d - baseDate).days
    ly = 1900
    while ly < 2101 and offset > 0:
        offset -= lYearDays(ly); ly += 1
    if offset < 0:
        offset += lYearDays(ly-1); ly -= 1
    leap = leapMonth(ly)
    isLeap = False
    lm = 1
    while lm < 13 and offset > 0:
        if leap > 0 and lm == (leap+1) and not isLeap:
            lm -= 1; isLeap = True; offset -= leapDays(ly)
        else:
            offset -= monthDays(ly, lm)
        lm += 1
        if isLeap and lm == (leap+1):
            isLeap = False
    if offset == 0 and leap > 0 and lm == leap+1:
        if isLeap: isLeap = False
        else: isLeap = True; lm -= 1
    if offset < 0:
        offset += monthDays(ly, lm-1); lm -= 1
    return (ly, lm, offset+1, isLeap, leap)

def lunarToSolar(ly, lm, ld, isLeap):
    if isLeap and leapMonth(ly) != lm: return None
    if ly < 1900 or ly > 2100: return None
    off = 0
    for i in range(1900, ly): off += lYearDays(i)
    d = baseDate + datetime.timedelta(days=off)
    for i in range(1, 13):
        if i == lm and not isLeap: break
        d += datetime.timedelta(days=monthDays(ly, i))
        if leapMonth(ly) == i:
            if lm == i and isLeap: break
            d += datetime.timedelta(days=leapDays(ly))
    maxDay = leapDays(ly) if isLeap else monthDays(ly, lm)
    d += datetime.timedelta(days=min(ld, maxDay)-1)
    return d

monthCN = ["正月","二月","三月","四月","五月","六月","七月","八月","九月","十月","冬月","腊月"]
dayCN = ["初一","初二","初三","初四","初五","初六","初七","初八","初九","初十",
"十一","十二","十三","十四","十五","十六","十七","十八","十九","二十",
"廿一","廿二","廿三","廿四","廿五","廿六","廿七","廿八","廿九","三十"]

def lunarText(lm, ld, isLeap):
    return ("闰" if isLeap else "") + monthCN[lm-1] + dayCN[ld-1]

# ===== 网络请求：带自动重试 =====
# 为什么需要：GitHub 的服务器在国外，连国内网站偶尔会握手超时。
# 重试几次就不会因为一次网络抖动而整个任务失败。
def _fetch(req, timeout=60, tries=3, label=""):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except Exception as e:
            last = e
            if i < tries - 1:
                wait = 5 * (i + 1)
                print("  [重试] %s 第 %d 次失败：%s；%d 秒后再试…" % (label, i + 1, e, wait))
                time.sleep(wait)
    raise last

# ===== 云端读取（公开读，带访问密钥头） =====
def cloud_get(path, params=""):
    url = ENDPOINT + "/.cloud/database/rest/" + path + (("?" + params) if params else "")
    req = urllib.request.Request(url, headers={
        "x-wb-webapp-access-key": ACCESS_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    return json.loads(_fetch(req, 60, 4, "读取 " + path))

def cloud_rpc(func, params, tries=2):
    url = ENDPOINT + "/.cloud/database/rest/rpc/" + func
    data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "x-wb-webapp-access-key": ACCESS_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    return _fetch(req, 60, tries, "调用 " + func)

def nextOccurrence(r, today):
    """算出这条提醒「下一次」发生（含今天）的公历日期"""
    if r.get("type") == "solar":
        y = today.year
        for _ in range(5):
            try:
                d = datetime.date(y, int(r["month"]), int(r["day"]))
            except ValueError:
                return None
            if d >= today: return (d, d.year)
            y += 1
        return None
    else:
        ly = today.year
        d = lunarToSolar(ly, int(r["month"]), int(r["day"]), bool(r.get("leap")))
        if d is None:
            ly += 1; d = lunarToSolar(ly, int(r["month"]), int(r["day"]), bool(r.get("leap")))
        if d is not None and d < today:
            ly += 1; d = lunarToSolar(ly, int(r["month"]), int(r["day"]), bool(r.get("leap")))
        if d is None: return None
        return (d, ly)

# ===== 企业微信群机器人发送 =====
def wework_send(webhook, content):
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last = None
    for i in range(2):
        req = urllib.request.Request(webhook, data=data, method="POST", headers={
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            if resp.get("errcode") != 0:
                raise RuntimeError("企业微信返回错误: %s" % resp)
            return resp
        except Exception as e:
            last = e
            if i == 0:
                print("  [重试] 发送失败：%s；5 秒后再试一次…" % e)
                time.sleep(5)
    raise last

def build_message(due, sent, today):
    """due: [(r, date, ly, off)] → (标题行文本, 消息 markdown, 待记录列表)"""
    items = []
    to_log = []
    for (r, d, ly, off) in due:
        occ_key = "%s_%s_%s" % (r["id"], d.isoformat(), off)
        if occ_key in sent:
            continue
        label = "今天" if off == 0 else "还有 %d 天" % off
        color = "warning" if off == 0 else "comment"
        if r.get("type") == "solar":
            lunar = "阳历 %d月%d日" % (int(r["month"]), int(r["day"]))
        else:
            lunar = "农历 " + lunarText(int(r["month"]), int(r["day"]), bool(r.get("leap")))
        nm = r.get("name", "未命名")
        note = ("（%s）" % r.get("note")) if r.get("note") else ""
        items.append(
            '> <font color="%s">%s</font>　**%s**%s\n'
            "> 　对应公历 %s（%s）" % (color, label, nm, note, d.strftime("%Y-%m-%d"), lunar)
        )
        to_log.append({"reminder_id": int(r["id"]), "occ_key": occ_key})

    if not items:
        return None, None, []

    header = "### 🎂 生日提醒 · %s\n**共 %d 位顾客**\n" % (today.strftime("%m月%d日"), len(items))
    # 末尾附上日历网页链接：点进去能看到接下来所有人的生日
    footer = (
        "\n\n---\n"
        "📅 **完整生日日历**（含接下来所有客户的生日）\n"
        "[👉 点这里打开](%s)" % CALENDAR_URL
    )
    content = header + "\n".join(items) + footer
    return header, content, to_log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印，不发送、不写记录")
    parser.add_argument("--date", default=None, help="模拟日期 YYYY-MM-DD（测试用）")
    parser.add_argument("--webhook", default=os.environ.get("WEWORK_WEBHOOK_URL", ""),
                        help="企业微信群机器人 Webhook 地址")
    args = parser.parse_args()

    today = datetime.date.today() if not args.date else datetime.date.fromisoformat(args.date)

    # 1) 读提醒
    try:
        rows = cloud_get("shared_reminders", "select=id,payload,updated_at&order=updated_at.desc")
    except Exception as e:
        print("读取云端提醒失败:", e); sys.exit(1)
    reminders = []
    for row in rows:
        p = row.get("payload") or {}
        p["id"] = row["id"]
        reminders.append(p)
    print("云端提醒总数:", len(reminders))

    # 2) 读已发送记录
    sent = set()
    try:
        for x in cloud_get("push_log", "select=reminder_id,occ_key"):
            sent.add(str(x.get("occ_key")))
    except Exception as e:
        print("读取发送记录失败(忽略):", e)

    # 3) 算今天命中
    due = []
    for r in reminders:
        if r.get("enabled") is False: continue
        occ = nextOccurrence(r, today)
        if not occ: continue
        d, ly = occ
        diff = (d - today).days
        advance = r.get("advance") or []
        if isinstance(advance, int): advance = [advance]
        for off in advance:
            if diff == int(off):
                due.append((r, d, ly, int(off)))

    if not due:
        print("今日无命中提醒，不发送。")
        return

    header, content, to_log = build_message(due, sent, today)
    if not content:
        print("今日命中项均已发送过，跳过。")
        return

    if args.dry_run:
        print("[DRY-RUN] 将要发送到企业微信群：")
        print(content)
        print("待写记录:", to_log)
        return

    webhook = args.webhook.strip()
    if not webhook:
        print("缺少企业微信群机器人地址（WEWORK_WEBHOOK_URL），无法发送。"); sys.exit(1)

    # 4) 发送
    try:
        wework_send(webhook, content)
        print("已发送企业微信推送，条数:", len(to_log))
    except Exception as e:
        print("发送失败:", e); sys.exit(1)

    # 5) 记录已发送（走云端函数，公开可调用、内部提权写）
    ok = 0
    for item in to_log:
        try:
            cloud_rpc("record_push", {"p_rid": item["reminder_id"], "p_occ": item["occ_key"]})
            ok += 1
        except Exception as e:
            print("记录失败:", item, e)
    print("已记录发送: %d/%d 条" % (ok, len(to_log)))


if __name__ == "__main__":
    main()
