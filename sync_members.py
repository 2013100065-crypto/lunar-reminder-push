#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
千翕医美系统（413cq.cn）→ 农历/阳历提醒日历  客户生日自动同步

做什么：
  1. 用账号密码登录千翕
  2. 分页拉取全部会员
  3. 与日历云端已有记录比对：
       · 新客户            → 加进来
       · 生日被改过的      → 更正
       · 已经一致的        → 跳过，不动它
  4. 只增不删：千翕里删掉的客户，日历这边保留（怕误删，需要自己点删）

特点：
  · 纯 Python 标准库，无需安装任何第三方包
  · 网络请求自带重试（GitHub 服务器在国外，连国内系统偶尔会握手超时）
  · 千翕的内部编号会记在记录里，用来认清"同一个人"（有重名客户）
  · 更新已存在的提醒时，会保留你在网页上自己改过的"提前几天提醒 / 开关 / 备注"

环境变量：
  QX_USER       千翕登录账号
  QX_PWD        千翕登录密码
  EDIT_KEY      日历共享口令（写入需要）
  WB_ACCESS_KEY 日历云端密钥（可选，有默认值）

命令行：
  --dry-run     只打印将要发生的变更，不真正写入
  --limit N     最多写 N 条（调试用）
"""
import sys, os, json, time, argparse, datetime, urllib.request, urllib.error, urllib.parse

# ===== 常量 =====
QX_HOST = "https://www.413cq.cn"
QX_LOGIN = "/sishiyi/login"
QX_LIST = "/sishiyi/personage/queryPersonageByName"
QX_PAGE_SIZE = 50            # 服务端大分页会 504，必须小分页
QX_PAGE_SLEEP = 0.8          # 翻页间隔（秒）
QX_MAX_PAGE = 200            # 防止死循环

ENDPOINT = "https://lunar-reminder.app.workbuddy.host"
ACCESS_KEY = os.environ.get(
    "WB_ACCESS_KEY",
    "wbpk_UsSYCeH8Cpd3mfPHLSq33H_Y7OTn2r1ljvRgoN4e7iwi23pxrCFPrQQ",
)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

CLOUD_HDR = {
    "x-wb-webapp-access-key": ACCESS_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}


# ===== 网络请求：统一重试 =====
def _fetch(req, timeout=60, tries=3, label="", sleep_base=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if i < tries - 1:
                wait = sleep_base * (i + 1)
                print("  [重试] %s 第 %d 次失败：%s；%d 秒后再试…" % (label, i + 1, e, wait))
                time.sleep(wait)
    raise last


def qx_post(path, obj, token=None, timeout=90, tries=4, label=""):
    hdr = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": QX_HOST,
        "Referer": QX_HOST + "/slxd/index.html",
        "User-Agent": UA,
    }
    if token:
        hdr["Authorization"] = token
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(QX_HOST + path, data=data, method="POST", headers=hdr)
    txt = _fetch(req, timeout, tries, label or ("千翕 " + path))
    return json.loads(txt)


def cloud_get(path, params=""):
    url = ENDPOINT + "/.cloud/database/rest/" + path + (("?" + params) if params else "")
    req = urllib.request.Request(url, headers=CLOUD_HDR)
    return json.loads(_fetch(req, 60, 4, "读取云端 " + path))


def cloud_rpc(func, params, tries=3):
    url = ENDPOINT + "/.cloud/database/rest/rpc/" + func
    data = json.dumps(params, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=CLOUD_HDR)
    return _fetch(req, 60, tries, "调用云端 " + func)


# ===== 第一步：登录千翕 =====
def qx_login(user, pwd):
    qs = urllib.parse.urlencode({"user": user, "pwd": pwd, "type": "1"})
    d = qx_post(QX_LOGIN + "?" + qs, {"user": user, "pwd": pwd},
                timeout=60, tries=3, label="千翕登录")
    if d.get("code") != 0:
        raise RuntimeError("千翕登录失败：code=%s msg=%s" % (d.get("code"), d.get("msg")))
    tok = ((d.get("data") or {}).get("token")) or ""
    if not tok:
        raise RuntimeError("千翕登录成功但没拿到 token")
    who = (d.get("data") or {}).get("userName") or (d.get("data") or {}).get("name") or ""
    org = (d.get("data") or {}).get("organizationName") or ""
    print("  ✓ 登录成功（%s / %s），token 长度 %d" % (who, org, len(tok)))
    return tok


# ===== 第二步：拉全部会员 =====
def qx_fetch_members(token):
    all_rows = []
    total = None
    total_page = None
    page = 1
    while page <= QX_MAX_PAGE:
        body = {"xingming": "", "pageNum": page, "pageSize": QX_PAGE_SIZE,
                "orderType": 21, "queryType": "6", "isCache": "0"}
        t0 = time.time()
        r = qx_post(QX_LIST, body, token=token)
        if r.get("code") != 0:
            raise RuntimeError("拉取会员失败（第 %d 页）：code=%s msg=%s"
                               % (page, r.get("code"), r.get("msg")))
        d = r.get("data") or {}
        if total is None:
            total = d.get("count")
            total_page = d.get("totalPage")
            print("  ✓ 服务端共 %s 位会员，%s 页（耗时 %.1fs）" % (total, total_page, time.time() - t0))
        rows = d.get("data") or []
        all_rows.extend(rows)
        print("     第 %d 页：%d 条" % (page, len(rows)))
        if not rows:
            break
        if total_page and page >= int(total_page):
            break
        page += 1
        time.sleep(QX_PAGE_SLEEP)
    return all_rows


# ===== 第三步：把原始会员整理成"姓名 + 月 + 日" =====
def parse_birthday(s):
    """千翕的生日统一是 YYYY-MM-DD；拿不到有效月日就返回 None"""
    s = (s or "").strip()
    if not s:
        return None
    s = s.replace("/", "-").replace(".", "-")
    if " " in s:
        s = s.split(" ")[0]
    if "T" in s:
        s = s.split("T")[0]
    parts = s.split("-")
    if len(parts) < 3:
        return None
    try:
        m = int(parts[1])
        dd = int(parts[2])
    except Exception:
        return None
    if not (1 <= m <= 12 and 1 <= dd <= 31):
        return None
    # 校验该月该日真实存在（用闰年 2000 试）
    try:
        datetime.date(2000, m, dd)
    except ValueError:
        return None
    return (m, dd)


def build_members(rows):
    out, skipped_nobirth, skipped_badname = [], 0, 0
    seen = set()
    for x in rows:
        name = (x.get("xingming") or "").strip()
        qid = str(x.get("id") or "").strip()
        bd = parse_birthday(x.get("chushengriqi"))
        if not name:
            skipped_badname += 1
            continue
        if not bd:
            skipped_nobirth += 1
            continue
        if qid and qid in seen:
            continue
        if qid:
            seen.add(qid)
        out.append({"qid": qid, "name": name, "month": bd[0], "day": bd[1]})
    return out, skipped_nobirth, skipped_badname


# ===== 第四步：比对 + 写入 =====
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印差异，不写入")
    ap.add_argument("--limit", type=int, default=0, help="最多写 N 条（调试用）")
    args = ap.parse_args()

    user = (os.environ.get("QX_USER") or "").strip()
    pwd = (os.environ.get("QX_PWD") or "").strip()
    edit_key = (os.environ.get("EDIT_KEY") or "").strip()
    if not user or not pwd:
        print("缺少千翕账号（QX_USER）或密码（QX_PWD）"); sys.exit(1)
    if not edit_key and not args.dry_run:
        print("缺少日历共享口令（EDIT_KEY），无法写入"); sys.exit(1)

    print("=" * 56)
    print("千翕客户生日 → 日历  自动同步")
    print("时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("模式：%s" % ("试运行（不写入）" if args.dry_run else "正式同步"))
    print("=" * 56)

    # --- 1) 登录千翕 ---
    print("\n[1/4] 登录千翕…")
    try:
        token = qx_login(user, pwd)
    except Exception as e:
        print("✗ 登录失败：%s" % e); sys.exit(2)

    # --- 2) 拉会员 ---
    print("\n[2/4] 拉取会员列表…")
    try:
        raw = qx_fetch_members(token)
    except Exception as e:
        print("✗ 拉取失败：%s" % e); sys.exit(2)
    members, no_birth, bad_name = build_members(raw)
    print("  → 有生日的客户 %d 位（没填生日跳过 %d 位，姓名为空跳过 %d 位）"
          % (len(members), no_birth, bad_name))
    if not members:
        print("没有可同步的客户，退出。"); return

    # --- 3) 读云端现有 ---
    print("\n[3/4] 读取日历云端现有记录…")
    try:
        rows = cloud_get("shared_reminders", "select=id,payload&order=id")
    except Exception as e:
        print("✗ 读取云端失败：%s" % e); sys.exit(2)
    print("  → 云端现有提醒 %d 条" % len(rows))

    by_qid, by_key, by_name = {}, {}, {}
    for r in rows:
        p = dict(r.get("payload") or {})
        p["_id"] = r["id"]
        q = str(p.get("qid") or "").strip()
        if q:
            by_qid.setdefault(q, p)
        try:
            k = (str(p.get("name") or "").strip(), int(p.get("month")), int(p.get("day")))
            by_key.setdefault(k, p)
        except Exception:
            k = None
        by_name.setdefault(str(p.get("name") or "").strip(), []).append(p)

    # --- 4) 逐条比对 ---
    todo_add, todo_update, todo_tag, same = [], [], [], 0
    for m in members:
        hit = by_qid.get(m["qid"])
        if hit:
            if (int(hit.get("month") or 0) != m["month"] or int(hit.get("day") or 0) != m["day"]
                    or str(hit.get("name") or "").strip() != m["name"]):
                todo_update.append((hit, m, "生日或姓名有变化"))
            else:
                same += 1
            continue

        hit = by_key.get((m["name"], m["month"], m["day"]))
        if hit and not str(hit.get("qid") or "").strip():
            todo_tag.append((hit, m, "老记录补上编号"))
            continue
        if hit and str(hit.get("qid") or "").strip() == m["qid"]:
            same += 1
            continue

        # 网页编辑会把编号冲掉：同名且未被别的客户认领的唯一一条，认作同一人
        cands = [p for p in by_name.get(m["name"], []) if not str(p.get("qid") or "").strip()]
        if len(cands) == 1:
            todo_update.append((cands[0], m, "网页改过，按姓名认回同一位"))
            continue

        todo_add.append((None, m, "新客户"))

    print("\n[4/4] 比对结果：")
    print("   ✓ 新增      %d 位" % len(todo_add))
    print("   ✎ 更正      %d 位（生日/姓名变了）" % len(todo_update))
    print("   # 补编号    %d 条（内容没变，只补内部编号）" % len(todo_tag))
    print("   · 无需变动  %d 位" % same)

    if args.dry_run:
        print("\n--- 新增预览（最多 20 条）---")
        for _, m, why in todo_add[:20]:
            print("   ＋ %s  %d月%d日  （%s）" % (m["name"], m["month"], m["day"], why))
        print("\n--- 更正预览（最多 20 条）---")
        for hit, m, why in todo_update[:20]:
            print("   ✎ %s  %s → %d月%d日" % (m["name"],
                  "%s月%s日" % (hit.get("month"), hit.get("day")), m["month"], m["day"]))
        print("\n（试运行结束，什么都没写入）")
        return

    jobs = todo_add + todo_update + todo_tag
    if args.limit:
        jobs = jobs[:args.limit]
        print("（--limit %d，本次最多写 %d 条）" % (args.limit, len(jobs)))
    if not jobs:
        print("\n两边完全一致，无需写入。")
        return

    ok, fail = 0, 0
    for i, (hit, m, why) in enumerate(jobs, 1):
        if hit is not None:
            payload = dict(hit)
            payload.pop("_id", None)
        else:
            payload = {"type": "solar", "leap": False, "advance": [0],
                       "note": "", "enabled": True}
        # 同步的字段：姓名 / 月 / 日 / 编号；其余（提醒时机、开关、备注）保留原样
        payload["name"] = m["name"]
        payload["type"] = "solar"
        payload["month"] = m["month"]
        payload["day"] = m["day"]
        payload["leap"] = False
        payload["qid"] = m["qid"]
        payload.setdefault("advance", [0])
        payload.setdefault("note", "")
        if payload.get("enabled") is None:
            payload["enabled"] = True

        pid = hit["_id"] if hit is not None else 0
        try:
            cloud_rpc("upsert_reminder",
                      {"p_key": edit_key, "p_id": pid, "p_payload": payload})
            ok += 1
            if i % 20 == 0 or i == len(jobs):
                print("   进度 %d/%d" % (i, len(jobs)))
        except Exception as e:
            fail += 1
            print("   ✗ 失败：%s %d月%d日 : %s" % (m["name"], m["month"], m["day"], str(e)[:140]))
        time.sleep(0.2)

    print("\n写入完成：成功 %d 条，失败 %d 条" % (ok, fail))

    # --- 终校验 ---
    try:
        rows2 = cloud_get("shared_reminders", "select=id,payload&order=id")
        print("同步后云端提醒总数：%d 条" % len(rows2))
    except Exception as e:
        print("（终校验读取失败，忽略：%s）" % e)

    if fail:
        print("⚠️ 有个别失败，下次运行会自动重试（同步是幂等的，不会重复）")
        sys.exit(3)


if __name__ == "__main__":
    main()
